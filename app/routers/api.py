from datetime import datetime
from io import BytesIO
import json
import subprocess
import threading
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AnalysisResult, CommentInfo, VideoInfo
from app.db.session import SessionLocal, get_db
from app.schemas.common import (
    AnalyzeRequest,
    AuthorCandidateRequest,
    AuthorVideoRequest,
    BuildTrainsetRequest,
    CommentOut,
    CrawlCommentsRequest,
    CrawlTaskStatus,
    ExportRequest,
    IngestRequest,
    PredictBatchRequest,
    SearchRequest,
    SyncRequest,
    VideoAssetImportRequest,
    VideoOut,
    VideoInsightRequest,
)
from app.services.analyzer import (
    behavior_stats,
    build_local_comment_summary,
    build_local_ops_suggestion,
    build_local_video_insight,
    cluster_topics,
    sentiment as infer_sentiment,
    sentiment_warning,
    simple_topic,
    tokenize,
    top_keywords,
    top_keywords_with_counts,
)
from app.services.deepseek_client import deepseek_service
from app.services.douyin_bridge import (
    build_comment_crawl_cmd,
    fetch_comments_by_video_id,
    fetch_video_media_info,
    fetch_video_by_url,
    fetch_videos_by_author_sec_uid,
    fetch_videos_by_keyword_or_author,
    load_comments_from_output,
    search_author_by_douyin_id_diagnose,
    search_authors_by_name,
    search_authors_by_name_diagnose,
)
from app.services.sentiment_model import sentiment_service
from app.services.training_data import build_trainset
from app.services.qwen_vl_client import qwen_vl_service
from app.services.video_asr import video_asr_service
from app.services.video_visual import video_visual_service


router = APIRouter(prefix="/api", tags=["dy-comments"])
COMMENT_CRAWL_TASKS: dict[str, dict] = {}
COMMENT_CRAWL_LOCK = threading.Lock()
VIDEO_DB_FIELDS = {
    "video_id",
    "title",
    "desc",
    "author_name",
    "author_id",
    "duration",
    "digg_count",
    "comment_count",
    "collect_count",
    "share_count",
    "create_time",
    "music_name",
    "video_url",
}


def _set_comment_task(task_id: str, **updates):
    with COMMENT_CRAWL_LOCK:
        task = COMMENT_CRAWL_TASKS.get(task_id, {}).copy()
        task["task_id"] = task_id
        task.update(updates)
        COMMENT_CRAWL_TASKS[task_id] = task
        return task


def _get_comment_task(task_id: str) -> dict | None:
    with COMMENT_CRAWL_LOCK:
        task = COMMENT_CRAWL_TASKS.get(task_id)
        return task.copy() if task else None


def _dedupe_comments(comments: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for item in comments:
        comment_id = str(item.get("comment_id") or "").strip()
        if not comment_id:
            continue
        deduped[comment_id] = item
    return list(deduped.values())


def _upsert_comments(db: Session, comments: list[dict]) -> int:
    comments = _dedupe_comments(comments)
    synced = 0
    for c in comments:
        row = db.execute(select(CommentInfo).where(CommentInfo.comment_id == c["comment_id"])).scalar_one_or_none()
        if row:
            for k, val in c.items():
                setattr(row, k, val)
        else:
            db.add(CommentInfo(**c))
        synced += 1
    db.commit()
    return synced


def _to_video_db_payload(data: dict) -> dict:
    return {k: v for k, v in data.items() if k in VIDEO_DB_FIELDS}


def _run_comment_crawl_task(task_id: str, payload: CrawlCommentsRequest):
    db = SessionLocal()
    try:
        video = db.execute(select(VideoInfo).where(VideoInfo.video_id == payload.video_id)).scalar_one_or_none()
        if not video:
            _set_comment_task(
                task_id,
                status="failed",
                stage="validate",
                error="video not found",
                message="视频不存在，无法抓取评论",
            )
            return

        analyze_path = Path(settings.dy_analyze_path)
        cmd, out_file = build_comment_crawl_cmd(payload.video_id, payload.comment_limit, payload.reply_limit)
        _set_comment_task(
            task_id,
            status="running",
            stage="validate",
            message="正在启动评论抓取任务",
        )

        proc = subprocess.Popen(
            cmd,
            cwd=str(analyze_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
        )

        if proc.stdout is None:
            raise RuntimeError("unable to read crawler stdout")

        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                _set_comment_task(task_id, message=line)
                continue

            if event.get("type") == "error":
                _set_comment_task(
                    task_id,
                    status="failed",
                    stage=event.get("stage") or "crawl",
                    error=event.get("message") or "comment crawl failed",
                    message=event.get("message") or "comment crawl failed",
                )
                continue

            stage = event.get("stage") or "crawl"
            status = event.get("status") or "running"
            _set_comment_task(
                task_id,
                status="running" if status != "failed" else "failed",
                stage=stage,
                top_count=int(event.get("top_count") or 0),
                top_target=int(event.get("top_target") or payload.comment_limit),
                reply_count=int(event.get("reply_count") or 0),
                reply_done=int(event.get("reply_done") or 0),
                reply_total=int(event.get("reply_total") or 0),
                comments_synced=int(event.get("comments_synced") or 0),
                message=event.get("message") or "",
                video_id=event.get("video_id") or payload.video_id,
            )

        ret = proc.wait()
        if ret != 0:
            current = _get_comment_task(task_id) or {}
            if current.get("status") != "failed":
                _set_comment_task(
                    task_id,
                    status="failed",
                    stage=current.get("stage") or "crawl",
                    error=current.get("message") or f"crawler exited with code {ret}",
                    message=current.get("message") or f"crawler exited with code {ret}",
                )
            return

        comments = load_comments_from_output(payload.video_id, out_file)
        synced = _upsert_comments(db, comments)
        current = _get_comment_task(task_id) or {}
        _set_comment_task(
            task_id,
            status="done",
            stage="save",
            comments_synced=synced,
            top_count=max(int(current.get("top_count") or 0), len([c for c in comments if "_" not in c["comment_id"]])),
            reply_count=max(int(current.get("reply_count") or 0), len([c for c in comments if "_" in c["comment_id"]])),
            message=f"评论已入库，一级评论 {len([c for c in comments if '_' not in c['comment_id']])} 条 / 二级评论 {len([c for c in comments if '_' in c['comment_id']])} 条",
            error="",
        )
    except Exception as e:
        _set_comment_task(
            task_id,
            status="failed",
            stage="crawl",
            error=str(e),
            message=str(e),
        )
    finally:
        db.close()


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "sentiment_model": sentiment_service.model_name,
    }


@router.post("/ingest")
def ingest_data(payload: IngestRequest, db: Session = Depends(get_db)):
    for v in payload.videos:
        media_meta = {
            "video_id": v.video_id,
            "media_url": v.video_url,
            "play_url": "",
            "download_url": "",
            "duration_ms": int(v.duration or 0) * 1000,
            "desc": v.desc,
        }
        video_asr_service.write_media_meta(v.video_id, media_meta)
        item = db.execute(select(VideoInfo).where(VideoInfo.video_id == v.video_id)).scalar_one_or_none()
        if item:
            for k, val in v.model_dump().items():
                setattr(item, k, val)
        else:
            db.add(VideoInfo(**v.model_dump()))

    deduped_comments = _dedupe_comments([c.model_dump() for c in payload.comments])
    for c in deduped_comments:
        item = db.execute(select(CommentInfo).where(CommentInfo.comment_id == c["comment_id"])).scalar_one_or_none()
        if item:
            for k, val in c.items():
                setattr(item, k, val)
        else:
            db.add(CommentInfo(**c))

    db.commit()
    return {
        "ok": True,
        "videos": len(payload.videos),
        "comments": len(payload.comments),
    }


@router.post("/sync/from-existing")
def sync_from_existing(payload: SyncRequest, db: Session = Depends(get_db)):
    if not payload.keyword and not payload.author_name and not payload.douyin_id and not payload.comment_video_id:
        if not payload.video_url:
            raise HTTPException(status_code=400, detail="keyword/author_name/douyin_id/video_url/comment_video_id at least one is required")

    videos = []
    comments = []

    if payload.video_url:
        single = fetch_video_by_url(payload.video_url)
        if single:
            videos = [single]
    elif payload.keyword or payload.author_name or payload.douyin_id:
        videos = fetch_videos_by_keyword_or_author(
            payload.keyword,
            payload.author_name,
            payload.video_limit,
            douyin_id=payload.douyin_id,
        )

    for v in videos:
        media_meta = {
            "video_id": v["video_id"],
            "media_url": str(v.get("media_url") or v.get("download_url") or v.get("play_url") or ""),
            "play_url": str(v.get("play_url") or ""),
            "download_url": str(v.get("download_url") or ""),
            "duration_ms": int(v.get("duration") or 0) * 1000,
            "desc": str(v.get("desc") or ""),
        }
        video_asr_service.write_media_meta(v["video_id"], media_meta)
        db_payload = _to_video_db_payload(v)
        row = db.execute(select(VideoInfo).where(VideoInfo.video_id == v["video_id"])).scalar_one_or_none()
        if row:
            for k, val in db_payload.items():
                setattr(row, k, val)
        else:
            db.add(VideoInfo(**db_payload))

    target_video_ids = []
    if payload.comment_video_id:
        target_video_ids.append(payload.comment_video_id)
    if payload.crawl_comments_for_found_videos:
        target_video_ids.extend([v["video_id"] for v in videos if v.get("video_id")])
    target_video_ids = list(dict.fromkeys(target_video_ids))

    for vid in target_video_ids:
        crawled = fetch_comments_by_video_id(vid, payload.comment_limit, payload.reply_limit)
        comments.extend(crawled)

    comments = _dedupe_comments(comments)
    _upsert_comments(db, comments)

    return {
        "ok": True,
        "videos_synced": len(videos),
        "comments_synced": len(comments),
        "video_ids": target_video_ids,
        "note": "Only comment_video_id is crawled by default. Set crawl_comments_for_found_videos=true to crawl all found videos.",
    }


@router.post("/authors/candidates")
def author_candidates(payload: AuthorCandidateRequest):
    author_name = (payload.author_name or "").strip()
    douyin_id = (payload.douyin_id or "").strip()
    if not author_name and not douyin_id:
        raise HTTPException(status_code=400, detail="author_name or douyin_id is required")
    try:
        if douyin_id:
            result = search_author_by_douyin_id_diagnose(douyin_id, payload.limit)
        else:
            result = search_authors_by_name_diagnose(author_name, payload.limit)
        rows = result.get("results") or []
        if not rows:
            attempts = result.get("diagnosis", {}).get("attempts", [])
            blocked = any("WinError 10013" in str(item.get("error", "")) for item in attempts)
            raise HTTPException(
                status_code=503 if blocked else 404,
                detail={
                    "message": "no author candidates found from all paths or no exact douyin_id match",
                    "network_blocked": blocked,
                    "hint": "check diagnosis.attempts; if template path fails, refresh template URL capture in DouYin_Spider or browser cookies",
                    "diagnosis": result.get("diagnosis", {}),
                },
            )
        return {
            "items": rows,
            "source": result.get("source", ""),
            "diagnosis": result.get("diagnosis", {}),
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"author search failed: {e}")


@router.post("/authors/videos")
def author_videos(payload: AuthorVideoRequest, db: Session = Depends(get_db)):
    try:
        fetch_limit = 10000 if payload.fetch_all else max(int(payload.limit), 1)
        fetched = fetch_videos_by_author_sec_uid(payload.author_sec_uid, fetch_limit, payload.author_name or "")
        if not fetched:
            raise HTTPException(
                status_code=404,
                detail="no videos returned for selected author (possible cookie invalid/risk-control or author has no public works)",
            )
        for v in fetched:
            media_meta = {
                "video_id": v["video_id"],
                "media_url": str(v.get("media_url") or v.get("download_url") or v.get("play_url") or ""),
                "play_url": str(v.get("play_url") or ""),
                "download_url": str(v.get("download_url") or ""),
                "duration_ms": int(v.get("duration") or 0) * 1000,
                "desc": str(v.get("desc") or ""),
            }
            video_asr_service.write_media_meta(v["video_id"], media_meta)
            db_payload = _to_video_db_payload(v)
            item = db.execute(select(VideoInfo).where(VideoInfo.video_id == v["video_id"])).scalar_one_or_none()
            if item:
                for k, val in db_payload.items():
                    setattr(item, k, val)
            else:
                db.add(VideoInfo(**db_payload))
        db.commit()
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"author videos fetch failed: {e}")

    out = []
    for v in fetched:
        row = db.execute(select(VideoInfo).where(VideoInfo.video_id == v["video_id"])).scalar_one_or_none()
        if row:
            out.append(VideoOut.model_validate(row).model_dump())

    reverse = payload.sort_order == "desc"

    def _sort_key(item):
        if payload.sort_by == "create_time":
            value = item.get("create_time")
            return str(value or "")
        return int(item.get(payload.sort_by) or 0)

    out.sort(key=_sort_key, reverse=reverse)

    total = len(out)
    page = max(1, int(payload.page))
    limit = max(1, int(payload.limit))
    start = (page - 1) * limit
    end = start + limit
    page_items = out[start:end]

    return {
        "items": page_items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit,
        },
        "sort": {
            "sort_by": payload.sort_by,
            "sort_order": payload.sort_order,
        },
    }


@router.post("/search")
def search_video(payload: SearchRequest, db: Session = Depends(get_db)):
    if not any(
        [
            (payload.video_id or "").strip(),
            (payload.author_name or "").strip(),
            (payload.douyin_id or "").strip(),
            (payload.author_sec_uid or "").strip(),
            (payload.author_id or "").strip(),
            (payload.keyword or "").strip(),
        ]
    ):
        return []

    if payload.video_id and payload.video_id.strip():
        video_id = payload.video_id.strip()
        row = db.execute(select(VideoInfo).where(VideoInfo.video_id == video_id)).scalar_one_or_none()
        if row:
            return [VideoOut.model_validate(row).model_dump()]

        if payload.remote_fallback:
            single = fetch_video_by_url(f"https://www.douyin.com/video/{video_id}")
            if single and single.get("video_id"):
                media_meta = {
                    "video_id": single["video_id"],
                    "media_url": str(single.get("media_url") or single.get("download_url") or single.get("play_url") or ""),
                    "play_url": str(single.get("play_url") or ""),
                    "download_url": str(single.get("download_url") or ""),
                    "duration_ms": int(single.get("duration") or 0) * 1000,
                    "desc": str(single.get("desc") or ""),
                }
                video_asr_service.write_media_meta(single["video_id"], media_meta)
                db_payload = _to_video_db_payload(single)
                existing = db.execute(select(VideoInfo).where(VideoInfo.video_id == single["video_id"])).scalar_one_or_none()
                if existing:
                    for k, val in db_payload.items():
                        setattr(existing, k, val)
                else:
                    db.add(VideoInfo(**db_payload))
                db.commit()
                saved = db.execute(select(VideoInfo).where(VideoInfo.video_id == single["video_id"])).scalar_one_or_none()
                if saved:
                    return [VideoOut.model_validate(saved).model_dump()]
        return []

    def _query_local():
        if payload.author_sec_uid and not payload.author_name and not payload.keyword:
            return []

        stmt = select(VideoInfo)
        if payload.author_name:
            stmt = stmt.where(VideoInfo.author_name.contains(payload.author_name))
        if payload.author_id:
            stmt = stmt.where(VideoInfo.author_id == payload.author_id)
        if payload.keyword:
            stmt = stmt.where(VideoInfo.title.contains(payload.keyword))
        stmt = stmt.order_by(desc(VideoInfo.digg_count)).limit(payload.limit)
        return db.execute(stmt).scalars().all()

    rows = _query_local()
    if rows:
        return [VideoOut.model_validate(r).model_dump() for r in rows]

    # Fallback: call existing spider project when local DB has no hit.
    if payload.remote_fallback and (payload.keyword or payload.author_name or payload.douyin_id or payload.author_sec_uid):
        try:
            fetched = fetch_videos_by_keyword_or_author(
                keyword=payload.keyword,
                author_name=payload.author_name,
                limit=payload.limit,
                author_sec_uid=payload.author_sec_uid,
                douyin_id=payload.douyin_id,
            )
            for v in fetched:
                media_meta = {
                    "video_id": v["video_id"],
                    "media_url": str(v.get("media_url") or v.get("download_url") or v.get("play_url") or ""),
                    "play_url": str(v.get("play_url") or ""),
                    "download_url": str(v.get("download_url") or ""),
                    "duration_ms": int(v.get("duration") or 0) * 1000,
                    "desc": str(v.get("desc") or ""),
                }
                video_asr_service.write_media_meta(v["video_id"], media_meta)
                db_payload = _to_video_db_payload(v)
                item = db.execute(select(VideoInfo).where(VideoInfo.video_id == v["video_id"])).scalar_one_or_none()
                if item:
                    for k, val in db_payload.items():
                        setattr(item, k, val)
                else:
                    db.add(VideoInfo(**db_payload))
            db.commit()
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=502,
                detail=f"remote search failed: {e}",
            )

        rows = _query_local()

    return [VideoOut.model_validate(r).model_dump() for r in rows]


@router.get("/videos")
def list_videos(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.execute(select(VideoInfo).order_by(desc(VideoInfo.created_at)).limit(limit)).scalars().all()
    return [VideoOut.model_validate(r).model_dump() for r in rows]


@router.get("/comments/{video_id}")
def list_comments(video_id: str, limit: int = Query(default=200, ge=1, le=2000), db: Session = Depends(get_db)):
    rows = (
        db.execute(
            select(CommentInfo)
            .where(CommentInfo.video_id == video_id)
            .order_by(desc(CommentInfo.create_time), desc(CommentInfo.created_at))
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [CommentOut.model_validate(r).model_dump() for r in rows]


@router.post("/analyze")
def analyze_video(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    video = db.execute(select(VideoInfo).where(VideoInfo.video_id == payload.video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    comments = db.execute(select(CommentInfo).where(CommentInfo.video_id == payload.video_id)).scalars().all()
    if not comments:
        raise HTTPException(status_code=400, detail="no comments for this video")

    if payload.force_reanalyze:
        db.query(AnalysisResult).filter(AnalysisResult.comment_id.in_([c.comment_id for c in comments])).delete(synchronize_session=False)
        db.commit()

    existing = {
        a.comment_id: a
        for a in db.execute(
            select(AnalysisResult).where(AnalysisResult.comment_id.in_([c.comment_id for c in comments]))
        )
        .scalars()
        .all()
    }

    texts = [c.content for c in comments]
    cluster_labels = cluster_topics(texts)

    generated = 0
    sentiment_list = []
    for i, c in enumerate(comments):
        words = tokenize(c.content)
        sentiment_label = infer_sentiment(c.content)
        sentiment_list.append(sentiment_label)
        topic = f"topic_{cluster_labels[i]}_{simple_topic(words)}"
        kw = words[:8]

        if c.comment_id in existing and not payload.force_reanalyze:
            continue

        row = AnalysisResult(
            comment_id=c.comment_id,
            sentiment=sentiment_label,
            keywords=",".join(kw),
            topic=topic,
            summary="",
            suggestion="",
        )
        db.add(row)
        generated += 1

    db.commit()

    sentiment_counter = {
        "Positive": sentiment_list.count("Positive"),
        "Neutral": sentiment_list.count("Neutral"),
        "Negative": sentiment_list.count("Negative"),
    }

    keyword_stats = top_keywords_with_counts(texts, 50)
    warning = sentiment_warning(sentiment_list, texts)
    comment_summary = deepseek_service.summarize_comments(
        comments=texts,
        video_meta={
            "video_id": video.video_id,
            "title": video.title,
            "author_name": video.author_name,
            "desc": video.desc,
        },
        sentiment_counter=sentiment_counter,
        keyword_stats=keyword_stats,
    )
    if not comment_summary:
        comment_summary = build_local_comment_summary(
            video_meta={
                "video_id": video.video_id,
                "title": video.title,
                "author_name": video.author_name,
                "desc": video.desc,
            },
            comments=texts,
            sentiments=sentiment_list,
            keyword_stats=keyword_stats,
        )
    ops_suggestion = deepseek_service.generate_suggestion(
        {
            "video_id": video.video_id,
            "title": video.title,
            "author_name": video.author_name,
            "desc": video.desc,
            "digg_count": video.digg_count,
            "comment_count": video.comment_count,
            "collect_count": video.collect_count,
            "share_count": video.share_count,
        },
        comment_summary,
        warning,
        keyword_stats=keyword_stats,
        top_comments=[c.content for c in sorted(comments, key=lambda x: x.digg_count, reverse=True)[:10]],
    )
    if not ops_suggestion:
        ops_suggestion = build_local_ops_suggestion(
            video_meta={
                "video_id": video.video_id,
                "title": video.title,
                "author_name": video.author_name,
                "desc": video.desc,
            },
            warning=warning,
            keyword_stats=keyword_stats,
            top_comments=[c.content for c in sorted(comments, key=lambda x: x.digg_count, reverse=True)[:10]],
        )

    db.query(AnalysisResult).filter(AnalysisResult.comment_id.in_([c.comment_id for c in comments])).update(
        {AnalysisResult.summary: comment_summary, AnalysisResult.suggestion: ops_suggestion},
        synchronize_session=False,
    )
    db.commit()

    behavior = behavior_stats([c.create_time for c in comments])

    return {
        "video_id": payload.video_id,
        "analyzed_comments": len(comments),
        "new_rows": generated,
        "sentiment_distribution": sentiment_counter,
        "top_keywords": [item["keyword"] for item in keyword_stats],
        "top_keyword_stats": keyword_stats,
        "behavior": behavior,
        "warning": warning,
        "comment_summary": comment_summary,
        "ops_suggestion": ops_suggestion,
        "sentiment_model": sentiment_service.model_name,
    }


@router.post("/analyze/video-content")
def analyze_video_content(payload: VideoInsightRequest, db: Session = Depends(get_db)):
    video = db.execute(select(VideoInfo).where(VideoInfo.video_id == payload.video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    comments = db.execute(select(CommentInfo).where(CommentInfo.video_id == payload.video_id)).scalars().all()
    texts = [c.content for c in comments]

    sentiment_counter = {"Positive": 0, "Neutral": 0, "Negative": 0}
    if texts:
        for text in texts:
            sentiment_counter[infer_sentiment(text)] += 1

    keyword_stats = top_keywords_with_counts(texts, 30) if texts else []
    top_comments = [c.content for c in sorted(comments, key=lambda x: x.digg_count, reverse=True)[:10]]
    comment_summary = ""
    if texts:
        comment_summary = deepseek_service.summarize_comments(
            comments=texts,
            video_meta={
                "video_id": video.video_id,
                "title": video.title,
                "author_name": video.author_name,
                "desc": video.desc,
            },
            sentiment_counter=sentiment_counter,
            keyword_stats=keyword_stats,
        ) or build_local_comment_summary(
            video_meta={
                "video_id": video.video_id,
                "title": video.title,
                "author_name": video.author_name,
                "desc": video.desc,
            },
            comments=texts,
            sentiments=[infer_sentiment(text) for text in texts],
            keyword_stats=keyword_stats,
        )

    transcript_data = {}
    transcript_text = ""
    transcript_summary = ""
    transcript_key_clips: list[str] = []
    metrics = {}
    media_info = video_asr_service.read_media_meta(video.video_id) or {}
    transcript_error = ""
    transcript_error_hint = ""
    try:
        transcript_data = video_asr_service.transcribe_video(video.video_id, force_refresh=False)
        transcript_text = str(transcript_data.get("transcript") or "").strip()
        transcript_summary = video_asr_service.summarize_transcript(transcript_text)
        transcript_key_clips = video_asr_service.build_key_clips(transcript_text)
        metrics = transcript_data.get("metrics") or {}
        if not media_info:
            media_info = {
                "media_url": transcript_data.get("media_url") or "",
                "duration_ms": 0,
            }
    except Exception as e:
        transcript_error = str(e)
        transcript_error_hint = video_asr_service.explain_transcript_error(transcript_error)

    visual_data = {}
    visual_summary = ""
    visual_frames: list[dict] = []
    visual_error = ""
    mp4_path = str(transcript_data.get("mp4_path") or video_asr_service.get_cached_mp4_path(video.video_id) or "")
    if mp4_path:
        try:
            visual_data = video_visual_service.analyze_video(video.video_id, mp4_path, force_refresh=False)
            visual_summary = str(visual_data.get("visual_style_summary") or "").strip()
            visual_frames = list(visual_data.get("frames") or [])
        except Exception as e:
            visual_error = str(e)

    qwen_video_insight = qwen_vl_service.analyze_video(
        video_meta={
            "video_id": video.video_id,
            "title": video.title,
            "desc": video.desc,
            "author_name": video.author_name,
            "digg_count": video.digg_count,
            "comment_count": video.comment_count,
            "collect_count": video.collect_count,
            "share_count": video.share_count,
            "video_url": video.video_url,
            "media_duration_ms": media_info.get("duration_ms") or 0,
        },
        transcript=transcript_text,
        transcript_summary=transcript_summary,
        key_clips=transcript_key_clips,
        visual_summary=visual_summary,
        visual_frames=list(visual_data.get("frames") or []),
    )

    insight_provider = "deepseek"
    insight = deepseek_service.analyze_video_content(
        video_meta={
            "video_id": video.video_id,
            "title": video.title,
            "desc": video.desc,
            "author_name": video.author_name,
            "digg_count": video.digg_count,
            "comment_count": video.comment_count,
            "collect_count": video.collect_count,
            "share_count": video.share_count,
            "video_url": video.video_url,
            "media_duration_ms": media_info.get("duration_ms") or 0,
        },
        qwen_insight=qwen_video_insight,
        sentiment_counter=sentiment_counter,
        keyword_stats=keyword_stats,
        top_comments=top_comments,
        comment_summary=comment_summary,
        transcript=transcript_text,
        transcript_summary=transcript_summary,
        key_clips=transcript_key_clips,
        visual_summary=visual_summary,
        visual_frames=visual_frames,
    )
    if not insight:
        insight_provider = "local_fallback"
        insight = build_local_video_insight(
            video_meta={
                "video_id": video.video_id,
                "title": video.title,
                "desc": video.desc,
                "author_name": video.author_name,
            },
            sentiment_counter=sentiment_counter,
            keyword_stats=keyword_stats,
            top_comments=top_comments,
            transcript=transcript_text,
            transcript_summary=transcript_summary,
            key_clips=transcript_key_clips,
            visual_summary=visual_summary,
            qwen_insight=qwen_video_insight,
        )

    return {
        "video_id": video.video_id,
        "video_title": video.title,
        "author_name": video.author_name,
        "insight": insight,
        "video_insight_provider": insight_provider,
        "qwen_video_insight": qwen_video_insight,
        "transcript": transcript_text,
        "transcript_summary": transcript_summary,
        "transcript_key_clips": transcript_key_clips,
        "transcript_preview": transcript_text[:500],
        "transcript_metrics": metrics,
        "transcript_error": transcript_error,
        "transcript_error_hint": transcript_error_hint,
        "visual_summary": visual_summary,
        "visual_frames": video_visual_service.frame_public_items(video.video_id, visual_data) if visual_frames else [],
        "visual_error": visual_error,
        "sentiment_distribution": sentiment_counter,
        "top_keyword_stats": keyword_stats,
        "top_comments": top_comments[:5],
        "has_comments": bool(texts),
    }


@router.get("/video-assets/status/{video_id}")
def video_asset_status(video_id: str, db: Session = Depends(get_db)):
    video = db.execute(select(VideoInfo).where(VideoInfo.video_id == video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    diagnostics = video_asr_service.media_diagnostics(video_id)
    transcript_data = video_asr_service.read_cached_transcript(video_id) or {}
    visual_data = video_visual_service.read_cached_visual_analysis(video_id) or {}

    return {
        "video_id": video_id,
        "title": video.title,
        "author_name": video.author_name,
        "diagnostics": diagnostics,
        "transcript_preview": str(transcript_data.get("transcript") or "")[:500],
        "transcript_summary": video_asr_service.summarize_transcript(str(transcript_data.get("transcript") or "")),
        "transcript_key_clips": video_asr_service.build_key_clips(str(transcript_data.get("transcript") or "")),
        "visual_summary": str(visual_data.get("visual_style_summary") or ""),
        "visual_frames": video_visual_service.frame_public_items(video_id, visual_data),
    }


@router.post("/video-assets/import-mp4")
def import_video_asset(payload: VideoAssetImportRequest, db: Session = Depends(get_db)):
    video = db.execute(select(VideoInfo).where(VideoInfo.video_id == payload.video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    try:
        result = video_asr_service.import_local_mp4(
            payload.video_id,
            payload.mp4_path,
            overwrite=payload.overwrite,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "ok": True,
        "video_id": payload.video_id,
        "title": video.title,
        "result": result,
        "diagnostics": video_asr_service.media_diagnostics(payload.video_id),
    }


@router.post("/comments/crawl")
def crawl_comments(payload: CrawlCommentsRequest, db: Session = Depends(get_db)):
    video = db.execute(select(VideoInfo).where(VideoInfo.video_id == payload.video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    comments = fetch_comments_by_video_id(payload.video_id, payload.comment_limit, payload.reply_limit)
    synced = _upsert_comments(db, comments)

    return {
        "ok": True,
        "video_id": payload.video_id,
        "comments_synced": synced,
        "comment_limit": payload.comment_limit,
        "reply_limit": payload.reply_limit,
    }


@router.post("/comments/crawl/start", response_model=CrawlTaskStatus)
def crawl_comments_start(payload: CrawlCommentsRequest, db: Session = Depends(get_db)):
    video = db.execute(select(VideoInfo).where(VideoInfo.video_id == payload.video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    task_id = uuid.uuid4().hex
    _set_comment_task(
        task_id,
        status="queued",
        stage="validate",
        video_id=payload.video_id,
        top_count=0,
        top_target=payload.comment_limit,
        reply_count=0,
        reply_done=0,
        reply_total=0,
        comments_synced=0,
        message="评论抓取任务已创建",
        error="",
    )
    worker = threading.Thread(target=_run_comment_crawl_task, args=(task_id, payload), daemon=True)
    worker.start()
    return CrawlTaskStatus(**(_get_comment_task(task_id) or {}))


@router.get("/comments/crawl/status/{task_id}", response_model=CrawlTaskStatus)
def crawl_comments_status(task_id: str):
    task = _get_comment_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="crawl task not found")
    return CrawlTaskStatus(**task)


@router.post("/sentiment/predict")
def predict_sentiment_batch(payload: PredictBatchRequest):
    result = []
    for text in payload.texts:
        pred = infer_sentiment(text)
        result.append({"text": text, "label": pred})
    return {
        "model": sentiment_service.model_name,
        "results": result,
    }


@router.post("/sentiment/build-trainset")
def sentiment_build_trainset(payload: BuildTrainsetRequest, db: Session = Depends(get_db)):
    res = build_trainset(
        db=db,
        output_csv=payload.output_csv,
        video_id=payload.video_id,
        sample_size=payload.sample_size,
        strategy=payload.strategy,
        manual_csv=payload.manual_csv,
    )
    return res


@router.post("/sentiment/finetune")
def sentiment_finetune(
    train_csv: str,
    output_dir: str = "./models/roberta_sentiment_3cls",
    epochs: int = 3,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
):
    cmd = [
        "python",
        "scripts/finetune_roberta_3cls.py",
        "--train-csv",
        train_csv,
        "--output-dir",
        output_dir,
        "--base-model",
        settings.sentiment_base_model,
        "--epochs",
        str(epochs),
        "--batch-size",
        str(batch_size),
        "--learning-rate",
        str(learning_rate),
        "--max-length",
        str(settings.sentiment_max_length),
    ]
    proc = subprocess.run(cmd, cwd=".", capture_output=True, text=True)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr or proc.stdout)
    return {
        "ok": True,
        "stdout": proc.stdout,
        "model_dir": output_dir,
    }


@router.post("/sentiment/reload")
def sentiment_reload():
    sentiment_service.reset()
    _ = sentiment_service.classify("测试")
    return {
        "ok": True,
        "model": sentiment_service.model_name,
        "id2label": sentiment_service.id2label,
    }


@router.get("/dashboard/{video_id}")
def dashboard(video_id: str, db: Session = Depends(get_db)):
    video = db.execute(select(VideoInfo).where(VideoInfo.video_id == video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    comments = db.execute(select(CommentInfo).where(CommentInfo.video_id == video_id)).scalars().all()
    if not comments:
        raise HTTPException(status_code=400, detail="no comments")

    analysis_rows = (
        db.execute(
            select(AnalysisResult, CommentInfo)
            .join(CommentInfo, AnalysisResult.comment_id == CommentInfo.comment_id)
            .where(CommentInfo.video_id == video_id)
        )
        .all()
    )

    sentiments = [r[0].sentiment for r in analysis_rows]
    sentiment_counter = {
        "Positive": sentiments.count("Positive"),
        "Neutral": sentiments.count("Neutral"),
        "Negative": sentiments.count("Negative"),
    }

    top_comments = sorted(comments, key=lambda x: x.digg_count, reverse=True)[:10]
    trend = {}
    for c in comments:
        if c.create_time:
            day = c.create_time.date().isoformat()
            trend[day] = trend.get(day, 0) + 1

    texts = [c.content for c in comments]
    kw_stats = top_keywords_with_counts(texts, 30)
    kw = [item["keyword"] for item in kw_stats]
    behavior = behavior_stats([c.create_time for c in comments])
    warning = sentiment_warning(sentiments, texts)

    summary_row = db.execute(
        select(AnalysisResult.summary, AnalysisResult.suggestion)
        .join(CommentInfo, AnalysisResult.comment_id == CommentInfo.comment_id)
        .where(CommentInfo.video_id == video_id)
        .limit(1)
    ).first()

    summary_text = summary_row[0] if summary_row and summary_row[0] else build_local_comment_summary(
        video_meta={
            "video_id": video.video_id,
            "title": video.title,
            "author_name": video.author_name,
            "desc": video.desc,
        },
        comments=texts,
        sentiments=sentiments,
        keyword_stats=kw_stats,
    )
    suggestion_text = summary_row[1] if summary_row and summary_row[1] else build_local_ops_suggestion(
        video_meta={
            "video_id": video.video_id,
            "title": video.title,
            "author_name": video.author_name,
            "desc": video.desc,
        },
        warning=warning,
        keyword_stats=kw_stats,
        top_comments=[c.content for c in top_comments],
    )

    transcript_data = video_asr_service.read_cached_transcript(video_id) or {}
    transcript_text = str(transcript_data.get("transcript") or "").strip()
    transcript_metrics = transcript_data.get("metrics") or {}
    transcript_summary = video_asr_service.summarize_transcript(transcript_text)
    transcript_key_clips = video_asr_service.build_key_clips(transcript_text)
    visual_data = video_visual_service.read_cached_visual_analysis(video_id) or {}
    visual_summary = str(visual_data.get("visual_style_summary") or "").strip()
    visual_frames = video_visual_service.frame_public_items(video_id, visual_data)

    return {
        "video": {
            "video_id": video.video_id,
            "title": video.title,
            "author_name": video.author_name,
            "digg_count": video.digg_count,
            "comment_count": video.comment_count,
            "collect_count": video.collect_count,
            "share_count": video.share_count,
            "video_url": video.video_url,
        },
        "comment_total": len(comments),
        "sentiment": sentiment_counter,
        "keyword_top": kw,
        "keyword_top_stats": kw_stats,
        "comment_trend": trend,
        "active_hours": behavior["active_hours"],
        "warning": warning,
        "top_comments": [
            {
                "comment_id": c.comment_id,
                "user_name": c.user_name,
                "content": c.content,
                "digg_count": c.digg_count,
                "reply_count": c.reply_count,
                "ip_label": c.ip_label,
            }
            for c in top_comments
        ],
        "summary": summary_text,
        "suggestion": suggestion_text,
        "transcript": transcript_text,
        "transcript_summary": transcript_summary,
        "transcript_key_clips": transcript_key_clips,
        "transcript_metrics": transcript_metrics,
        "visual_summary": visual_summary,
        "visual_frames": visual_frames,
    }


@router.get("/video-assets/frame")
def video_frame_asset(video_id: str, name: str):
    base_dir = (Path(settings.asr_cache_dir).resolve() / video_id / "frames").resolve()
    target = (base_dir / name).resolve()
    if not str(target).startswith(str(base_dir)):
        raise HTTPException(status_code=400, detail="invalid frame path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="frame not found")
    return FileResponse(str(target))


@router.post("/export")
def export_result(payload: ExportRequest, db: Session = Depends(get_db)):
    video = db.execute(select(VideoInfo).where(VideoInfo.video_id == payload.video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    comments = db.execute(select(CommentInfo).where(CommentInfo.video_id == payload.video_id)).scalars().all()
    if not comments:
        raise HTTPException(status_code=404, detail="no data to export")

    dashboard_data = dashboard(payload.video_id, db)
    insight_data = analyze_video_content(VideoInsightRequest(video_id=payload.video_id), db)

    summary_rows = [
        {"section": "视频信息", "metric": "视频ID", "value": video.video_id},
        {"section": "视频信息", "metric": "标题", "value": video.title},
        {"section": "视频信息", "metric": "作者", "value": video.author_name},
        {"section": "视频信息", "metric": "点赞数", "value": video.digg_count},
        {"section": "视频信息", "metric": "评论数", "value": video.comment_count},
        {"section": "视频信息", "metric": "收藏数", "value": video.collect_count},
        {"section": "视频信息", "metric": "分享数", "value": video.share_count},
        {"section": "视频信息", "metric": "视频链接", "value": video.video_url},
        {"section": "分析结果", "metric": "评论总数", "value": dashboard_data["comment_total"]},
        {"section": "分析结果", "metric": "正向评论", "value": dashboard_data["sentiment"]["Positive"]},
        {"section": "分析结果", "metric": "中性评论", "value": dashboard_data["sentiment"]["Neutral"]},
        {"section": "分析结果", "metric": "负向评论", "value": dashboard_data["sentiment"]["Negative"]},
        {"section": "分析结果", "metric": "舆情预警", "value": "是" if dashboard_data["warning"]["warning"] else "否"},
        {"section": "分析结果", "metric": "负向占比", "value": dashboard_data["warning"]["negative_ratio"]},
        {"section": "分析结果", "metric": "敏感占比", "value": dashboard_data["warning"]["sensitive_ratio"]},
        {"section": "分析结果", "metric": "高频关键词", "value": "、".join(dashboard_data["keyword_top"][:20])},
        {"section": "分析结果", "metric": "AI评论总结", "value": dashboard_data["summary"]},
        {"section": "分析结果", "metric": "AI运营建议", "value": dashboard_data["suggestion"]},
        {"section": "分析结果", "metric": "视频语音转写", "value": dashboard_data.get("transcript") or "暂无"},
        {"section": "分析结果", "metric": "视频语音摘要", "value": dashboard_data.get("transcript_summary") or "暂无"},
        {"section": "分析结果", "metric": "视频关键片段", "value": "；".join(dashboard_data.get("transcript_key_clips") or []) or "暂无"},
        {"section": "分析结果", "metric": "画面风格摘要", "value": dashboard_data.get("visual_summary") or "暂无"},
        {"section": "分析结果", "metric": "AI视频内容分析", "value": insight_data["insight"]},
    ]

    top_comment_rows = [
        {
            "section": "高赞评论",
            "metric": f"TOP{idx + 1}",
            "value": f"{item['user_name']}｜赞 {item['digg_count']}｜回复 {item['reply_count']}｜{item['content']}",
        }
        for idx, item in enumerate(dashboard_data["top_comments"][:10])
    ]

    export_rows = summary_rows + top_comment_rows
    df = pd.DataFrame(export_rows)
    fmt = payload.format.lower()

    if fmt == "csv":
        data = df.to_csv(index=False).encode("utf-8-sig")
        return StreamingResponse(BytesIO(data), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={payload.video_id}.csv"})

    if fmt == "json":
        return JSONResponse(
            content={
                "video": dashboard_data["video"],
                "comment_total": dashboard_data["comment_total"],
                "sentiment": dashboard_data["sentiment"],
                "warning": dashboard_data["warning"],
                "keyword_top": dashboard_data["keyword_top"][:20],
                "summary": dashboard_data["summary"],
                "suggestion": dashboard_data["suggestion"],
                "transcript": dashboard_data.get("transcript") or "",
                "transcript_summary": dashboard_data.get("transcript_summary") or "",
                "transcript_key_clips": dashboard_data.get("transcript_key_clips") or [],
                "transcript_metrics": dashboard_data.get("transcript_metrics") or {},
                "visual_summary": dashboard_data.get("visual_summary") or "",
                "visual_frames": dashboard_data.get("visual_frames") or [],
                "video_insight": insight_data["insight"],
                "video_insight_provider": insight_data.get("video_insight_provider") or "",
                "top_comments": dashboard_data["top_comments"][:10],
            }
        )

    if fmt == "excel":
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="summary")
        bio.seek(0)
        return StreamingResponse(
            bio,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={payload.video_id}.xlsx"},
        )

    md = [
        f"# 视频 {payload.video_id} 分析报告",
        "",
        "## 视频信息",
        f"- 标题: {video.title}",
        f"- 作者: {video.author_name}",
        f"- 点赞: {video.digg_count}",
        f"- 评论: {video.comment_count}",
        f"- 收藏: {video.collect_count}",
        f"- 分享: {video.share_count}",
        f"- 链接: {video.video_url}",
        "",
        "## 情绪概览",
        f"- 评论总数: {dashboard_data['comment_total']}",
        f"- 正向: {dashboard_data['sentiment']['Positive']}",
        f"- 中性: {dashboard_data['sentiment']['Neutral']}",
        f"- 负向: {dashboard_data['sentiment']['Negative']}",
        f"- 舆情预警: {'是' if dashboard_data['warning']['warning'] else '否'}",
        f"- 高频关键词: {'、'.join(dashboard_data['keyword_top'][:20])}",
        "",
        "## AI 评论总结",
        dashboard_data["summary"] or "暂无",
        "",
        "## AI 运营建议",
        dashboard_data["suggestion"] or "暂无",
        "",
        "## AI 视频内容分析",
        insight_data["insight"] or "暂无",
        "",
        "## 高赞评论",
    ]
    md.extend(
        [
            f"- {item['user_name']}｜赞 {item['digg_count']}｜回复 {item['reply_count']}｜{item['content']}"
            for item in dashboard_data["top_comments"][:10]
        ]
    )
    data = "\n".join(md).encode("utf-8")
    return StreamingResponse(BytesIO(data), media_type="text/markdown", headers={"Content-Disposition": f"attachment; filename={payload.video_id}.md"})


@router.get("/")
def index_page():
    return FileResponse("web/index.html")

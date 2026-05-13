import json
import os
import time
import traceback
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Dict, List

import imageio_ffmpeg
import requests
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)

from download_mp4_to_mp3 import download_file, mp4_to_mp3, pick_video_url
from keyword_file_first_blogger_videos import (
    build_result_item,
    fetch_all_videos_by_sec_uid,
    fetch_first_blogger,
    fetch_profile_by_sec_uid,
    load_keywords,
    sanitize_filename,
)
from keyword_only_quickstart import DEFAULT_COOKIE, DEFAULT_TEMPLATE_URL, DEFAULT_VERIFY_FP


BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = (BASE_DIR / "datas" / "web_ui_runs").resolve()
RUNS_DIR.mkdir(parents=True, exist_ok=True)
MAX_LOG_LINES = 800

TASK_LOCK = Lock()
TASKS: Dict[str, Dict[str, Any]] = {}

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "douyin-spider-web-ui")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_task_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _make_task_paths(task_id: str) -> Dict[str, str]:
    task_dir = (RUNS_DIR / task_id).resolve()
    if not _is_within(RUNS_DIR, task_dir):
        raise RuntimeError("unsafe task dir")

    input_dir = (task_dir / "input").resolve()
    json_dir = (task_dir / "json").resolve()
    each_json_dir = (json_dir / "each_keyword").resolve()
    mp4_dir = (task_dir / "mp4").resolve()
    mp3_dir = (task_dir / "mp3").resolve()
    report_dir = (task_dir / "report").resolve()

    for p in [input_dir, json_dir, each_json_dir, mp4_dir, mp3_dir, report_dir]:
        p.mkdir(parents=True, exist_ok=True)

    return {
        "task_dir": str(task_dir),
        "keyword_file": str((input_dir / "keyword.txt").resolve()),
        "json_dir": str(json_dir),
        "each_json_dir": str(each_json_dir),
        "merged_json": str((json_dir / "keywords_merged.json").resolve()),
        "flat_json": str((json_dir / "videos_flat.json").resolve()),
        "report_json": str((report_dir / "mp3_convert_report.json").resolve()),
        "mp4_dir": str(mp4_dir),
        "mp3_dir": str(mp3_dir),
        "zip_file": str((task_dir / "mp3_bundle.zip").resolve()),
    }


def _add_log(task_id: str, message: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return
        task["logs"].append(line)
        task["logs"] = task["logs"][-MAX_LOG_LINES:]


def _set_progress(task_id: str, *, phase: str = "", current: int = -1, total: int = -1) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return
        progress = task["progress"]
        if phase:
            progress["phase"] = phase
        if current >= 0:
            progress["current"] = current
        if total >= 0:
            progress["total"] = total


def _set_status(task_id: str, status: str, error: str = "") -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return
        task["status"] = status
        task["error"] = error
        if status in {"success", "failed"}:
            task["finished_at"] = _now_text()


def _snapshot_task(task_id: str) -> Dict[str, Any]:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return {}
        return json.loads(json.dumps(task, ensure_ascii=False))


def _resolve_task_path(task: Dict[str, Any], key: str, *, must_exist: bool = False) -> Path:
    raw = (task.get("paths") or {}).get(key, "")
    if not raw:
        raise RuntimeError(f"missing path key={key}")

    p = Path(raw).resolve()
    task_dir = Path(task["paths"]["task_dir"]).resolve()
    if not _is_within(task_dir, p):
        raise RuntimeError(f"unsafe path key={key}")
    if must_exist and not p.exists():
        raise RuntimeError(f"path not found key={key}")
    return p


def _human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{size}B"


def _collect_mp3_files(mp3_dir: Path) -> List[Dict[str, str]]:
    if not mp3_dir.exists():
        return []
    files = []
    for p in sorted(mp3_dir.glob("*.mp3")):
        stat = p.stat()
        files.append({"name": p.name, "size_text": _human_size(stat.st_size)})
    return files


def _build_mp3_zip(mp3_dir: Path, zip_file: Path) -> None:
    zip_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(mp3_dir.glob("*.mp3")):
            zf.write(p, arcname=p.name)


def _extract_user_info_from_search_item(user_item: Dict[str, Any]) -> Dict[str, Any]:
    user_info = user_item.get("user_info") or {}
    if not user_info and isinstance(user_item.get("items"), list) and user_item["items"]:
        user_info = (user_item["items"][0] or {}).get("user_info") or {}
    return {
        "uid": user_info.get("uid"),
        "sec_uid": user_info.get("sec_uid"),
        "nickname": user_info.get("nickname"),
        "unique_id": user_info.get("unique_id"),
        "short_id": user_info.get("short_id"),
        "signature": user_info.get("signature"),
        "follower_count": user_info.get("follower_count"),
        "following_count": user_info.get("following_count"),
        "total_favorited": user_info.get("total_favorited"),
        "aweme_count": user_info.get("aweme_count"),
    }


def _fetch_first_blogger_with_fallback(keyword: str, params: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    try:
        return fetch_first_blogger(
            keyword=keyword,
            template_url=params["template_url"],
            cookie=params["cookie"],
            count=params["search_count"],
            uifid=params["uifid"],
        )
    except Exception as exc:  # noqa: BLE001
        if "No user found" not in str(exc):
            raise

        _add_log(task_id, "template_url search missed users, trying signed fallback search.")
        try:
            from builder.auth import DouyinAuth
            from dy_apis.douyin_api import DouyinAPI

            auth = DouyinAuth()
            auth.perepare_auth(params["cookie"], "", "")
            users = DouyinAPI.search_some_user(auth, keyword, max(1, int(params["search_count"])))
            if not users:
                raise RuntimeError("fallback search empty")

            blogger = _extract_user_info_from_search_item(users[0])
            if not blogger.get("sec_uid"):
                raise RuntimeError("fallback result has no sec_uid")

            _add_log(task_id, f"fallback blogger={blogger.get('nickname')} sec_uid={blogger.get('sec_uid')}")
            return blogger
        except Exception as fallback_exc:  # noqa: BLE001
            raise RuntimeError(
                "No user found for this keyword. Please refresh template_url/cookie/verify_fp and retry."
                f" fallback_error={fallback_exc}"
            ) from fallback_exc


def _extract_flat_videos_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        if isinstance(payload.get("videos"), list):
            return [item for item in payload["videos"] if isinstance(item, dict)]

        if isinstance(payload.get("item"), dict) and isinstance(payload["item"].get("videos"), list):
            return [item for item in payload["item"]["videos"] if isinstance(item, dict)]

        if isinstance(payload.get("items"), list):
            items = payload["items"]
            if items and isinstance(items[0], dict) and isinstance(items[0].get("videos"), list):
                flat_videos: List[Dict[str, Any]] = []
                for block in items:
                    keyword = block.get("keyword")
                    blogger_basic = block.get("blogger_basic") or {}
                    for video in block.get("videos") or []:
                        if not isinstance(video, dict):
                            continue
                        row = dict(video)
                        row["keyword"] = keyword
                        row["nickname"] = blogger_basic.get("nickname")
                        row["sec_uid"] = blogger_basic.get("sec_uid")
                        flat_videos.append(row)
                return flat_videos

            return [item for item in items if isinstance(item, dict)]

    raise RuntimeError("Unsupported JSON format for mp3 conversion.")


def _convert_flat_videos_to_mp3(
    task_id: str,
    flat_videos: List[Dict[str, Any]],
    mp4_dir: Path,
    mp3_dir: Path,
    report_path: Path,
    keep_mp4: bool,
    mp3_limit: int,
) -> Dict[str, int]:
    source_total = len(flat_videos)
    selected = flat_videos[:mp3_limit] if mp3_limit and mp3_limit > 0 else flat_videos
    _add_log(task_id, f"mp3_limit={mp3_limit if mp3_limit > 0 else 'all'} selected={len(selected)} source={source_total}")
    _set_progress(task_id, phase="Downloading and converting MP3", current=0, total=len(selected))

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    report: List[Dict[str, Any]] = []
    ok = 0
    skipped = 0
    failed = 0

    for idx, video_item in enumerate(selected, start=1):
        _set_progress(task_id, current=idx, total=len(selected))
        aweme_id = str(video_item.get("aweme_id") or f"unknown_{idx}")
        video_url = pick_video_url(video_item)

        if not video_url:
            failed += 1
            report.append({"aweme_id": aweme_id, "status": "failed", "reason": "missing_video_url"})
            _add_log(task_id, f"[{idx}/{len(selected)}] missing_video_url: {aweme_id}")
            continue

        # File naming rule: use aweme_id only.
        mp4_path = (mp4_dir / f"{aweme_id}.mp4").resolve()
        mp3_path = (mp3_dir / f"{aweme_id}.mp3").resolve()
        if not _is_within(mp4_dir, mp4_path) or not _is_within(mp3_dir, mp3_path):
            raise RuntimeError("unsafe mp3 path")

        if mp3_path.exists() and mp3_path.stat().st_size > 0:
            skipped += 1
            report.append({"aweme_id": aweme_id, "status": "skipped", "mp3": str(mp3_path)})
            _add_log(task_id, f"[{idx}/{len(selected)}] skipped_exists: {aweme_id}")
            continue

        if not mp4_path.exists() or mp4_path.stat().st_size == 0:
            downloaded = download_file(video_url, mp4_path)
            if not downloaded:
                failed += 1
                report.append(
                    {
                        "aweme_id": aweme_id,
                        "status": "failed",
                        "reason": "download_failed",
                        "url": video_url,
                    }
                )
                _add_log(task_id, f"[{idx}/{len(selected)}] download_failed: {aweme_id}")
                continue

        converted = mp4_to_mp3(ffmpeg_exe, mp4_path, mp3_path)
        if not converted:
            failed += 1
            report.append(
                {
                    "aweme_id": aweme_id,
                    "status": "failed",
                    "reason": "convert_failed",
                    "mp4": str(mp4_path),
                }
            )
            _add_log(task_id, f"[{idx}/{len(selected)}] convert_failed: {aweme_id}")
            continue

        if not keep_mp4 and mp4_path.exists():
            try:
                mp4_path.unlink()
            except OSError:
                pass

        ok += 1
        report.append({"aweme_id": aweme_id, "status": "ok", "mp3": str(mp3_path)})
        _add_log(task_id, f"[{idx}/{len(selected)}] mp3_ok: {aweme_id}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _add_log(task_id, f"report_saved: {report_path.name}")

    return {
        "videos_total": len(selected),
        "mp3_ok": ok,
        "mp3_skipped": skipped,
        "mp3_failed": failed,
    }


def _run_keyword_pipeline(task_id: str) -> None:
    _set_status(task_id, "running")
    _add_log(task_id, "task_started: keyword pipeline")

    task = _snapshot_task(task_id)
    if not task:
        return

    params = task["params"]

    try:
        requests.packages.urllib3.disable_warnings()

        keyword_file = _resolve_task_path(task, "keyword_file", must_exist=True)
        json_dir = _resolve_task_path(task, "json_dir", must_exist=True)
        each_json_dir = _resolve_task_path(task, "each_json_dir", must_exist=True)
        mp4_dir = _resolve_task_path(task, "mp4_dir", must_exist=True)
        mp3_dir = _resolve_task_path(task, "mp3_dir", must_exist=True)
        merged_json_path = _resolve_task_path(task, "merged_json")
        flat_json_path = _resolve_task_path(task, "flat_json")
        report_path = _resolve_task_path(task, "report_json")

        keywords = load_keywords(str(keyword_file))
        if not keywords:
            raise RuntimeError("Keyword file is empty.")

        _set_progress(task_id, phase="Fetching keyword data", current=0, total=len(keywords))
        _add_log(task_id, f"keywords_total={len(keywords)}")

        merged_items: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        for idx, keyword in enumerate(keywords, start=1):
            _set_progress(task_id, current=idx, total=len(keywords))
            _add_log(task_id, f"[{idx}/{len(keywords)}] keyword={keyword}")
            try:
                blogger_basic = _fetch_first_blogger_with_fallback(keyword, params, task_id)
                sec_uid = blogger_basic["sec_uid"]
                _add_log(task_id, f"blogger={blogger_basic.get('nickname')} sec_uid={sec_uid}")

                blogger_profile = fetch_profile_by_sec_uid(
                    sec_uid=sec_uid,
                    cookie=params["cookie"],
                    verify_fp=params["verify_fp"],
                )
                videos = fetch_all_videos_by_sec_uid(
                    sec_uid=sec_uid,
                    cookie=params["cookie"],
                    verify_fp=params["verify_fp"],
                    sleep_seconds=params["page_sleep"],
                )

                item = build_result_item(
                    keyword=keyword,
                    blogger_basic=blogger_basic,
                    blogger_profile=blogger_profile,
                    videos=videos,
                )
                merged_items.append(item)

                if params["save_each"]:
                    each_file = (each_json_dir / f"keyword_{sanitize_filename(keyword)}.json").resolve()
                    if not _is_within(each_json_dir, each_file):
                        raise RuntimeError("unsafe each json path")
                    each_payload = {
                        "meta": {
                            "keyword": keyword,
                            "generated_at": datetime.now().isoformat(),
                            "video_count": len(videos),
                        },
                        "item": item,
                    }
                    each_file.write_text(json.dumps(each_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    _add_log(task_id, f"saved_each={each_file.name}")

                _add_log(task_id, f"keyword_done={keyword} videos={len(videos)}")
            except Exception as exc:  # noqa: BLE001
                errors.append({"keyword": keyword, "error": str(exc)})
                _add_log(task_id, f"keyword_failed={keyword} error={exc}")

            if params["keyword_sleep"] > 0 and idx < len(keywords):
                time.sleep(params["keyword_sleep"])

        if not merged_items:
            preview = " | ".join([f"{e['keyword']}: {e['error']}" for e in errors[:3]])
            raise RuntimeError(
                "All keywords failed to match users. Please refresh template_url/cookie/verify_fp and retry."
                + (f" details: {preview}" if preview else "")
            )

        merged_payload = {
            "meta": {
                "generated_at": datetime.now().isoformat(),
                "keyword_file": str(keyword_file),
                "total_keywords": len(keywords),
                "success_count": len(merged_items),
                "error_count": len(errors),
            },
            "items": merged_items,
            "errors": errors,
        }

        json_dir.mkdir(parents=True, exist_ok=True)
        merged_json_path.write_text(json.dumps(merged_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _add_log(task_id, f"saved_merged={merged_json_path.name}")

        flat_videos: List[Dict[str, Any]] = []
        for item in merged_items:
            keyword = item.get("keyword")
            blogger_basic = item.get("blogger_basic") or {}
            for video in item.get("videos") or []:
                row = dict(video)
                row["keyword"] = keyword
                row["nickname"] = blogger_basic.get("nickname")
                row["sec_uid"] = blogger_basic.get("sec_uid")
                flat_videos.append(row)

        flat_json_path.write_text(json.dumps(flat_videos, ensure_ascii=False, indent=2), encoding="utf-8")
        _add_log(task_id, f"saved_flat={flat_json_path.name} total={len(flat_videos)}")

        mp3_stats = _convert_flat_videos_to_mp3(
            task_id=task_id,
            flat_videos=flat_videos,
            mp4_dir=mp4_dir,
            mp3_dir=mp3_dir,
            report_path=report_path,
            keep_mp4=params["keep_mp4"],
            mp3_limit=params.get("mp3_limit", 0),
        )

        with TASK_LOCK:
            target = TASKS.get(task_id)
            if target:
                target["stats"] = {
                    "keywords_total": len(keywords),
                    "keywords_success": len(merged_items),
                    "keywords_failed": len(errors),
                    "videos_total": mp3_stats["videos_total"],
                    "mp3_ok": mp3_stats["mp3_ok"],
                    "mp3_skipped": mp3_stats["mp3_skipped"],
                    "mp3_failed": mp3_stats["mp3_failed"],
                }

        _set_progress(task_id, phase="Done", current=1, total=1)
        _set_status(task_id, "success")
        _add_log(task_id, "task_finished")
    except Exception as exc:  # noqa: BLE001
        _set_status(task_id, "failed", str(exc))
        _set_progress(task_id, phase="failed")
        _add_log(task_id, f"task_failed: {exc}")
        _add_log(task_id, traceback.format_exc())


def _run_mp3_only_pipeline(task_id: str) -> None:
    _set_status(task_id, "running")
    _add_log(task_id, "task_started: mp3-only")

    task = _snapshot_task(task_id)
    if not task:
        return

    params = task["params"]

    try:
        flat_json_path = _resolve_task_path(task, "flat_json", must_exist=True)
        mp4_dir = _resolve_task_path(task, "mp4_dir", must_exist=True)
        mp3_dir = _resolve_task_path(task, "mp3_dir", must_exist=True)
        report_path = _resolve_task_path(task, "report_json")

        payload = json.loads(flat_json_path.read_text(encoding="utf-8"))
        flat_videos = _extract_flat_videos_from_payload(payload)
        if not flat_videos:
            raise RuntimeError("No video items found in uploaded JSON.")

        _add_log(task_id, f"video_items={len(flat_videos)}")
        mp3_stats = _convert_flat_videos_to_mp3(
            task_id=task_id,
            flat_videos=flat_videos,
            mp4_dir=mp4_dir,
            mp3_dir=mp3_dir,
            report_path=report_path,
            keep_mp4=params["keep_mp4"],
            mp3_limit=params.get("mp3_limit", 0),
        )

        with TASK_LOCK:
            target = TASKS.get(task_id)
            if target:
                target["stats"] = {
                    "keywords_total": 0,
                    "keywords_success": 0,
                    "keywords_failed": 0,
                    "videos_total": mp3_stats["videos_total"],
                    "mp3_ok": mp3_stats["mp3_ok"],
                    "mp3_skipped": mp3_stats["mp3_skipped"],
                    "mp3_failed": mp3_stats["mp3_failed"],
                }

        _set_progress(task_id, phase="Done", current=1, total=1)
        _set_status(task_id, "success")
        _add_log(task_id, "task_finished")
    except Exception as exc:  # noqa: BLE001
        _set_status(task_id, "failed", str(exc))
        _set_progress(task_id, phase="failed")
        _add_log(task_id, f"task_failed: {exc}")
        _add_log(task_id, traceback.format_exc())


def _register_task(task_id: str, params: Dict[str, Any], paths: Dict[str, str]) -> None:
    with TASK_LOCK:
        TASKS[task_id] = {
            "id": task_id,
            "created_at": _now_text(),
            "finished_at": "",
            "status": "queued",
            "error": "",
            "logs": [],
            "progress": {"phase": "queued", "current": 0, "total": 0},
            "stats": {},
            "params": params,
            "paths": paths,
        }


@app.route("/", methods=["GET"])
def index() -> str:
    with TASK_LOCK:
        tasks = sorted(TASKS.values(), key=lambda x: x["created_at"], reverse=True)

    defaults = {
        "template_url": os.getenv("DOUYIN_SEARCH_URL_TEMPLATE", "").strip(),
        "cookie": os.getenv("DY_COOKIES", "").strip(),
        "verify_fp": os.getenv("DY_VERIFY_FP", "").strip(),
        "uifid": "",
        "search_count": 12,
        "page_sleep": 0.2,
        "keyword_sleep": 0.6,
        "mp3_limit": 0,
    }
    return render_template("index.html", tasks=tasks, defaults=defaults)


@app.route("/start", methods=["POST"])
def start_task() -> Any:
    uploaded = request.files.get("keyword_file")
    if not uploaded or not uploaded.filename:
        flash("请先上传关键词 txt 文件。", "error")
        return redirect(url_for("index"))

    template_url = (
        request.form.get("template_url", "").strip()
        or os.getenv("DOUYIN_SEARCH_URL_TEMPLATE", "").strip()
        or DEFAULT_TEMPLATE_URL
    )
    cookie = (
        request.form.get("cookie", "").strip()
        or os.getenv("DY_COOKIES", "").strip()
        or DEFAULT_COOKIE
    )
    verify_fp = (
        request.form.get("verify_fp", "").strip()
        or os.getenv("DY_VERIFY_FP", "").strip()
        or DEFAULT_VERIFY_FP
    )

    task_id = _new_task_id()
    paths = _make_task_paths(task_id)

    keyword_file = Path(paths["keyword_file"]).resolve()
    uploaded.save(str(keyword_file))

    params = {
        "mode": "keyword_pipeline",
        "template_url": template_url,
        "cookie": cookie,
        "verify_fp": verify_fp,
        "uifid": request.form.get("uifid", "").strip(),
        "search_count": _safe_int(request.form.get("search_count"), 12),
        "page_sleep": _safe_float(request.form.get("page_sleep"), 0.2),
        "keyword_sleep": _safe_float(request.form.get("keyword_sleep"), 0.6),
        "mp3_limit": max(0, _safe_int(request.form.get("mp3_limit"), 0)),
        "save_each": request.form.get("save_each") == "on",
        "keep_mp4": request.form.get("keep_mp4") == "on",
    }

    _register_task(task_id, params, paths)
    Thread(target=_run_keyword_pipeline, args=(task_id,), daemon=True).start()
    return redirect(url_for("task_detail", task_id=task_id))


@app.route("/start-mp3-only", methods=["POST"])
def start_mp3_only_task() -> Any:
    uploaded = request.files.get("videos_json_file")
    if not uploaded or not uploaded.filename:
        flash("请先上传视频 JSON 文件。", "error")
        return redirect(url_for("index"))

    task_id = _new_task_id()
    paths = _make_task_paths(task_id)

    flat_json_path = (Path(paths["json_dir"]) / "videos_input.json").resolve()
    if not _is_within(Path(paths["task_dir"]), flat_json_path):
        abort(400, "Invalid path")
    uploaded.save(str(flat_json_path))
    paths["flat_json"] = str(flat_json_path)

    params = {
        "mode": "mp3_only",
        "mp3_limit": max(0, _safe_int(request.form.get("mp3_limit"), 0)),
        "keep_mp4": request.form.get("keep_mp4") == "on",
    }

    _register_task(task_id, params, paths)
    Thread(target=_run_mp3_only_pipeline, args=(task_id,), daemon=True).start()
    return redirect(url_for("task_detail", task_id=task_id))


def _find_task_or_404(task_id: str) -> Dict[str, Any]:
    task = _snapshot_task(task_id)
    if not task:
        abort(404, "Task not found")
    return task


@app.route("/task/<task_id>", methods=["GET"])
def task_detail(task_id: str) -> str:
    task = _find_task_or_404(task_id)

    try:
        mp3_dir = _resolve_task_path(task, "mp3_dir", must_exist=True)
    except RuntimeError:
        abort(400, "Invalid task path")

    mp3_files = _collect_mp3_files(mp3_dir)

    artifacts: Dict[str, Dict[str, str]] = {}
    for key in ["merged_json", "flat_json", "report_json"]:
        try:
            p = _resolve_task_path(task, key)
        except RuntimeError:
            continue
        if p.exists():
            artifacts[key] = {"name": p.name, "size_text": _human_size(p.stat().st_size)}

    auto_refresh = task["status"] in {"queued", "running"}
    return render_template(
        "task.html",
        task=task,
        mp3_files=mp3_files,
        artifacts=artifacts,
        auto_refresh=auto_refresh,
    )


@app.route("/download/<task_id>/<artifact>", methods=["GET"])
def download_artifact(task_id: str, artifact: str) -> Any:
    task = _find_task_or_404(task_id)

    mapping = {
        "merged_json": "merged_json",
        "flat_json": "flat_json",
        "report_json": "report_json",
    }
    if artifact not in mapping:
        abort(404, "Artifact not found")

    try:
        file_path = _resolve_task_path(task, mapping[artifact], must_exist=True)
    except RuntimeError:
        abort(404, "File not found")

    return send_file(file_path, as_attachment=True)


@app.route("/download/<task_id>/mp3/<path:filename>", methods=["GET"])
def download_mp3(task_id: str, filename: str) -> Any:
    task = _find_task_or_404(task_id)

    try:
        mp3_dir = _resolve_task_path(task, "mp3_dir", must_exist=True)
    except RuntimeError:
        abort(404, "MP3 dir not found")

    target = (mp3_dir / filename).resolve()
    if not _is_within(mp3_dir, target) or not target.exists() or not target.is_file():
        abort(404, "MP3 not found")

    return send_from_directory(mp3_dir, target.name, as_attachment=True)


@app.route("/download/<task_id>/mp3-zip", methods=["GET"])
def download_mp3_zip(task_id: str) -> Any:
    task = _find_task_or_404(task_id)

    try:
        mp3_dir = _resolve_task_path(task, "mp3_dir", must_exist=True)
        zip_file = _resolve_task_path(task, "zip_file")
    except RuntimeError:
        abort(404, "Task path invalid")

    mp3_files = list(mp3_dir.glob("*.mp3"))
    if not mp3_files:
        abort(404, "No mp3 files yet")

    need_rebuild = not zip_file.exists()
    if not need_rebuild:
        newest_mp3_time = max(p.stat().st_mtime for p in mp3_files)
        if newest_mp3_time > zip_file.stat().st_mtime:
            need_rebuild = True

    if need_rebuild:
        _build_mp3_zip(mp3_dir, zip_file)

    return send_file(zip_file, as_attachment=True, download_name=f"{task_id}_mp3.zip")


if __name__ == "__main__":
    port = _safe_int(os.getenv("WEB_UI_PORT"), 5050)
    app.run(host="0.0.0.0", port=port, debug=False)

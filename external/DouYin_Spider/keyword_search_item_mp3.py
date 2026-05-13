import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import imageio_ffmpeg
import requests
from dotenv import load_dotenv

from builder.header import HeaderBuilder, HeaderType
from builder.params import Params
from download_mp4_to_mp3 import download_file, mp4_to_mp3
from utils.dy_util import generate_msToken, trans_cookies


SEARCH_API = "https://www.douyin.com/aweme/v1/web/search/item/"


def sanitize_filename(name: str) -> str:
    if not name:
        return "keyword"
    chars: List[str] = []
    for ch in name.strip():
        if ch in '<>:"/\\|?*':
            chars.append("_")
        else:
            chars.append(ch)
    out = "".join(chars).strip()
    return out or "keyword"


def load_keywords(file_path: Path) -> List[str]:
    if not file_path.exists():
        raise FileNotFoundError(f"Keyword file not found: {file_path}")
    lines = file_path.read_text(encoding="utf-8").splitlines()
    rows: List[str] = []
    for line in lines:
        item = line.strip().lstrip("\ufeff")
        if not item or item.startswith("#"):
            continue
        rows.append(item)
    seen = set()
    uniq: List[str] = []
    for kw in rows:
        if kw in seen:
            continue
        seen.add(kw)
        uniq.append(kw)
    return uniq


def read_cookie_from_file(file_path: Path) -> str:
    if not file_path.exists():
        raise FileNotFoundError(f"Cookie file not found: {file_path}")
    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Cookie file is empty: {file_path}")
    return text


def first_non_empty(values: Iterable[Optional[str]]) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def first_url(node: Any) -> Optional[str]:
    if isinstance(node, dict):
        urls = node.get("url_list")
        if isinstance(urls, list):
            for url in urls:
                if isinstance(url, str) and url:
                    return url
        url = node.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def extract_video_url(aweme: Dict[str, Any]) -> Optional[str]:
    video = aweme.get("video") or {}
    bit_rate = video.get("bit_rate") or []
    bit_rate_urls = []
    for row in bit_rate:
        if not isinstance(row, dict):
            continue
        bit_rate_urls.append(first_url(row.get("play_addr")))
        bit_rate_urls.append(first_url(row.get("play_addr_265")))

    return first_non_empty(
        [
            first_url(video.get("download_addr")),
            first_url(video.get("play_addr")),
            first_url(video.get("play_addr_h264")),
            first_url(video.get("play_addr_265")),
            *bit_rate_urls,
        ]
    )


def looks_like_aweme(node: Dict[str, Any]) -> bool:
    if not isinstance(node, dict):
        return False
    aweme_id = node.get("aweme_id")
    if aweme_id in (None, ""):
        return False
    if isinstance(node.get("video"), dict):
        return True
    if isinstance(node.get("statistics"), dict):
        return True
    return bool(node.get("desc") is not None and node.get("create_time") is not None)


def collect_awemes(payload: Any) -> List[Dict[str, Any]]:
    stack = [payload]
    out: List[Dict[str, Any]] = []
    seen_ids = set()

    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if looks_like_aweme(cur):
                aweme_id = str(cur.get("aweme_id"))
                if aweme_id not in seen_ids:
                    seen_ids.add(aweme_id)
                    out.append(cur)
            for v in cur.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for item in cur:
                if isinstance(item, (dict, list)):
                    stack.append(item)

    return out


def build_headers(keyword: str, cookie_str: str, uifid: str = "") -> Dict[str, str]:
    referer = f"https://www.douyin.com/search/{quote(keyword)}?type=general"
    headers = HeaderBuilder.build(HeaderType.GET)
    headers.set_referer(referer)
    headers.set_header("cookie", cookie_str)
    # Avoid brotli decode issues in some runtime environments.
    headers.set_header("accept-encoding", "gzip, deflate")
    if uifid:
        headers.set_header("uifid", uifid)
    return headers.get()


def build_search_params(
    auth: "SimpleAuth",
    keyword: str,
    offset: int,
    count: int,
    verify_fp: str,
    search_channel: str,
    search_source: str,
) -> Dict[str, Any]:
    referer = f"https://www.douyin.com/search/{quote(keyword)}?type=general"
    params = Params().with_platform()
    params.add_param("search_channel", search_channel)
    params.add_param("keyword", keyword)
    params.add_param("search_source", search_source)
    params.add_param("query_correct_type", "1")
    params.add_param("is_filter_search", "0")
    params.add_param("from_group_id", "")
    params.add_param("offset", str(offset))
    params.add_param("count", str(count))
    params.add_param("need_filter_settings", "1" if offset == 0 else "0")
    params.add_param("list_type", "single")
    params.with_web_id(auth, referer)
    params.add_param("verifyFp", verify_fp)
    params.add_param("fp", verify_fp)
    params.add_param("msToken", auth.msToken)
    params.with_a_bogus()
    return params.get()


def request_page(
    auth: "SimpleAuth",
    keyword: str,
    offset: int,
    count: int,
    verify_fp: str,
    search_channel: str,
    search_source: str,
    timeout: int,
    uifid: str = "",
) -> Dict[str, Any]:
    params = build_search_params(
        auth=auth,
        keyword=keyword,
        offset=offset,
        count=count,
        verify_fp=verify_fp,
        search_channel=search_channel,
        search_source=search_source,
    )
    headers = build_headers(keyword=keyword, cookie_str=auth.cookie_str, uifid=uifid)
    resp = requests.get(
        SEARCH_API,
        headers=headers,
        params=params,
        cookies=auth.cookie,
        timeout=timeout,
        verify=False,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    if not resp.content:
        if resp.headers.get("X-Vc-Bdturing-Parameters"):
            raise RuntimeError(
                "verify_required_bdturing (slide challenge, refresh cookie after manual verify)"
            )
        abort_info = resp.headers.get("X-Whale-Throughput-Abort-Data", "")
        raise RuntimeError(f"empty response abort={abort_info}")
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"json decode failed: {exc}") from exc
    if data.get("status_code") != 0:
        raise RuntimeError(
            f"status_code={data.get('status_code')} status_msg={data.get('status_msg')}"
        )
    return data


def build_song_info(aweme: Dict[str, Any], keyword: str) -> Tuple[Dict[str, Any], Optional[str]]:
    video = aweme.get("video") or {}
    play_addr = video.get("play_addr") or {}
    stats = aweme.get("statistics") or {}
    video_url = extract_video_url(aweme)

    info = {
        "keyword": keyword,
        "aweme_id": str(aweme.get("aweme_id") or ""),
        "desc": aweme.get("desc"),
        "create_time": aweme.get("create_time"),
        "duration_ms": video.get("duration"),
        "ratio": video.get("ratio"),
        "play_uri": play_addr.get("uri"),
        "digg_count": stats.get("digg_count"),
        "comment_count": stats.get("comment_count"),
        "collect_count": stats.get("collect_count"),
        "share_count": stats.get("share_count"),
        "play_count": stats.get("play_count"),
    }
    return info, video_url


def parse_duration_ms(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class TrackTask:
    keyword: str
    keyword_dir_name: str
    aweme_id: str
    info: Dict[str, Any]
    video_url: str


@dataclass
class TrackResult:
    keyword: str
    aweme_id: str
    status: str
    reason: str = ""


class SimpleAuth:
    def __init__(self, cookie_str: str) -> None:
        self.cookie = trans_cookies(cookie_str)
        self.msToken = self.cookie.get("msToken") or generate_msToken()
        self.cookie["msToken"] = self.msToken
        self.cookie_str = "; ".join([f"{k}={v}" for k, v in self.cookie.items()])


class SearchItemMp3Crawler:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.base_dir = Path(__file__).resolve().parent
        self.output_dir = self.resolve_path(args.output_dir)
        self.keyword_file = self.resolve_path(args.keyword_file)
        self.log_lock = threading.Lock()
        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        self.uifid = ""
        self.min_duration_ms = int(float(args.min_duration_minutes) * 60 * 1000)
        self.max_duration_ms = int(float(args.max_duration_minutes) * 60 * 1000)

    def resolve_path(self, path_value: str) -> Path:
        p = Path(path_value)
        if p.is_absolute():
            return p
        return (self.base_dir / p).resolve()

    def log(self, message: str) -> None:
        with self.log_lock:
            try:
                print(message, flush=True)
            except UnicodeEncodeError:
                safe = message.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
                print(safe, flush=True)

    def build_auth(self) -> Tuple[SimpleAuth, str]:
        cookie = self.args.cookie.strip()
        if not cookie and self.args.cookie_file.strip():
            cookie_path = self.resolve_path(self.args.cookie_file.strip())
            cookie = read_cookie_from_file(cookie_path)
        if not cookie:
            cookie = os.getenv("DY_COOKIES", "").strip()
        if not cookie:
            raise RuntimeError(
                "Missing cookie. Use --cookie / --cookie-file or set DY_COOKIES in env/.env."
            )
        auth = SimpleAuth(cookie)
        verify_fp = self.args.verify_fp.strip() or auth.cookie.get("s_v_web_id", "")
        if not verify_fp:
            raise RuntimeError("Missing verifyFp. Use --verify-fp or provide s_v_web_id in cookie.")
        self.uifid = self.args.uifid.strip() or auth.cookie.get("UIFID", "")
        return auth, verify_fp

    def fetch_keyword_tracks(
        self,
        auth: SimpleAuth,
        verify_fp: str,
        keyword: str,
        on_task: Optional[Callable[[TrackTask], None]] = None,
    ) -> Tuple[str, List[TrackTask], int, Optional[str]]:
        tasks: List[TrackTask] = []
        seen_ids = set()
        offset = self.args.offset
        filtered_duration_count = 0

        try:
            for page_idx in range(1, self.args.max_pages + 1):
                data = None
                last_err: Optional[str] = None
                for attempt in range(1, self.args.request_retries + 1):
                    if self.args.request_interval > 0 and attempt == 1:
                        time.sleep(self.args.request_interval)
                    try:
                        fetched = request_page(
                            auth=auth,
                            keyword=keyword,
                            offset=offset,
                            count=self.args.count,
                            verify_fp=verify_fp,
                            search_channel=self.args.search_channel,
                            search_source=self.args.search_source,
                            timeout=self.args.request_timeout,
                            uifid=self.uifid,
                        )
                        nil_type_tmp = (
                            (fetched.get("search_nil_info") or {}).get("search_nil_type") or ""
                        ).strip()
                        # verify_check can be temporary under anti-bot pressure; retry instead of
                        # failing immediately.
                        if page_idx == 1 and nil_type_tmp == "verify_check":
                            if attempt < self.args.request_retries:
                                sleep_s = (
                                    self.args.request_retry_base_sleep * attempt
                                    + random.uniform(0.5, 1.1)
                                )
                                self.log(
                                    f"[fetch-retry-verify] keyword={keyword} page={page_idx} "
                                    f"attempt={attempt}/{self.args.request_retries} sleep={sleep_s:.2f}s"
                                )
                                time.sleep(sleep_s)
                                continue
                        data = fetched
                        break
                    except Exception as exc:
                        last_err = str(exc)
                        if attempt >= self.args.request_retries:
                            raise
                        if "verify_required_bdturing" in last_err:
                            sleep_s = max(
                                15.0,
                                self.args.request_retry_base_sleep * attempt * 4.0,
                            ) + random.uniform(1.0, 2.5)
                            self.log(
                                f"[fetch-retry-verify-challenge] keyword={keyword} page={page_idx} "
                                f"attempt={attempt}/{self.args.request_retries} sleep={sleep_s:.2f}s"
                            )
                            time.sleep(sleep_s)
                            continue
                        if "status_code=2484" in last_err:
                            sleep_s = max(
                                8.0,
                                self.args.request_retry_base_sleep * attempt * 5.0,
                            ) + random.uniform(0.8, 2.0)
                            self.log(
                                f"[fetch-retry-rate-limit] keyword={keyword} page={page_idx} "
                                f"attempt={attempt}/{self.args.request_retries} sleep={sleep_s:.2f}s"
                            )
                            time.sleep(sleep_s)
                            continue
                        if "HTTP 444" in last_err:
                            sleep_s = (
                                self.args.request_retry_base_sleep * attempt
                                + random.uniform(0.2, 0.9)
                            )
                            self.log(
                                f"[fetch-retry] keyword={keyword} page={page_idx} "
                                f"attempt={attempt}/{self.args.request_retries} sleep={sleep_s:.2f}s error={last_err}"
                            )
                            time.sleep(sleep_s)
                        else:
                            sleep_s = 0.5 + random.uniform(0.1, 0.6)
                            time.sleep(sleep_s)

                if data is None:
                    raise RuntimeError(last_err or "request failed")

                nil_type = ((data.get("search_nil_info") or {}).get("search_nil_type") or "").strip()
                awemes = collect_awemes(data)
                page_added = 0
                page_filtered_duration = 0
                for aweme in awemes:
                    aweme_id = str(aweme.get("aweme_id") or "")
                    if not aweme_id or aweme_id in seen_ids:
                        continue
                    info, video_url = build_song_info(aweme, keyword)
                    duration_ms = parse_duration_ms(info.get("duration_ms"))
                    if duration_ms is None:
                        page_filtered_duration += 1
                        filtered_duration_count += 1
                        continue
                    if duration_ms < self.min_duration_ms or duration_ms > self.max_duration_ms:
                        page_filtered_duration += 1
                        filtered_duration_count += 1
                        continue
                    if not video_url:
                        continue
                    seen_ids.add(aweme_id)
                    tasks.append(
                        TrackTask(
                            keyword=keyword,
                            keyword_dir_name=sanitize_filename(keyword),
                            aweme_id=aweme_id,
                            info=info,
                            video_url=video_url,
                        )
                    )
                    if on_task is not None:
                        on_task(tasks[-1])
                    page_added += 1

                self.log(
                    f"[fetch] keyword={keyword} page={page_idx} offset={offset} "
                    f"aweme_hits={len(awemes)} duration_filtered={page_filtered_duration} "
                    f"usable={page_added} total={len(tasks)}"
                )

                if page_idx == 1 and not tasks and nil_type == "verify_check":
                    raise RuntimeError(
                        "search_nil_type=verify_check (need refreshed cookie / manual verify on douyin web)"
                    )

                has_more = int(data.get("has_more") or 0)
                if has_more != 1:
                    break

                next_offset_raw = data.get("cursor")
                if next_offset_raw is None:
                    next_offset_raw = data.get("offset")

                try:
                    next_offset = int(next_offset_raw) if next_offset_raw is not None else offset + self.args.count
                except Exception:
                    next_offset = offset + self.args.count

                if next_offset <= offset:
                    next_offset = offset + self.args.count
                offset = next_offset

                if self.args.page_sleep > 0:
                    time.sleep(self.args.page_sleep)

            return keyword, tasks, filtered_duration_count, None
        except Exception as exc:
            return keyword, tasks, filtered_duration_count, str(exc)

    def process_track(self, task: TrackTask) -> TrackResult:
        keyword_dir = self.output_dir / task.keyword_dir_name
        track_dir = keyword_dir / task.aweme_id
        track_dir.mkdir(parents=True, exist_ok=True)

        mp3_path = track_dir / f"{task.aweme_id}.mp3"
        info_path = track_dir / "info.json"
        tmp_mp4_path = track_dir / f"{task.aweme_id}.tmp.mp4"

        try:
            if mp3_path.exists() and mp3_path.stat().st_size > 0:
                info_path.write_text(json.dumps(task.info, ensure_ascii=False, indent=2), encoding="utf-8")
                return TrackResult(keyword=task.keyword, aweme_id=task.aweme_id, status="skipped")

            ok_download = download_file(
                url=task.video_url,
                target=tmp_mp4_path,
                timeout=self.args.download_timeout,
                retries=self.args.download_retries,
            )
            if not ok_download:
                return TrackResult(
                    keyword=task.keyword,
                    aweme_id=task.aweme_id,
                    status="failed",
                    reason="download_failed",
                )

            ok_convert = mp4_to_mp3(self.ffmpeg_exe, tmp_mp4_path, mp3_path)
            if not ok_convert:
                return TrackResult(
                    keyword=task.keyword,
                    aweme_id=task.aweme_id,
                    status="failed",
                    reason="convert_failed",
                )

            info_path.write_text(json.dumps(task.info, ensure_ascii=False, indent=2), encoding="utf-8")
            return TrackResult(keyword=task.keyword, aweme_id=task.aweme_id, status="ok")
        except Exception as exc:
            return TrackResult(
                keyword=task.keyword,
                aweme_id=task.aweme_id,
                status="failed",
                reason=str(exc),
            )
        finally:
            if tmp_mp4_path.exists():
                try:
                    tmp_mp4_path.unlink()
                except OSError:
                    pass

    def run(self) -> None:
        requests.packages.urllib3.disable_warnings()
        auth, verify_fp = self.build_auth()
        keywords = load_keywords(self.keyword_file)
        if not keywords:
            raise RuntimeError(f"No keywords found in {self.keyword_file}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"keyword_file={self.keyword_file}")
        self.log(f"output_dir={self.output_dir}")
        self.log(
            f"keywords={len(keywords)} keyword_workers={self.args.keyword_workers} "
            f"convert_workers={self.args.convert_workers} "
            f"duration_limit=[{self.args.min_duration_minutes},{self.args.max_duration_minutes}]min "
            f"request_interval={self.args.request_interval}s"
        )

        all_track_tasks: List[TrackTask] = []
        keyword_errors: List[Dict[str, Any]] = []
        keyword_stats: Dict[str, int] = {}
        keyword_duration_filtered: Dict[str, int] = {}
        total_duration_filtered = 0
        stopped_early_due_verify = False

        mp3_ok = 0
        mp3_skipped = 0
        mp3_failed = 0
        track_errors: List[Dict[str, str]] = []
        convert_future_map: Dict[Any, TrackTask] = {}
        convert_future_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=self.args.convert_workers) as convert_executor:
            def enqueue_convert_task(task: TrackTask) -> None:
                conv_future = convert_executor.submit(self.process_track, task)
                with convert_future_lock:
                    convert_future_map[conv_future] = task

            with ThreadPoolExecutor(max_workers=self.args.keyword_workers) as executor:
                future_map = {
                    executor.submit(
                        self.fetch_keyword_tracks, auth, verify_fp, keyword, enqueue_convert_task
                    ): keyword
                    for keyword in keywords
                }
                for future in as_completed(future_map):
                    keyword = future_map[future]
                    done_keyword, tasks, filtered_count, err = future.result()
                    all_track_tasks.extend(tasks)
                    keyword_stats[done_keyword] = len(tasks)
                    keyword_duration_filtered[done_keyword] = filtered_count
                    total_duration_filtered += filtered_count
                    if err:
                        keyword_errors.append({"keyword": keyword, "error": err})
                        self.log(f"[fetch-failed] keyword={keyword} error={err}")
                        if "verify_required_bdturing" in err:
                            stopped_early_due_verify = True
                            self.log(
                                "[stop] verify challenge detected, cancel remaining keywords. "
                                "refresh cookie after manual web verify and rerun."
                            )
                            for pending in future_map:
                                if pending is future:
                                    continue
                                pending.cancel()
                            break
                    else:
                        self.log(
                            f"[fetch-done] keyword={keyword} tracks={len(tasks)} "
                            f"duration_filtered={filtered_count}"
                        )

            self.log(
                f"fetch_total_tracks={len(all_track_tasks)} total_duration_filtered={total_duration_filtered}"
            )
            if not all_track_tasks:
                summary = {
                    "meta": {
                        "generated_at": datetime.now().isoformat(),
                        "keyword_file": str(self.keyword_file),
                        "output_dir": str(self.output_dir),
                        "duration_filter_minutes": {
                            "min": self.args.min_duration_minutes,
                            "max": self.args.max_duration_minutes,
                        },
                        "stopped_early_due_verify": stopped_early_due_verify,
                    },
                    "stats": {
                        "keywords_total": len(keywords),
                        "keywords_with_tracks": 0,
                        "tracks_total": 0,
                        "duration_filtered_total": total_duration_filtered,
                        "mp3_ok": 0,
                        "mp3_skipped": 0,
                        "mp3_failed": 0,
                    },
                    "keyword_track_count": keyword_stats,
                    "keyword_duration_filtered_count": keyword_duration_filtered,
                    "keyword_errors": keyword_errors,
                }
                summary_path = self.output_dir / "summary.json"
                summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                self.log(f"summary_saved={summary_path}")
                return

            done = 0
            total = len(convert_future_map)
            for future in as_completed(convert_future_map):
                done += 1
                result = future.result()
                if result.status == "ok":
                    mp3_ok += 1
                elif result.status == "skipped":
                    mp3_skipped += 1
                else:
                    mp3_failed += 1
                    track_errors.append(
                        {
                            "keyword": result.keyword,
                            "aweme_id": result.aweme_id,
                            "reason": result.reason,
                        }
                    )
                self.log(
                    f"[convert] {done}/{total} keyword={result.keyword} "
                    f"aweme_id={result.aweme_id} status={result.status}"
                )

        summary = {
            "meta": {
                "generated_at": datetime.now().isoformat(),
                "keyword_file": str(self.keyword_file),
                "output_dir": str(self.output_dir),
                "search_api": SEARCH_API,
                "search_channel": self.args.search_channel,
                "search_source": self.args.search_source,
                "count": self.args.count,
                "max_pages": self.args.max_pages,
                "keyword_workers": self.args.keyword_workers,
                "convert_workers": self.args.convert_workers,
                "duration_filter_minutes": {
                    "min": self.args.min_duration_minutes,
                    "max": self.args.max_duration_minutes,
                },
                "stopped_early_due_verify": stopped_early_due_verify,
            },
            "stats": {
                "keywords_total": len(keywords),
                "keywords_with_tracks": sum(1 for x in keyword_stats.values() if x > 0),
                "tracks_total": len(all_track_tasks),
                "duration_filtered_total": total_duration_filtered,
                "mp3_ok": mp3_ok,
                "mp3_skipped": mp3_skipped,
                "mp3_failed": mp3_failed,
            },
            "keyword_track_count": keyword_stats,
            "keyword_duration_filtered_count": keyword_duration_filtered,
            "keyword_errors": keyword_errors,
            "track_errors": track_errors,
        }
        summary_path = self.output_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"summary_saved={summary_path}")
        self.log(
            f"done keywords={len(keywords)} tracks={len(all_track_tasks)} "
            f"ok={mp3_ok} skipped={mp3_skipped} failed={mp3_failed}"
        )


def build_parser() -> argparse.ArgumentParser:
    default_keyword_file = "datas/key/suno_keyword_music.txt"
    default_output_dir = "dy_suno_mp3"

    parser = argparse.ArgumentParser(
        description=(
            "Read keyword list -> call /aweme/v1/web/search/item/ -> download mp4 -> convert mp3 "
            "and store as dy_suno_mp3/<keyword>/<aweme_id>/<aweme_id>.mp3 + info.json."
        )
    )
    parser.add_argument("--keyword-file", default=default_keyword_file, help="Keyword file path.")
    parser.add_argument("--output-dir", default=default_output_dir, help="Root output dir.")
    parser.add_argument("--cookie", default="", help="Douyin cookie string. Default from DY_COOKIES.")
    parser.add_argument("--cookie-file", default="", help="Read cookie string from file.")
    parser.add_argument("--uifid", default="", help="Optional uifid header. Default from cookie UIFID.")
    parser.add_argument(
        "--verify-fp",
        default="",
        help="verifyFp/fp value. Default from --cookie s_v_web_id.",
    )
    parser.add_argument("--search-channel", default="aweme_general", help="Search channel.")
    parser.add_argument("--search-source", default="normal_search", help="Search source.")
    parser.add_argument("--offset", type=int, default=0, help="Initial offset.")
    parser.add_argument("--count", type=int, default=12, help="Page size.")
    parser.add_argument("--max-pages", type=int, default=3, help="Max pages per keyword.")
    parser.add_argument("--keyword-workers", type=int, default=3, help="Concurrent keyword workers.")
    parser.add_argument("--convert-workers", type=int, default=4, help="Concurrent mp3 workers.")
    parser.add_argument(
        "--min-duration-minutes",
        type=float,
        default=2.0,
        help="Keep videos with duration >= this value (minutes).",
    )
    parser.add_argument(
        "--max-duration-minutes",
        type=float,
        default=7.0,
        help="Keep videos with duration <= this value (minutes).",
    )
    parser.add_argument("--page-sleep", type=float, default=0.25, help="Sleep seconds between pages.")
    parser.add_argument("--request-timeout", type=int, default=25, help="Search request timeout seconds.")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.0,
        help="Fixed sleep seconds before each page request.",
    )
    parser.add_argument("--request-retries", type=int, default=4, help="Retries for search requests.")
    parser.add_argument(
        "--request-retry-base-sleep",
        type=float,
        default=1.2,
        help="Base sleep seconds for retry backoff.",
    )
    parser.add_argument("--download-timeout", type=int, default=30, help="Download timeout seconds.")
    parser.add_argument("--download-retries", type=int, default=3, help="Download retries.")
    return parser


def main() -> None:
    load_dotenv()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args()
    if args.keyword_workers < 1:
        parser.error("--keyword-workers must be >= 1")
    if args.convert_workers < 1:
        parser.error("--convert-workers must be >= 1")
    if args.count < 1:
        parser.error("--count must be >= 1")
    if args.max_pages < 1:
        parser.error("--max-pages must be >= 1")
    if args.request_interval < 0:
        parser.error("--request-interval must be >= 0")
    if args.request_retries < 1:
        parser.error("--request-retries must be >= 1")
    if args.request_retry_base_sleep < 0:
        parser.error("--request-retry-base-sleep must be >= 0")
    if args.min_duration_minutes <= 0:
        parser.error("--min-duration-minutes must be > 0")
    if args.max_duration_minutes <= 0:
        parser.error("--max-duration-minutes must be > 0")
    if args.max_duration_minutes < args.min_duration_minutes:
        parser.error("--max-duration-minutes must be >= --min-duration-minutes")
    crawler = SearchItemMp3Crawler(args)
    crawler.run()


if __name__ == "__main__":
    main()

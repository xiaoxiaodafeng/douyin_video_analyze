import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, quote

import requests


def update_query_params(url: str, updates: Dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(updates)
    new_query = urlencode(query, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


def sanitize_filename(name: str) -> str:
    if not name:
        return "keyword"
    chars = []
    for ch in name.strip():
        if ch in '<>:"/\\|?*':
            chars.append("_")
        else:
            chars.append(ch)
    result = "".join(chars).strip()
    return result or "keyword"


def build_headers(referer: str, cookie: str, uifid: str = "") -> Dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8,zh-TW;q=0.7",
        "Connection": "keep-alive",
        "Referer": referer,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Cookie": cookie,
    }
    if uifid:
        headers["uifid"] = uifid
    return headers


def extract_user_info(user_item: Dict[str, Any]) -> Dict[str, Any]:
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


def request_json(url: str, headers: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP error: {resp.status_code}")
    if not resp.content:
        abort_info = resp.headers.get("X-Whale-Throughput-Abort-Data", "")
        raise RuntimeError(f"Empty response. abort={abort_info}")
    try:
        return resp.json()
    except Exception as e:
        raise RuntimeError(f"JSON decode failed: {e}") from e


def fetch_first_blogger(
    keyword: str,
    template_url: str,
    cookie: str,
    count: int,
    uifid: str,
) -> Dict[str, Any]:
    referer = f"https://www.douyin.com/search/{quote(keyword)}?type=user"
    headers = build_headers(referer=referer, cookie=cookie, uifid=uifid)
    page_url = update_query_params(
        template_url, {"keyword": keyword, "offset": "0", "count": str(count)}
    )
    data = request_json(page_url, headers)
    if data.get("status_code") != 0:
        raise RuntimeError(
            f"Search API failed: status_code={data.get('status_code')} "
            f"status_msg={data.get('status_msg')}"
        )
    user_list = data.get("user_list") or []
    if not user_list:
        raise RuntimeError("No user found for this keyword.")
    first_user = extract_user_info(user_list[0])
    if not first_user.get("sec_uid"):
        raise RuntimeError("First user has no sec_uid.")
    return first_user


def fetch_all_videos_by_sec_uid(
    sec_uid: str,
    cookie: str,
    verify_fp: str,
    sleep_seconds: float = 0.2,
) -> List[Dict[str, Any]]:
    referer = f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main"
    headers = build_headers(referer=referer, cookie=cookie)
    params_base = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "sec_user_id": sec_uid,
        "count": "18",
        "locate_query": "false",
        "show_live_replay_strategy": "1",
        "publish_video_strategy_type": "2",
        "update_version_code": "170400",
        "pc_client_type": "1",
        "version_code": "290100",
        "version_name": "29.1.0",
        "cookie_enabled": "true",
        "screen_width": "1920",
        "screen_height": "1080",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "146.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "146.0.0.0",
        "os_name": "Windows",
        "os_version": "10",
        "cpu_core_num": "12",
        "device_memory": "8",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "150",
        "verifyFp": verify_fp,
        "fp": verify_fp,
    }

    max_cursor = "0"
    all_videos: List[Dict[str, Any]] = []
    page = 0

    while True:
        page += 1
        params = dict(params_base)
        params["max_cursor"] = max_cursor
        params["need_time_list"] = "1" if max_cursor == "0" else "0"
        params["time_list_query"] = "0"

        api_url = "https://www.douyin.com/aweme/v1/web/aweme/post/?" + urlencode(params)
        data = request_json(api_url, headers)
        if data.get("status_code") != 0:
            raise RuntimeError(
                f"Post API failed on page {page}: status_code={data.get('status_code')} "
                f"status_msg={data.get('status_msg')}"
            )

        aweme_list = data.get("aweme_list") or []
        print(f"page={page} got={len(aweme_list)} has_more={data.get('has_more')}")

        for aweme in aweme_list:
            video = aweme.get("video") or {}
            play_addr = video.get("play_addr") or {}
            download_addr = video.get("download_addr") or {}
            stats = aweme.get("statistics") or {}

            all_videos.append(
                {
                    "aweme_id": aweme.get("aweme_id"),
                    "desc": aweme.get("desc"),
                    "create_time": aweme.get("create_time"),
                    "duration_ms": video.get("duration"),
                    "ratio": video.get("ratio"),
                    "play_url": (play_addr.get("url_list") or [None])[0],
                    "download_url": (download_addr.get("url_list") or [None])[0],
                    "play_uri": play_addr.get("uri"),
                    "download_uri": download_addr.get("uri"),
                    "digg_count": stats.get("digg_count"),
                    "comment_count": stats.get("comment_count"),
                    "collect_count": stats.get("collect_count"),
                    "share_count": stats.get("share_count"),
                    "play_count": stats.get("play_count"),
                }
            )

        if data.get("has_more") != 1:
            break
        max_cursor = str(data.get("max_cursor", "0"))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return all_videos


def main() -> None:
    parser = argparse.ArgumentParser(
        description="keyword -> first blogger -> sec_uid -> all videos -> export JSON"
    )
    parser.add_argument("--keyword", required=True, help="Search keyword.")
    parser.add_argument(
        "--template-url",
        default=os.getenv("DOUYIN_SEARCH_URL_TEMPLATE", ""),
        help="Captured search API URL with signature params.",
    )
    parser.add_argument(
        "--cookie",
        default=os.getenv("DY_COOKIES", ""),
        help="Douyin cookie string. Default reads DY_COOKIES.",
    )
    parser.add_argument(
        "--verify-fp",
        default=os.getenv("DY_VERIFY_FP", ""),
        help="verifyFp/fp value, usually s_v_web_id.",
    )
    parser.add_argument("--uifid", default="", help="Optional search header uifid.")
    parser.add_argument("--search-count", type=int, default=12, help="Search count for first request.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep seconds between pagination requests.")
    parser.add_argument("--output-dir", default="datas/keyword_videos", help="Output directory.")
    args = parser.parse_args()

    requests.packages.urllib3.disable_warnings()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not args.template_url:
        raise ValueError("Missing --template-url (or env DOUYIN_SEARCH_URL_TEMPLATE).")
    if not args.cookie:
        raise ValueError("Missing --cookie (or env DY_COOKIES).")
    if not args.verify_fp:
        raise ValueError("Missing --verify-fp (or env DY_VERIFY_FP).")

    blogger = fetch_first_blogger(
        keyword=args.keyword,
        template_url=args.template_url,
        cookie=args.cookie,
        count=args.search_count,
        uifid=args.uifid,
    )
    sec_uid = blogger["sec_uid"]
    print(f"first_blogger={blogger.get('nickname')} sec_uid={sec_uid}")

    videos = fetch_all_videos_by_sec_uid(
        sec_uid=sec_uid,
        cookie=args.cookie,
        verify_fp=args.verify_fp,
        sleep_seconds=args.sleep,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keyword = sanitize_filename(args.keyword)
    out_file = output_dir / f"first_{safe_keyword}_{timestamp}.json"

    payload = {
        "meta": {
            "keyword": args.keyword,
            "generated_at": datetime.now().isoformat(),
            "video_count": len(videos),
        },
        "blogger": blogger,
        "videos": videos,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"saved={out_file.resolve()}")
    print(f"video_count={len(videos)}")


if __name__ == "__main__":
    main()

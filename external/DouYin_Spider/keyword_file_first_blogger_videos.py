import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

from keyword_first_blogger_all_videos import (
    build_headers,
    fetch_all_videos_by_sec_uid,
    fetch_first_blogger,
    request_json,
    sanitize_filename,
)
from keyword_only_quickstart import (
    DEFAULT_COOKIE,
    DEFAULT_TEMPLATE_URL,
    DEFAULT_VERIFY_FP,
)


def load_keywords(file_path: str) -> List[str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Keyword file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    keywords: List[str] = []
    for line in lines:
        item = line.strip()
        if not item:
            continue
        if item.startswith("#"):
            continue
        keywords.append(item)
    # keep input order, remove duplicates
    seen = set()
    result: List[str] = []
    for kw in keywords:
        if kw in seen:
            continue
        seen.add(kw)
        result.append(kw)
    return result


def extract_blogger_profile(profile_json: Dict[str, Any]) -> Dict[str, Any]:
    user = profile_json.get("user") or {}
    return {
        "uid": user.get("uid"),
        "sec_uid": user.get("sec_uid"),
        "nickname": user.get("nickname"),
        "signature": user.get("signature"),
        "follower_count": user.get("follower_count"),
        "following_count": user.get("following_count"),
        "total_favorited": user.get("total_favorited"),
        "aweme_count": user.get("aweme_count"),
        "gender": user.get("gender"),
        "ip_location": user.get("ip_location"),
        "user_url": f"https://www.douyin.com/user/{user.get('sec_uid')}" if user.get("sec_uid") else None,
    }


def fetch_profile_by_sec_uid(sec_uid: str, cookie: str, verify_fp: str) -> Dict[str, Any]:
    referer = f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main"
    headers = build_headers(referer=referer, cookie=cookie)
    params = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "publish_video_strategy_type": "2",
        "source": "channel_pc_web",
        "sec_user_id": sec_uid,
        "personal_center_strategy": "1",
        "update_version_code": "170400",
        "pc_client_type": "1",
        "version_code": "170400",
        "version_name": "17.4.0",
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
    url = "https://www.douyin.com/aweme/v1/web/user/profile/other/?"
    query = "&".join([f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items()])
    data = request_json(url + query, headers)
    if data.get("status_code") != 0:
        raise RuntimeError(
            f"profile api failed: status_code={data.get('status_code')} status_msg={data.get('status_msg')}"
        )
    return extract_blogger_profile(data)


def build_result_item(
    keyword: str,
    blogger_basic: Dict[str, Any],
    blogger_profile: Dict[str, Any],
    videos: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "keyword": keyword,
        "blogger_basic": blogger_basic,
        "blogger_profile": blogger_profile,
        "video_count": len(videos),
        "videos": videos,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read keyword list -> pick first blogger per keyword -> fetch blogger profile -> "
            "fetch all videos (mp4 urls) -> export JSON."
        )
    )
    parser.add_argument("--keyword-file", default="datas/key/keyword.txt", help="Keyword file path, one keyword per line.")
    parser.add_argument(
        "--template-url",
        default=os.getenv("DOUYIN_SEARCH_URL_TEMPLATE", DEFAULT_TEMPLATE_URL),
        help="Captured search API URL.",
    )
    parser.add_argument(
        "--cookie",
        default=os.getenv("DY_COOKIES", DEFAULT_COOKIE),
        help="Douyin cookie string.",
    )
    parser.add_argument(
        "--verify-fp",
        default=os.getenv("DY_VERIFY_FP", DEFAULT_VERIFY_FP),
        help="s_v_web_id / verifyFp / fp value.",
    )
    parser.add_argument("--uifid", default="", help="Optional uifid header for search request.")
    parser.add_argument("--search-count", type=int, default=12, help="Search count for first page.")
    parser.add_argument("--page-sleep", type=float, default=0.2, help="Sleep seconds between video pagination requests.")
    parser.add_argument("--keyword-sleep", type=float, default=0.6, help="Sleep seconds between keywords.")
    parser.add_argument("--output-dir", default="datas/keyword_batch", help="Output directory.")
    parser.add_argument("--save-each", action="store_true", help="Save one JSON per keyword in addition to merged file.")
    args = parser.parse_args()

    requests.packages.urllib3.disable_warnings()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    keywords = load_keywords(args.keyword_file)
    if not keywords:
        print(f"No keywords found in: {args.keyword_file}")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    merged_items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, keyword in enumerate(keywords, start=1):
        print(f"\n[{idx}/{len(keywords)}] keyword={keyword}")
        try:
            blogger_basic = fetch_first_blogger(
                keyword=keyword,
                template_url=args.template_url,
                cookie=args.cookie,
                count=args.search_count,
                uifid=args.uifid,
            )
            sec_uid = blogger_basic["sec_uid"]
            print(f"first_blogger={blogger_basic.get('nickname')} sec_uid={sec_uid}")

            blogger_profile = fetch_profile_by_sec_uid(
                sec_uid=sec_uid,
                cookie=args.cookie,
                verify_fp=args.verify_fp,
            )
            videos = fetch_all_videos_by_sec_uid(
                sec_uid=sec_uid,
                cookie=args.cookie,
                verify_fp=args.verify_fp,
                sleep_seconds=args.page_sleep,
            )

            item = build_result_item(
                keyword=keyword,
                blogger_basic=blogger_basic,
                blogger_profile=blogger_profile,
                videos=videos,
            )
            merged_items.append(item)

            if args.save_each:
                safe_kw = sanitize_filename(keyword)
                each_file = output_dir / f"keyword_{safe_kw}.json"
                each_payload = {
                    "meta": {
                        "keyword": keyword,
                        "generated_at": datetime.now().isoformat(),
                        "video_count": len(videos),
                    },
                    "item": item,
                }
                each_file.write_text(json.dumps(each_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"saved_each={each_file.resolve()}")

            print(f"video_count={len(videos)}")
        except Exception as e:
            err = {"keyword": keyword, "error": str(e)}
            errors.append(err)
            print(f"error={e}")

        if args.keyword_sleep > 0 and idx < len(keywords):
            time.sleep(args.keyword_sleep)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_file = output_dir / f"keywords_merged_{stamp}.json"
    merged_payload = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "keyword_file": str(Path(args.keyword_file).resolve()),
            "total_keywords": len(keywords),
            "success_count": len(merged_items),
            "error_count": len(errors),
        },
        "items": merged_items,
        "errors": errors,
    }
    merged_file.write_text(json.dumps(merged_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nDone.")
    print(f"saved_merged={merged_file.resolve()}")
    print(f"success={len(merged_items)} error={len(errors)}")


if __name__ == "__main__":
    main()

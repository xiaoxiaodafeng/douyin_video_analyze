import argparse
import json
from datetime import datetime
from pathlib import Path

from keyword_first_blogger_all_videos import (
    fetch_all_videos_by_sec_uid,
    fetch_first_blogger,
    sanitize_filename,
)


# Preconfigured template values.
# Fill your own cookie/verify_fp in local environment before running.
DEFAULT_TEMPLATE_URL = (
    "https://www.douyin.com/aweme/v1/web/discover/search/"
    "?device_platform=webapp&aid=6383&channel=channel_pc_web&search_channel=aweme_user_web"
    "&keyword=%E5%B0%8F%E6%97%AD+AI+Studio&search_source=normal_search&query_correct_type=1"
    "&is_filter_search=0&from_group_id=&disable_rs=0&offset=0&count=12&need_filter_settings=1"
    "&list_type=&pc_search_top_1_params=%7B%22enable_ai_search_top_1%22%3A1%7D"
    "&update_version_code=170400&pc_client_type=1&pc_libra_divert=Windows&support_h265=1"
    "&support_dash=1&cpu_core_num=12&version_code=170400&version_name=17.4.0&cookie_enabled=true"
    "&screen_width=1920&screen_height=1080&browser_language=en&browser_platform=Win32"
    "&browser_name=Chrome&browser_version=146.0.0.0&browser_online=true&engine_name=Blink"
    "&engine_version=146.0.0.0&os_name=Windows&os_version=10&device_memory=8&platform=PC"
    "&downlink=10&effective_type=4g&round_trip_time=150"
)

DEFAULT_COOKIE = ""
DEFAULT_VERIFY_FP = ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Only pass keyword -> first blogger + all video URLs.")
    parser.add_argument("--keyword", required=True, help="Search keyword.")
    parser.add_argument("--output-dir", default="datas/keyword_videos_quick", help="Output directory.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep seconds between pages.")
    args = parser.parse_args()

    if not DEFAULT_COOKIE or not DEFAULT_VERIFY_FP:
        raise ValueError("Please set DEFAULT_COOKIE and DEFAULT_VERIFY_FP before running quickstart.")

    blogger = fetch_first_blogger(
        keyword=args.keyword,
        template_url=DEFAULT_TEMPLATE_URL,
        cookie=DEFAULT_COOKIE,
        count=12,
        uifid="",
    )
    sec_uid = blogger["sec_uid"]
    print(f"first_blogger={blogger.get('nickname')} sec_uid={sec_uid}")

    videos = fetch_all_videos_by_sec_uid(
        sec_uid=sec_uid,
        cookie=DEFAULT_COOKIE,
        verify_fp=DEFAULT_VERIFY_FP,
        sleep_seconds=args.sleep,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_kw = sanitize_filename(args.keyword)
    out_file = output_dir / f"quick_{safe_kw}_{stamp}.json"

    payload = {
        "meta": {
            "keyword": args.keyword,
            "generated_at": datetime.now().isoformat(),
            "video_count": len(videos),
        },
        "blogger": blogger,
        "videos": videos,
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"saved={out_file.resolve()}")
    print(f"video_count={len(videos)}")


if __name__ == "__main__":
    main()

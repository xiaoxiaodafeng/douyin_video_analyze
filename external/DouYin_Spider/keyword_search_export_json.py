import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests


def update_query_params(url: str, updates: Dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(updates)
    new_query = urlencode(query, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


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


def extract_user_rows(resp_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in (resp_json.get("user_list") or []):
        user_info = item.get("user_info") or {}
        rows.append(
            {
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
                "user_url": (
                    f"https://www.douyin.com/user/{user_info.get('sec_uid')}"
                    if user_info.get("sec_uid")
                    else None
                ),
            }
        )
    return rows


def sanitize_filename(name: str) -> str:
    keep = []
    for ch in name.strip():
        if ch in '<>:"/\\|?*':
            keep.append("_")
        else:
            keep.append(ch)
    result = "".join(keep).strip()
    return result or "keyword"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pass keyword, request Douyin search API, export JSON."
    )
    parser.add_argument("--keyword", required=True, help="Search keyword.")
    parser.add_argument(
        "--template-url",
        default=os.getenv("DOUYIN_SEARCH_URL_TEMPLATE", ""),
        help=(
            "Search API URL template. Can be full captured URL with all params. "
            "Keyword/offset/count will be overwritten automatically."
        ),
    )
    parser.add_argument(
        "--cookie",
        default=os.getenv("DY_COOKIES", ""),
        help="Douyin cookie string. Default from DY_COOKIES env.",
    )
    parser.add_argument("--uifid", default="", help="Optional uifid header value.")
    parser.add_argument("--referer", default="", help="Optional Referer override.")
    parser.add_argument("--offset", type=int, default=0, help="Start offset.")
    parser.add_argument("--count", type=int, default=12, help="Page size.")
    parser.add_argument("--pages", type=int, default=1, help="How many pages to request.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests.")
    parser.add_argument(
        "--output-dir", default="datas/search_json", help="Output directory for JSON file."
    )
    parser.add_argument("--save-raw-pages", action="store_true", help="Save full raw page JSON list.")
    args = parser.parse_args()

    requests.packages.urllib3.disable_warnings()

    if not args.template_url:
        raise ValueError("Missing --template-url (or DOUYIN_SEARCH_URL_TEMPLATE env).")
    if not args.cookie:
        raise ValueError("Missing --cookie (or DY_COOKIES env).")

    parsed_template = urlparse(args.template_url)
    q = dict(parse_qsl(parsed_template.query, keep_blank_values=True))
    q["keyword"] = args.keyword
    q["offset"] = str(args.offset)
    q["count"] = str(args.count)
    if "search_channel" not in q:
        q["search_channel"] = "aweme_user_web"
    if "search_source" not in q:
        q["search_source"] = "normal_search"
    url = urlunparse(
        (
            parsed_template.scheme,
            parsed_template.netloc,
            parsed_template.path,
            parsed_template.params,
            urlencode(q, doseq=True),
            parsed_template.fragment,
        )
    )

    referer = (
        args.referer
        or f"https://www.douyin.com/search/{args.keyword}?type=user"
    )
    headers = build_headers(referer=referer, cookie=args.cookie, uifid=args.uifid)

    all_rows: List[Dict[str, Any]] = []
    raw_pages: List[Dict[str, Any]] = []

    for page_idx in range(args.pages):
        curr_offset = args.offset + page_idx * args.count
        page_url = update_query_params(
            url,
            {
                "keyword": args.keyword,
                "offset": str(curr_offset),
                "count": str(args.count),
            },
        )
        resp = requests.get(page_url, headers=headers, timeout=30, verify=False)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP error: {resp.status_code} on page {page_idx + 1}")
        if not resp.content:
            abort_info = resp.headers.get("X-Whale-Throughput-Abort-Data", "")
            raise RuntimeError(f"Empty response on page {page_idx + 1}. abort={abort_info}")

        try:
            resp_json = resp.json()
        except Exception as e:
            raise RuntimeError(f"JSON decode failed on page {page_idx + 1}: {e}") from e

        status_code = resp_json.get("status_code")
        if status_code != 0:
            raise RuntimeError(
                f"API status_code={status_code} status_msg={resp_json.get('status_msg')}"
            )

        rows = extract_user_rows(resp_json)
        all_rows.extend(rows)
        if args.save_raw_pages:
            raw_pages.append(resp_json)

        has_more = resp_json.get("has_more")
        print(
            f"page={page_idx + 1} offset={curr_offset} count={len(rows)} has_more={has_more}"
        )
        if has_more != 1:
            break
        if args.sleep > 0:
            time.sleep(args.sleep)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keyword = sanitize_filename(args.keyword)
    out_file = output_dir / f"search_{safe_keyword}_{stamp}.json"

    result = {
        "meta": {
            "keyword": args.keyword,
            "pages_requested": args.pages,
            "count_per_page": args.count,
            "offset_start": args.offset,
            "generated_at": datetime.now().isoformat(),
            "total_items": len(all_rows),
        },
        "items": all_rows,
    }
    if args.save_raw_pages:
        result["raw_pages"] = raw_pages

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"saved={out_file.resolve()}")
    print(f"total_items={len(all_rows)}")


if __name__ == "__main__":
    main()

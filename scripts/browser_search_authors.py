import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="ignore")


def load_env_value(key: str) -> str:
    env_path = Path(".env")
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return ""


def parse_cookie_header(cookie_header: str) -> list[dict]:
    cookies = []
    for chunk in cookie_header.split(";"):
        item = chunk.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".douyin.com",
                "path": "/",
            }
        )
    return cookies


def avatar_url(user_info: dict) -> str:
    avatar = user_info.get("avatar_thumb") or {}
    urls = avatar.get("url_list") or []
    if isinstance(urls, list) and urls:
        first = urls[0]
        if isinstance(first, str):
            return first
    return ""


def normalize_author_row(user_item: dict) -> dict | None:
    user_info = user_item.get("user_info") or user_item.get("user") or {}
    if not user_info and isinstance(user_item.get("items"), list) and user_item["items"]:
        user_info = (user_item["items"][0] or {}).get("user_info") or {}
    if not user_info:
        return None

    stats = user_info.get("stats") or {}
    sec_uid = str(user_info.get("sec_uid") or user_info.get("sec_uid_v2") or "")
    uid = str(user_info.get("uid") or user_info.get("id") or "")
    nickname = str(user_info.get("nickname") or "")
    unique_id = str(user_info.get("unique_id") or "")
    if not (sec_uid or uid or nickname):
        return None

    return {
        "author_sec_uid": sec_uid,
        "author_id": uid,
        "author_name": nickname,
        "unique_id": unique_id,
        "signature": str(user_info.get("signature") or ""),
        "follower_count": int(stats.get("follower_count") or user_info.get("follower_count") or 0),
        "total_favorited": int(stats.get("total_favorited") or user_info.get("total_favorited") or 0),
        "avatar_url": avatar_url(user_info),
    }


async def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else ""
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    if not keyword.strip():
        print(json.dumps({"ok": False, "error": "keyword required"}, ensure_ascii=False))
        return 1

    captured_rows: list[dict] = []
    seen: set[str] = set()
    hit_event = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context()
        cookie_header = load_env_value("DY_COOKIE").strip()
        if cookie_header:
            await context.add_cookies(parse_cookie_header(cookie_header))
        page = await context.new_page()

        async def on_response(response):
            url = response.url
            if "/aweme/v1/web/discover/search/" not in url:
                return
            if "search_channel=aweme_user_web" not in url:
                return
            try:
                data = await response.json()
            except Exception:
                return
            for item in data.get("user_list") or []:
                row = normalize_author_row(item or {})
                if not row:
                    continue
                key = row["author_sec_uid"] or row["author_id"] or f'{row["author_name"]}_{row["unique_id"]}'
                if not key or key in seen:
                    continue
                seen.add(key)
                captured_rows.append(row)
                if len(captured_rows) >= limit:
                    hit_event.set()
            if captured_rows:
                hit_event.set()

        page.on("response", on_response)

        search_url = f"https://www.douyin.com/search/{quote(keyword)}?type=user"
        await page.goto(search_url, wait_until="domcontentloaded")

        try:
            await asyncio.wait_for(hit_event.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass

        await page.wait_for_timeout(3000)
        await browser.close()

    print(
        json.dumps(
            {
                "ok": True,
                "keyword": keyword,
                "items": captured_rows[:limit],
                "count": len(captured_rows[:limit]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

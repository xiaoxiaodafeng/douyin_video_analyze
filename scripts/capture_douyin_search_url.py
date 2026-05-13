import asyncio
import json
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright


TARGET_KEYWORD = "\u674e\u8815\u8815"
OUTPUT_FILE = Path("datasets/captured_search_request.json")


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


async def main() -> None:
    captured = {
        "keyword": TARGET_KEYWORD,
        "final_page_url": "",
        "requests": [],
    }

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

        def on_request(request):
            url = request.url
            if (
                "/aweme/v1/web/discover/search" in url
                or "/aweme/v1/web/general/search/single" in url
                or "/search/" in url
            ):
                captured["requests"].append(
                    {
                        "url": url,
                        "method": request.method,
                        "headers": request.headers,
                    }
                )

        page.on("request", on_request)

        search_url = f"https://www.douyin.com/search/{quote(TARGET_KEYWORD)}?type=user"
        print(f"open={search_url}")
        print("If Douyin asks for login or verification, complete it in the browser window.")
        print("Leave the browser on the search results page for about 20 seconds.")
        await page.goto(search_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(20000)
        captured["final_page_url"] = page.url
        captured["title"] = await page.title()

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved={OUTPUT_FILE.resolve()}")
        print(f"captured_count={len(captured['requests'])}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

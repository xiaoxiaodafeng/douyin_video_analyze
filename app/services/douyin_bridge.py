from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
import builtins
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from app.core.config import settings


def _ensure_path(path: str) -> Path:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    return p


def _import_douyin_api():
    # Compatibility for old dependency `protobuf_to_dict` under Python 3.x
    if not hasattr(builtins, "long"):
        setattr(builtins, "long", int)
    if not hasattr(builtins, "unicode"):
        setattr(builtins, "unicode", str)

    spider_path = _ensure_path(settings.douyin_spider_path)
    if str(spider_path) not in sys.path:
        sys.path.insert(0, str(spider_path))

    from builder.auth import DouyinAuth  # type: ignore
    from dy_apis.douyin_api import DouyinAPI  # type: ignore

    return DouyinAuth, DouyinAPI


def _import_generate_a_bogus():
    spider_path = _ensure_path(settings.douyin_spider_path)
    if str(spider_path) not in sys.path:
        sys.path.insert(0, str(spider_path))

    from utils.dy_util import generate_a_bogus  # type: ignore

    return generate_a_bogus


def _build_auth():
    DouyinAuth, DouyinAPI = _import_douyin_api()

    cookie = settings.dy_cookie.strip()
    if not cookie:
        raise RuntimeError("DY_COOKIE is required for spider integration")

    auth = DouyinAuth()
    auth.perepare_auth(cookie)
    return auth, DouyinAPI


def _load_spider_quickstart_defaults() -> dict[str, str]:
    out = {
        "template_url": "",
        "cookie": "",
        "verify_fp": "",
        "uifid": "",
    }
    try:
        spider_path = _ensure_path(settings.douyin_spider_path)
        quickstart_file = spider_path / "keyword_only_quickstart.py"
        if not quickstart_file.exists():
            return out

        text = quickstart_file.read_text(encoding="utf-8", errors="ignore")

        def _extract_concat_str(var_name: str) -> str:
            pos = text.find(var_name)
            if pos < 0:
                return ""
            assign_pos = text.find("(", pos)
            if assign_pos < 0:
                return ""
            end_pos = text.find(")\n", assign_pos)
            if end_pos < 0:
                end_pos = text.find(")\r\n", assign_pos)
            if end_pos < 0:
                end_pos = assign_pos + 20000
            block = text[assign_pos:end_pos]
            parts = re.findall(r'"([^"]*)"', block)
            return "".join(parts).strip()

        def _extract_simple_str(var_name: str) -> str:
            m = re.search(rf'{var_name}\s*=\s*"([^"]*)"', text)
            return m.group(1).strip() if m else ""

        out["template_url"] = _extract_concat_str("DEFAULT_TEMPLATE_URL")
        out["cookie"] = _extract_concat_str("DEFAULT_COOKIE")
        out["verify_fp"] = _extract_simple_str("DEFAULT_VERIFY_FP")
        if out["template_url"]:
            q = dict(parse_qsl(urlparse(out["template_url"]).query, keep_blank_values=True))
            out["uifid"] = str(q.get("uifid") or "").strip()
        return out
    except Exception:
        return out


def _load_captured_search_defaults() -> dict[str, Any]:
    out: dict[str, Any] = {
        "template_url": "",
        "cookie": "",
        "verify_fp": "",
        "uifid": "",
        "user_agent": "",
        "sec_ch_ua": "",
        "sec_ch_ua_mobile": "",
        "sec_ch_ua_platform": "",
        "referer": "",
        "source": "",
    }
    try:
        capture_file = Path("datasets/captured_search_request.json")
        if not capture_file.exists():
            return out

        payload = json.loads(capture_file.read_text(encoding="utf-8", errors="ignore"))
        requests_list = payload.get("requests") or []
        for item in requests_list:
            url = str((item or {}).get("url") or "")
            if "/aweme/v1/web/discover/search/" not in url:
                continue

            headers = (item or {}).get("headers") or {}
            q = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
            out["template_url"] = url
            out["cookie"] = (settings.dy_cookie or "").strip()
            out["verify_fp"] = (
                (settings.dy_verify_fp or "").strip()
                or str(q.get("verifyFp") or q.get("fp") or "")
            )
            out["uifid"] = str(headers.get("uifid") or q.get("uifid") or "").strip()
            out["user_agent"] = str(headers.get("user-agent") or headers.get("User-Agent") or "").strip()
            out["sec_ch_ua"] = str(headers.get("sec-ch-ua") or "").strip()
            out["sec_ch_ua_mobile"] = str(headers.get("sec-ch-ua-mobile") or "").strip()
            out["sec_ch_ua_platform"] = str(headers.get("sec-ch-ua-platform") or "").strip()
            out["referer"] = str(headers.get("referer") or "").strip()
            out["source"] = "captured_search_request"
            return out
    except Exception:
        return out
    return out


def _resolve_search_params() -> dict[str, str]:
    defaults = _load_spider_quickstart_defaults()
    captured = _load_captured_search_defaults()

    env_template = (settings.dy_search_template_url or "").strip()
    env_cookie = (settings.dy_cookie or "").strip()
    env_verify_fp = (settings.dy_verify_fp or "").strip()
    env_uifid = (settings.dy_uifid or "").strip()

    template_url = env_template or captured["template_url"] or defaults["template_url"]
    cookie = env_cookie or captured["cookie"] or defaults["cookie"]
    verify_fp = env_verify_fp or captured["verify_fp"] or defaults["verify_fp"]
    uifid = env_uifid
    if not uifid and template_url:
        q = dict(parse_qsl(urlparse(template_url).query, keep_blank_values=True))
        uifid = str(q.get("uifid") or "").strip()
    if not uifid:
        uifid = captured["uifid"] or defaults["uifid"]

    source = "env"
    if not env_template and captured["template_url"]:
        source = "captured_search_request"
    elif not env_template and defaults["template_url"]:
        source = "quickstart_defaults"
    if env_template and not env_cookie and defaults["cookie"]:
        source = "mixed_env_template_default_cookie"
    if not env_template and env_cookie and defaults["template_url"]:
        source = "mixed_default_template_env_cookie"

    return {
        "template_url": template_url,
        "cookie": cookie,
        "verify_fp": verify_fp,
        "uifid": uifid,
        "source": source,
    }


def _candidate_search_param_sets() -> list[dict[str, str]]:
    defaults = _load_spider_quickstart_defaults()
    captured = _load_captured_search_defaults()
    env_template = (settings.dy_search_template_url or "").strip()
    env_cookie = (settings.dy_cookie or "").strip()
    env_verify_fp = (settings.dy_verify_fp or "").strip()
    env_uifid = (settings.dy_uifid or "").strip()

    candidates: list[dict[str, str]] = []

    if captured["template_url"] and (env_cookie or captured["cookie"]):
        q = dict(parse_qsl(urlparse(captured["template_url"]).query, keep_blank_values=True))
        candidates.append(
            {
                "template_url": captured["template_url"],
                "cookie": env_cookie or captured["cookie"],
                "verify_fp": env_verify_fp or captured["verify_fp"] or str(q.get("verifyFp") or q.get("fp") or ""),
                "uifid": env_uifid or captured["uifid"] or str(q.get("uifid") or ""),
                "source": "captured_search_request",
                "user_agent": captured["user_agent"],
                "sec_ch_ua": captured["sec_ch_ua"],
                "sec_ch_ua_mobile": captured["sec_ch_ua_mobile"],
                "sec_ch_ua_platform": captured["sec_ch_ua_platform"],
                "referer": captured["referer"],
            }
        )

    if defaults["template_url"] and defaults["cookie"]:
        candidates.append(
            {
                "template_url": defaults["template_url"],
                "cookie": defaults["cookie"],
                "verify_fp": defaults["verify_fp"],
                "uifid": defaults["uifid"],
                "source": "quickstart_bundle",
            }
        )

    if env_template and env_cookie:
        q = dict(parse_qsl(urlparse(env_template).query, keep_blank_values=True))
        candidates.append(
            {
                "template_url": env_template,
                "cookie": env_cookie,
                "verify_fp": env_verify_fp or defaults["verify_fp"],
                "uifid": env_uifid or str(q.get("uifid") or "") or defaults["uifid"],
                "source": "env_bundle",
            }
        )

    if defaults["template_url"] and env_cookie:
        q = dict(parse_qsl(urlparse(defaults["template_url"]).query, keep_blank_values=True))
        candidates.append(
            {
                "template_url": defaults["template_url"],
                "cookie": env_cookie,
                "verify_fp": env_verify_fp or defaults["verify_fp"],
                "uifid": env_uifid or str(q.get("uifid") or "") or defaults["uifid"],
                "source": "mixed_default_template_env_cookie",
            }
        )

    if env_template and defaults["cookie"]:
        q = dict(parse_qsl(urlparse(env_template).query, keep_blank_values=True))
        candidates.append(
            {
                "template_url": env_template,
                "cookie": defaults["cookie"],
                "verify_fp": env_verify_fp or defaults["verify_fp"],
                "uifid": env_uifid or str(q.get("uifid") or "") or defaults["uifid"],
                "source": "mixed_env_template_default_cookie",
            }
        )

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in candidates:
        key = (
            item["template_url"],
            item["cookie"],
            item["verify_fp"],
            item["uifid"],
            item["source"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _to_datetime(ts: Any):
    if ts in (None, ""):
        return None
    try:
        iv = int(ts)
        if iv > 1000000000:
            return datetime.fromtimestamp(iv)
    except Exception:
        pass
    return None


def _cid_to_datetime(cid: Any):
    """
    Decode Douyin/TikTok-style snowflake id timestamp.
    Many crawled comments do not expose explicit time fields, but cid embeds time.
    """
    try:
        iv = int(str(cid).strip())
    except Exception:
        return None
    if iv <= 0:
        return None
    # Try multiple known ID timestamp layouts; choose a plausible datetime.
    # We only accept dates in a sane window to avoid future-year artifacts.
    now = datetime.now()
    lower = datetime(2018, 1, 1)
    upper = datetime(now.year + 1, 12, 31, 23, 59, 59)
    candidates: list[datetime] = []

    try:
        # Common Douyin/TikTok style (empirically aligned with this dataset).
        ts_ms = (iv >> 24) + 1288834974657
        candidates.append(datetime.fromtimestamp(ts_ms / 1000.0))
    except Exception:
        pass

    try:
        # Alternate shifts seen in some variants.
        ts_ms = (iv >> 25) + 1466352806727
        candidates.append(datetime.fromtimestamp(ts_ms / 1000.0))
    except Exception:
        pass

    try:
        ts_ms = (iv >> 26) + 1577836800000
        candidates.append(datetime.fromtimestamp(ts_ms / 1000.0))
    except Exception:
        pass

    for dt in candidates:
        if lower <= dt <= upper:
            return dt
    return None


def _avatar_url(user_info: dict[str, Any]) -> str:
    avatar = user_info.get("avatar_thumb") or {}
    urls = avatar.get("url_list") or []
    if isinstance(urls, list) and urls:
        first = urls[0]
        if isinstance(first, str):
            return first
    return ""




def _extract_user_info(user_item: dict[str, Any]) -> dict[str, Any]:
    user_info = user_item.get("user_info") or user_item.get("user") or {}
    if not user_info and isinstance(user_item.get("items"), list) and user_item["items"]:
        user_info = (user_item["items"][0] or {}).get("user_info") or {}
    return user_info


def _normalize_author_row(user_item: dict[str, Any]) -> dict[str, Any] | None:
    user_info = _extract_user_info(user_item)
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
        "avatar_url": _avatar_url(user_info),
    }


def _dedupe_author_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_n = max(1, min(int(limit), 100))
    for row in rows:
        key = row.get("author_sec_uid") or row.get("author_id") or f"{row.get('author_name', '')}_{row.get('unique_id', '')}"
        key = str(key).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= max_n:
            break
    return out


def _search_authors_via_signed_user_api(author_name: str, limit: int) -> list[dict[str, Any]]:
    auth, DouyinAPI = _build_auth()
    users = DouyinAPI.search_some_user(auth, author_name.strip(), max(1, min(int(limit), 100)))
    rows = [_normalize_author_row(u or {}) for u in users]
    normalized = [row for row in rows if row]
    return _dedupe_author_rows(normalized, limit)


def _search_authors_via_general_work_api(author_name: str, limit: int) -> list[dict[str, Any]]:
    auth, DouyinAPI = _build_auth()
    works = DouyinAPI.search_some_general_work(auth, author_name.strip(), max(1, min(int(limit), 100)), "0", "0")
    rows: list[dict[str, Any]] = []
    for item in works:
        aweme = (item or {}).get("aweme_info") or {}
        author = aweme.get("author") or {}
        rows.append(
            {
                "author_sec_uid": str(author.get("sec_uid") or ""),
                "author_id": str(author.get("uid") or ""),
                "author_name": str(author.get("nickname") or ""),
                "unique_id": str(author.get("unique_id") or ""),
                "signature": str(author.get("signature") or ""),
                "follower_count": int(author.get("follower_count") or 0),
                "total_favorited": int(author.get("total_favorited") or 0),
                "avatar_url": _avatar_url(author),
            }
        )
    return _dedupe_author_rows(rows, limit)


def _to_video_row(aweme_info: dict[str, Any], fallback_author_name: str = "") -> dict[str, Any]:
    stats = aweme_info.get("statistics") or {}
    author = aweme_info.get("author") or {}
    video = aweme_info.get("video") or {}
    play_addr = video.get("play_addr") or {}
    download_addr = video.get("download_addr") or {}
    play_urls = play_addr.get("url_list") or []
    download_urls = download_addr.get("url_list") or []
    aweme_id = str(aweme_info.get("aweme_id") or "")
    return {
        "video_id": aweme_id,
        "title": str(aweme_info.get("desc") or ""),
        "desc": str(aweme_info.get("desc") or ""),
        "author_name": str(author.get("nickname") or fallback_author_name),
        "author_id": str(author.get("uid") or ""),
        "duration": int((aweme_info.get("video") or {}).get("duration") or 0) // 1000,
        "digg_count": int(stats.get("digg_count") or 0),
        "comment_count": int(stats.get("comment_count") or 0),
        "collect_count": int(stats.get("collect_count") or 0),
        "share_count": int(stats.get("share_count") or 0),
        "create_time": _to_datetime(aweme_info.get("create_time")),
        "music_name": str(((aweme_info.get("music") or {}).get("title")) or ""),
        "video_url": f"https://www.douyin.com/video/{aweme_id}" if aweme_id else "",
        "play_url": play_urls[0] if play_urls else "",
        "download_url": download_urls[0] if download_urls else "",
        "media_url": (download_urls[0] if download_urls else None) or (play_urls[0] if play_urls else ""),
    }




def _update_query_params(url: str, updates: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(updates)
    new_query = urlencode(query, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _build_signed_template_search_url(template_url: str, author_name: str, limit: int, verify_fp: str) -> str:
    parsed = urlparse(template_url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query_pairs: list[tuple[str, str]] = []
    seen_keys: set[str] = set()

    dynamic_values = {
        "keyword": author_name,
        "offset": "0",
        "count": str(max(1, min(int(limit), 100))),
        "search_channel": "aweme_user_web",
        "search_source": "normal_search",
        "is_filter_search": "0",
        "from_group_id": "",
        "disable_rs": "0",
        "need_filter_settings": "1",
        "list_type": "single",
    }
    if verify_fp:
        dynamic_values["verifyFp"] = verify_fp
        dynamic_values["fp"] = verify_fp

    for key, value in pairs:
        if key in {"a_bogus", "search_id"}:
            continue
        seen_keys.add(key)
        query_pairs.append((key, dynamic_values.get(key, value)))

    for key, value in dynamic_values.items():
        if key not in seen_keys:
            query_pairs.append((key, value))

    unsigned_query = urlencode(query_pairs, doseq=True)
    generate_a_bogus = _import_generate_a_bogus()
    a_bogus = generate_a_bogus(unsigned_query, "")
    signed_query = f"{unsigned_query}&a_bogus={quote(str(a_bogus), safe='')}"
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, signed_query, parsed.fragment))


def _effective_template_url() -> str:
    return _resolve_search_params().get("template_url", "")


def _template_search_users(author_name: str, limit: int, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    params = params or _resolve_search_params()
    template_url = params["template_url"]
    if not template_url:
        return []

    try:
        import requests
    except Exception:
        return []

    cookie = params["cookie"]
    if not cookie:
        return []

    verify_fp = (params.get("verify_fp") or "").strip()
    url = _build_signed_template_search_url(template_url, author_name, limit, verify_fp)

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8,zh-TW;q=0.7",
        "Connection": "keep-alive",
        "Referer": params.get("referer") or f"https://www.douyin.com/search/{quote(author_name)}?type=user",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": params.get("user_agent") or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": params.get("sec_ch_ua") or '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": params.get("sec_ch_ua_mobile") or "?0",
        "sec-ch-ua-platform": params.get("sec_ch_ua_platform") or '"Windows"',
        "Cookie": cookie,
    }
    q = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
    uifid = params["uifid"] or str(q.get("uifid") or "").strip()
    if uifid:
        headers["uifid"] = uifid

    resp = requests.get(url, headers=headers, timeout=30, verify=False)
    if resp.status_code != 200:
        raise RuntimeError(f"template search http error: {resp.status_code}")
    if not resp.content:
        abort_info = resp.headers.get("X-Whale-Throughput-Abort-Data", "")
        raise RuntimeError(f"template search empty response. abort={abort_info}")

    try:
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"template search json decode failed: {e}") from e

    if data.get("status_code") != 0:
        raise RuntimeError(
            f"template search api failed: status_code={data.get('status_code')} "
            f"status_msg={data.get('status_msg')}"
        )

    users = data.get('user_list') or []
    if not users:
        raise RuntimeError("template search returned empty user_list")

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for u in users:
        row = _normalize_author_row(u or {})
        if not row:
            continue
        key = row['author_sec_uid'] or row['author_id'] or f"{row['author_name']}_{row['unique_id']}"
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    if not out:
        raise RuntimeError("template search user_list exists but no normalized authors")
    return out


def _browser_search_users(author_name: str, limit: int) -> list[dict[str, Any]]:
    script = Path("scripts/browser_search_authors.py")
    if not script.exists():
        raise FileNotFoundError(f"browser search script not found: {script}")

    py = Path(".venv/Scripts/python.exe")
    if not py.exists():
        py = Path(sys.executable)

    proc = subprocess.run(
        [str(py), str(script), author_name, str(limit)],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "browser search failed")

    raw = (proc.stdout or "").strip().splitlines()
    payload_text = raw[-1] if raw else ""
    if not payload_text:
        raise RuntimeError("browser search returned empty stdout")

    data = json.loads(payload_text)
    items = data.get("items") or []
    if not items:
        raise RuntimeError("browser search returned empty items")
    return items


def search_authors_by_name_diagnose(author_name: str, limit: int = 10) -> dict[str, Any]:
    resolved = _resolve_search_params()
    candidate_sets = _candidate_search_param_sets()
    info: dict[str, Any] = {
        'results': [],
        'source': '',
        'diagnosis': {
            'cookie_len': len((resolved.get('cookie') or '').strip()),
            'has_verify_fp': bool((resolved.get('verify_fp') or '').strip()),
            'has_template_url': bool(resolved.get('template_url')),
            'has_uifid': bool((resolved.get('uifid') or '').strip()),
            'search_params_source': resolved.get("source", ""),
            'candidate_param_sources': [c.get("source", "") for c in candidate_sets],
            'attempts': [],
        },
    }

    if not author_name or not author_name.strip():
        info['diagnosis']['attempts'].append({'path': 'input', 'ok': False, 'error': 'empty author_name'})
        return info

    max_n = max(1, min(int(limit), 100))

    # Path A: signed user search (same signature chain as comment/video crawl)
    try:
        rows = _search_authors_via_signed_user_api(author_name, max_n)
        attempt = {'path': 'search_some_user', 'ok': bool(rows), 'count': len(rows)}
        if not rows:
            attempt['error'] = 'search_some_user returned empty rows'
        info['diagnosis']['attempts'].append(attempt)
        if rows:
            info['results'] = rows[:max_n]
            info['source'] = 'search_some_user'
            return info
    except Exception as e:
        info['diagnosis']['attempts'].append({'path': 'search_some_user', 'ok': False, 'error': str(e)})

    # Path B: infer from general work search authors
    try:
        rows = _search_authors_via_general_work_api(author_name, max_n)
        attempt = {'path': 'search_some_general_work', 'ok': bool(rows), 'count': len(rows)}
        if not rows:
            attempt['error'] = 'search_some_general_work returned no author candidates'
        info['diagnosis']['attempts'].append(attempt)
        if rows:
            info['results'] = rows[:max_n]
            info['source'] = 'search_some_general_work'
            return info
    except Exception as e:
        info['diagnosis']['attempts'].append({'path': 'search_some_general_work', 'ok': False, 'error': str(e)})

    # Path C: template URL captured from browser
    for candidate in candidate_sets:
        try:
            rows = _template_search_users(author_name.strip(), max_n, candidate)
            attempt = {
                'path': 'template_url_user_search',
                'param_source': candidate.get('source', ''),
                'ok': bool(rows),
                'count': len(rows),
            }
            if not rows:
                attempt['error'] = 'template search returned empty rows'
            info['diagnosis']['attempts'].append(attempt)
            if rows:
                info['results'] = rows[:max_n]
                info['source'] = f"template_url_user_search:{candidate.get('source', '')}"
                return info
        except Exception as e:
            info['diagnosis']['attempts'].append(
                {
                    'path': 'template_url_user_search',
                    'param_source': candidate.get('source', ''),
                    'ok': False,
                    'error': str(e),
                }
            )

    try:
        rows = _browser_search_users(author_name.strip(), max_n)
        info['diagnosis']['attempts'].append(
            {
                'path': 'browser_search_user',
                'ok': bool(rows),
                'count': len(rows),
            }
        )
        if rows:
            info['results'] = rows[:max_n]
            info['source'] = 'browser_search_user'
            return info
    except Exception as e:
        info['diagnosis']['attempts'].append(
            {
                'path': 'browser_search_user',
                'ok': False,
                'error': str(e),
            }
        )

    return info

def search_authors_by_name(author_name: str, limit: int = 10) -> list[dict[str, Any]]:
    return search_authors_by_name_diagnose(author_name, limit).get('results', [])


def search_author_by_douyin_id_diagnose(douyin_id: str, limit: int = 20) -> dict[str, Any]:
    did = str(douyin_id or "").strip()
    if not did:
        return {
            "results": [],
            "source": "",
            "diagnosis": {
                "attempts": [{"path": "input", "ok": False, "error": "empty douyin_id"}],
            },
        }

    scan_limit = max(10, min(max(int(limit), 50), 100))
    base = search_authors_by_name_diagnose(did, scan_limit)
    rows = base.get("results") or []
    normalized = did.lower()
    exact = [r for r in rows if str(r.get("unique_id") or "").strip().lower() == normalized]

    diagnosis = base.get("diagnosis", {})
    attempts = diagnosis.get("attempts") or []
    attempts.append(
        {
            "path": "exact_unique_id_filter",
            "ok": bool(exact),
            "query": did,
            "scanned_count": len(rows),
            "count": len(exact),
            "error": "" if exact else "no exact unique_id match",
        }
    )
    diagnosis["attempts"] = attempts

    if exact:
        return {
            "results": exact[: max(1, min(int(limit), 100))],
            "source": f"{base.get('source', '')}:exact_unique_id",
            "diagnosis": diagnosis,
        }

    return {
        "results": [],
        "source": "",
        "diagnosis": diagnosis,
    }


def fetch_videos_by_author_sec_uid(author_sec_uid: str, limit: int, fallback_author_name: str = "") -> list[dict[str, Any]]:
    if not author_sec_uid:
        return []

    auth, DouyinAPI = _build_auth()
    user_url = f"https://www.douyin.com/user/{author_sec_uid}"
    works = DouyinAPI.get_user_all_work_info(auth, user_url)

    out = [_to_video_row(aweme_info, fallback_author_name) for aweme_info in works[: int(limit)]]
    return [x for x in out if x["video_id"]]


def fetch_videos_by_keyword_or_author(
    keyword: str | None,
    author_name: str | None,
    limit: int,
    author_sec_uid: str | None = None,
    douyin_id: str | None = None,
) -> list[dict[str, Any]]:
    auth, DouyinAPI = _build_auth()

    if keyword:
        works = DouyinAPI.search_some_general_work(auth, keyword, limit, "0", "0")
        out = []
        for item in works:
            aweme_info = item.get("aweme_info") or {}
            out.append(_to_video_row(aweme_info, author_name or ""))
        return [x for x in out if x["video_id"]]

    if author_name or author_sec_uid or douyin_id:
        sec_uid = (author_sec_uid or "").strip()
        nickname = author_name or douyin_id or ""

        if not sec_uid and douyin_id:
            diag = search_author_by_douyin_id_diagnose(douyin_id, max(5, int(limit)))
            rows = diag.get("results") or []
            if rows:
                first = rows[0]
                nickname = str(first.get("author_name") or nickname)
                sec_uid = str(first.get("author_sec_uid") or "")
            if not sec_uid:
                return []

        if not sec_uid:
            rows: list[dict[str, Any]] = []
            # Explicitly prefer the signed user-search chain for resolving sec_uid.
            try:
                rows = _search_authors_via_signed_user_api(author_name or "", max(5, int(limit)))
            except Exception:
                rows = []
            if not rows:
                diag = search_authors_by_name_diagnose(author_name or "", max(5, int(limit)))
                rows = diag.get("results") or []
            if rows:
                first = rows[0]
                nickname = str(first.get("author_name") or nickname)
                sec_uid = str(first.get("author_sec_uid") or "")
            if not sec_uid:
                return []

        return fetch_videos_by_author_sec_uid(sec_uid, limit, nickname)

    return []


def fetch_video_by_url(video_url: str) -> dict[str, Any] | None:
    auth, DouyinAPI = _build_auth()

    res = DouyinAPI.get_work_info(auth, video_url)
    aweme_info = (res or {}).get("aweme_detail") or {}
    if not aweme_info:
        return None

    aweme_id = str(aweme_info.get("aweme_id") or "")
    if not aweme_id:
        return None

    return _to_video_row(aweme_info)


def fetch_video_media_info(video_id: str) -> dict[str, Any]:
    auth, DouyinAPI = _build_auth()
    page_url = f"https://www.douyin.com/video/{video_id}"
    res = DouyinAPI.get_work_info(auth, page_url)
    aweme_info = (res or {}).get("aweme_detail") or {}
    if not aweme_info:
        raise RuntimeError("video detail not found from douyin spider")

    video = aweme_info.get("video") or {}
    play_addr = video.get("play_addr") or {}
    download_addr = video.get("download_addr") or {}
    play_urls = play_addr.get("url_list") or []
    download_urls = download_addr.get("url_list") or []
    media_url = (download_urls[0] if download_urls else None) or (play_urls[0] if play_urls else None)
    return {
        "video_id": str(aweme_info.get("aweme_id") or video_id),
        "page_url": page_url,
        "media_url": media_url or "",
        "play_url": play_urls[0] if play_urls else "",
        "download_url": download_urls[0] if download_urls else "",
        "duration_ms": int(video.get("duration") or 0),
        "desc": str(aweme_info.get("desc") or ""),
    }


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _comment_runner_script() -> Path:
    script = _project_root() / "scripts" / "comment_crawl_runner.js"
    if not script.exists():
        raise FileNotFoundError(f"Comment runner script not found: {script}")
    return script


def _comment_output_file(video_id: str) -> Path:
    out_file = _project_root() / "outputs" / f"douyin_comments_{video_id}_bridge.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    return out_file


def build_comment_crawl_cmd(video_id: str, limit: int, reply_limit: int) -> tuple[list[str], Path]:
    out_file = _comment_output_file(video_id)
    cmd = [
        "node",
        str(_comment_runner_script()),
        str(video_id),
        f"--limit={int(limit)}",
        f"--reply-limit={int(reply_limit)}",
        f"--output={str(out_file)}",
    ]
    return cmd, out_file


def _load_comment_rows_from_file(video_id: str, out_file: Path) -> list[dict[str, Any]]:
    if not out_file.exists():
        raise RuntimeError("comment output not generated")

    data = json.loads(out_file.read_text(encoding="utf-8"))
    comments: list[dict[str, Any]] = []

    for c in data:
        cid = str(c.get("cid") or "")
        if not cid:
            continue
        comments.append(
            {
                "comment_id": cid,
                "video_id": str(video_id),
                "user_name": str(c.get("user_name") or ""),
                "content": str(c.get("text") or ""),
                "digg_count": int(c.get("digg_count") or 0),
                "reply_count": len(c.get("replies") or []),
                "create_time": _to_datetime(c.get("create_time")) or _to_datetime(c.get("create_timestamp")),
                "ip_label": str(c.get("ip_label") or ""),
            }
        )

        for reply in c.get("replies") or []:
            rcid = str(reply.get("cid") or "")
            if not rcid:
                continue
            comments.append(
                {
                    "comment_id": f"{cid}_{rcid}",
                    "video_id": str(video_id),
                    "user_name": str(reply.get("user_name") or ""),
                    "content": str(reply.get("text") or ""),
                    "digg_count": int(reply.get("digg_count") or 0),
                    "reply_count": 0,
                    "create_time": _to_datetime(reply.get("create_time")) or _to_datetime(reply.get("create_timestamp")),
                    "ip_label": str(reply.get("ip_label") or ""),
                }
            )

    return comments


def fetch_comments_by_video_id(video_id: str, limit: int, reply_limit: int) -> list[dict[str, Any]]:
    analyze_path = _ensure_path(settings.dy_analyze_path)
    cmd, out_file = build_comment_crawl_cmd(video_id, limit, reply_limit)

    proc = subprocess.run(cmd, cwd=str(analyze_path), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"comment crawl failed: {proc.stderr or proc.stdout}")
    return _load_comment_rows_from_file(video_id, out_file)


def load_comments_from_output(video_id: str, out_file: Path) -> list[dict[str, Any]]:
    return _load_comment_rows_from_file(video_id, out_file)

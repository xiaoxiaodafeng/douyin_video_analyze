import argparse
from pathlib import Path
from urllib.parse import urlparse

from builder.auth import DouyinAuth
from dy_apis.douyin_api import DouyinAPI
from dy_live.server import DouyinLive
from keyword_only_quickstart import DEFAULT_COOKIE
from utils.dy_util import generate_signature


REQUIRED_COOKIE_KEYS = (
    "ttwid",
    "sessionid",
    "sid_tt",
    "s_v_web_id",
    "passport_csrf_token",
)
RECOMMENDED_COOKIE_KEYS = (
    "uifid",
    "x-web-secsdk-uid",
    "odin_tt",
    "sid_guard",
)


def parse_live_id(value: str) -> str:
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        path = urlparse(value).path.strip("/")
        return path.split("?", 1)[0]
    return value.split("?", 1)[0]


def run_preflight(auth: DouyinAuth, live_id: str) -> None:
    cookie = auth.cookie or {}
    print("[Preflight] Checking required cookie keys...")
    missing = [k for k in REQUIRED_COOKIE_KEYS if not cookie.get(k)]
    if missing:
        raise RuntimeError(f"Missing required cookie keys: {', '.join(missing)}")
    print("[Preflight] Required cookie keys: OK")
    missing_recommended = [k for k in RECOMMENDED_COOKIE_KEYS if not cookie.get(k)]
    if missing_recommended:
        print(f"[Preflight] Cookie richness: WARN (missing {', '.join(missing_recommended)})")
    else:
        print("[Preflight] Cookie richness: OK")

    warnings = []
    if cookie.get("sessionid") and cookie.get("sid_tt") and cookie["sessionid"] != cookie["sid_tt"]:
        warnings.append("sessionid != sid_tt")
    if cookie.get("sessionid") and cookie.get("sessionid_ss") and cookie["sessionid"] != cookie["sessionid_ss"]:
        warnings.append("sessionid != sessionid_ss")
    if cookie.get("uid_tt") and cookie.get("uid_tt_ss") and cookie["uid_tt"] != cookie["uid_tt_ss"]:
        warnings.append("uid_tt != uid_tt_ss")
    if cookie.get("sid_guard") and cookie.get("sessionid"):
        if not cookie["sid_guard"].startswith(cookie["sessionid"]):
            warnings.append("sid_guard does not start with sessionid")

    if warnings:
        print(f"[Preflight] Cookie consistency: WARN ({'; '.join(warnings)})")
    else:
        print("[Preflight] Cookie consistency: OK")

    print("[Preflight] Checking live enter API...")
    room_info = DouyinAPI.get_live_info(auth, live_id)
    if not isinstance(room_info, dict):
        raise RuntimeError(f"Invalid room info payload: {room_info}")
    room_id = str(room_info.get("room_id", "")).strip()
    user_id = str(room_info.get("user_id", "")).strip()
    room_status = str(room_info.get("room_status", "")).strip()
    ws_user_unique_id = str(room_info.get("ws_user_unique_id") or room_info.get("user_id") or "").strip()
    if not room_id or not user_id:
        raise RuntimeError(f"Missing room_id/user_id in room info: {room_info}")
    print(
        "[Preflight] Live enter API: OK "
        f"room_id={room_id} user_id={user_id} ws_user_unique_id={ws_user_unique_id} status={room_status}"
    )
    if room_status and room_status != "2":
        raise RuntimeError(f"Live room is not active (status={room_status}).")

    print("[Preflight] Checking signature generation...")
    signature = generate_signature(room_id, ws_user_unique_id or user_id)
    if not signature:
        raise RuntimeError("Generated signature is empty.")
    print(f"[Preflight] Signature: OK len={len(signature)}")
    print("[Preflight] Passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Douyin live danmu listener.")
    parser.add_argument(
        "--live",
        default="505866813997",
        help="live_id or full live url, e.g. 505866813997 or https://live.douyin.com/505866813997?...",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip startup preflight checks.",
    )
    parser.add_argument(
        "--cookie-file",
        default="",
        help="Path to a file containing full Cookie string.",
    )
    parser.add_argument(
        "--cookie",
        default="",
        help="Full Cookie string (overrides --cookie-file).",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run preflight checks only and exit.",
    )
    args = parser.parse_args()

    live_id = parse_live_id(args.live)
    if not live_id:
        raise ValueError("Invalid live id/url.")

    cookie_str = ""
    if args.cookie:
        cookie_str = args.cookie.strip()
    elif args.cookie_file:
        cookie_path = Path(args.cookie_file)
        if not cookie_path.exists():
            raise FileNotFoundError(f"Cookie file not found: {cookie_path}")
        cookie_str = cookie_path.read_text(encoding="utf-8").strip()
    else:
        cookie_str = DEFAULT_COOKIE.strip()
        print("[Cookie] Using built-in default cookie (minimal).")
        print("[Cookie] Tip: pass --cookie-file with a full browser cookie for better success rate.")

    auth = DouyinAuth()
    auth.perepare_auth(cookie_str, "", "")

    if not args.skip_preflight:
        try:
            run_preflight(auth, live_id)
        except Exception as exc:
            print(f"[Preflight] FAILED: {exc}")
            print("[Preflight] Tip: refresh one full cookie set from the same browser session and retry.")
            raise SystemExit(2)

    if args.preflight_only:
        return

    print(f"Starting listener for live_id={live_id}")
    DouyinLive(live_id, auth).start_ws()


if __name__ == "__main__":
    main()

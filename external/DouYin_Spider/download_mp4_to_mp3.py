import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
import imageio_ffmpeg


def sanitize_text(text: str, max_len: int = 60) -> str:
    text = (text or "").strip().replace("\n", " ").replace("\r", " ")
    text = re.sub(r"[<>:\"/\\|?*]", "_", text)
    text = re.sub(r"\s+", " ", text)
    if not text:
        text = "untitled"
    return text[:max_len].strip()


def download_file(url: str, target: Path, timeout: int = 30, retries: int = 3) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        )
    }
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, headers=headers, stream=True, timeout=timeout, verify=False) as resp:
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                with open(target, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            if target.exists() and target.stat().st_size > 0:
                return True
        except Exception:
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
            if attempt < retries:
                time.sleep(1.5 * attempt)
    return False


def mp4_to_mp3(ffmpeg_exe: str, mp4_path: Path, mp3_path: Path) -> bool:
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(mp4_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-ab",
        "192k",
        str(mp3_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 0


def pick_video_url(item: Dict) -> Optional[str]:
    return item.get("download_url") or item.get("play_url")


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch download Douyin MP4 and convert to MP3.")
    parser.add_argument("--input", required=True, help="Path to JSON generated from mp4 data.")
    parser.add_argument("--out-mp4", default="datas/mp4", help="Output folder for downloaded mp4.")
    parser.add_argument("--out-mp3", default="datas/mp3", help="Output folder for converted mp3.")
    parser.add_argument("--report", default="datas/mp3_convert_report.json", help="Output report json path.")
    parser.add_argument("--limit", type=int, default=0, help="Process first N items only; 0 means all.")
    parser.add_argument("--keep-mp4", action="store_true", help="Keep mp4 files after conversion.")
    args = parser.parse_args()

    requests.packages.urllib3.disable_warnings()
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    input_path = Path(args.input)
    out_mp4 = Path(args.out_mp4)
    out_mp3 = Path(args.out_mp3)
    report_path = Path(args.report)

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        items: List[Dict] = json.load(f)

    if args.limit > 0:
        items = items[: args.limit]

    report: List[Dict] = []
    total = len(items)
    ok = 0
    skipped = 0
    failed = 0

    for idx, item in enumerate(items, start=1):
        aweme_id = str(item.get("aweme_id") or f"unknown_{idx}")
        desc = sanitize_text(item.get("desc") or "")
        video_url = pick_video_url(item)
        if not video_url:
            failed += 1
            report.append(
                {
                    "aweme_id": aweme_id,
                    "status": "failed",
                    "reason": "missing_video_url",
                }
            )
            print(f"[{idx}/{total}] fail {aweme_id} missing url")
            continue

        file_stub = f"{idx:04d}_{aweme_id}_{desc}" if desc else f"{idx:04d}_{aweme_id}"
        mp4_path = out_mp4 / f"{file_stub}.mp4"
        mp3_path = out_mp3 / f"{file_stub}.mp3"

        if mp3_path.exists() and mp3_path.stat().st_size > 0:
            skipped += 1
            report.append(
                {
                    "aweme_id": aweme_id,
                    "status": "skipped",
                    "mp3": str(mp3_path),
                }
            )
            print(f"[{idx}/{total}] skip {aweme_id} mp3 exists")
            continue

        if not mp4_path.exists() or mp4_path.stat().st_size == 0:
            print(f"[{idx}/{total}] download {aweme_id}")
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
                print(f"[{idx}/{total}] fail {aweme_id} download failed")
                continue

        print(f"[{idx}/{total}] convert {aweme_id}")
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
            print(f"[{idx}/{total}] fail {aweme_id} convert failed")
            continue

        if not args.keep_mp4 and mp4_path.exists():
            try:
                mp4_path.unlink()
            except OSError:
                pass

        ok += 1
        report.append(
            {
                "aweme_id": aweme_id,
                "status": "ok",
                "mp3": str(mp3_path),
            }
        )
        print(f"[{idx}/{total}] ok {aweme_id}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\nDone.")
    print(f"total={total} ok={ok} skipped={skipped} failed={failed}")
    print(f"mp3_dir={out_mp3.resolve()}")
    print(f"report={report_path.resolve()}")


if __name__ == "__main__":
    main()

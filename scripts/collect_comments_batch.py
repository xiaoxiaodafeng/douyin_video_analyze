from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def find_video_ids(info_root: Path, max_ids: int) -> list[str]:
    ids: list[str] = []
    for info in info_root.rglob("info.json"):
        vid = info.parent.name.strip()
        if vid.isdigit() and len(vid) >= 18:
            ids.append(vid)
    # keep order but dedupe
    seen = set()
    out = []
    for v in ids:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
        if len(out) >= max_ids:
            break
    return out


def count_texts(comment_json: Path) -> int:
    try:
        data = json.loads(comment_json.read_text(encoding="utf-8"))
    except Exception:
        return 0
    n = 0
    for c in data:
        if (c.get("text") or "").strip():
            n += 1
        for r in c.get("replies") or []:
            if (r.get("text") or "").strip():
                n += 1
    return n


def merge_comment_files(files: list[Path], output_file: Path) -> int:
    merged = []
    for f in files:
        try:
            arr = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(arr, list):
            merged.extend(arr)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(merged)


def main():
    parser = argparse.ArgumentParser(description="Batch crawl Douyin comments from existing video ids")
    parser.add_argument("--dy-analyze-path", default=r"E:\dy_analyze")
    parser.add_argument("--info-root", default=r"E:\douyin\DouYin_Spider\dy_suno_mp3")
    parser.add_argument("--max-videos", type=int, default=20)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--reply-limit", type=int, default=20)
    parser.add_argument("--target-texts", type=int, default=2000)
    parser.add_argument("--merge-output", default=r"e:\dy_comments\datasets\comments_corpus.json")
    args = parser.parse_args()

    dy_analyze = Path(args.dy_analyze_path)
    script = dy_analyze / "douyin_crawler_server.js"
    if not script.exists():
        raise FileNotFoundError(f"not found: {script}")

    ids = find_video_ids(Path(args.info_root), args.max_videos * 4)
    if not ids:
        raise RuntimeError("no candidate video ids found")

    out_dir = Path(r"e:\dy_comments\datasets\batch_outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    collected_files: list[Path] = []
    total_texts = 0
    used_videos = 0

    for vid in ids:
        if used_videos >= args.max_videos or total_texts >= args.target_texts:
            break
        out_file = out_dir / f"douyin_comments_{vid}.json"
        cmd = [
            "node",
            str(script),
            vid,
            f"--limit={args.limit}",
            f"--reply-limit={args.reply_limit}",
            f"--output={out_file}",
        ]
        proc = subprocess.run(cmd, cwd=str(dy_analyze), capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"[skip] {vid} failed: {(proc.stderr or proc.stdout)[:120]}")
            continue
        if not out_file.exists():
            print(f"[skip] {vid} no output")
            continue
        n = count_texts(out_file)
        if n <= 0:
            print(f"[skip] {vid} empty")
            continue
        collected_files.append(out_file)
        used_videos += 1
        total_texts += n
        print(f"[ok] {vid} texts={n} total={total_texts}")

    merged_count = merge_comment_files(collected_files, Path(args.merge_output))
    print("used_videos", used_videos)
    print("total_texts", total_texts)
    print("files", len(collected_files))
    print("merged_comment_rows", merged_count)
    print("merged_output", args.merge_output)


if __name__ == "__main__":
    main()

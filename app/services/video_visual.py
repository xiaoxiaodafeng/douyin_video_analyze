from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.core.config import settings


class VideoVisualService:
    def __init__(self) -> None:
        self.python_exe = Path(settings.visual_python_exe)
        self.cache_dir = Path(settings.asr_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _video_dir(self, video_id: str) -> Path:
        target = self.cache_dir / video_id
        target.mkdir(parents=True, exist_ok=True)
        return target

    def analyze_video(self, video_id: str, mp4_path: str, force_refresh: bool = False) -> dict[str, Any]:
        video_dir = self._video_dir(video_id)
        out_json = video_dir / "visual_analysis.json"
        frames_dir = video_dir / "frames"
        if out_json.exists() and not force_refresh:
            return json.loads(out_json.read_text(encoding="utf-8"))

        if not self.python_exe.exists():
            raise RuntimeError(f"visual python not found: {self.python_exe}")
        if not Path(mp4_path).exists():
            raise RuntimeError(f"mp4 not found for visual analysis: {mp4_path}")

        cmd = [
            str(self.python_exe),
            "scripts/extract_video_visuals.py",
            "--video",
            str(mp4_path),
            "--output",
            str(out_json),
            "--frames-dir",
            str(frames_dir),
            "--max-frames",
            "6",
        ]
        proc = subprocess.run(cmd, cwd=str(Path.cwd()), capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "visual analysis failed")
        return json.loads(out_json.read_text(encoding="utf-8"))

    def read_cached_visual_analysis(self, video_id: str) -> dict[str, Any] | None:
        out_json = self._video_dir(video_id) / "visual_analysis.json"
        if not out_json.exists():
            return None
        try:
            return json.loads(out_json.read_text(encoding="utf-8"))
        except Exception:
            return None

    def frame_public_items(self, video_id: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = payload or self.read_cached_visual_analysis(video_id) or {}
        frames = list(payload.get("frames") or [])
        items: list[dict[str, Any]] = []
        for item in frames:
            image_path = Path(str(item.get("image_path") or ""))
            if not image_path.exists():
                continue
            items.append(
                {
                    "index": int(item.get("index") or 0),
                    "timestamp_sec": float(item.get("timestamp_sec") or 0),
                    "name": image_path.name,
                    "observation": str(item.get("observation") or ""),
                    "ocr_text": " | ".join(
                        str(row.get("text") or "")
                        for row in list(item.get("ocr_lines") or [])[:6]
                        if str(row.get("text") or "").strip()
                    ),
                }
            )
        return items


video_visual_service = VideoVisualService()

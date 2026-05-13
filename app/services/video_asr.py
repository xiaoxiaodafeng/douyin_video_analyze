from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests

from app.core.config import settings
from app.services.douyin_bridge import fetch_video_media_info


class VideoASRService:
    def __init__(self) -> None:
        self.asr_python = Path(settings.asr_python_exe)
        self.asr_model_dir = Path(settings.asr_model_dir)
        self.ffmpeg_exe = Path(settings.asr_ffmpeg_exe)
        self.cache_dir = Path(settings.asr_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _video_dir(self, video_id: str) -> Path:
        target = self.cache_dir / video_id
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _meta_file(self, video_id: str) -> Path:
        return self._video_dir(video_id) / "media_meta.json"

    def _mp4_file(self, video_id: str) -> Path:
        return self._video_dir(video_id) / f"{video_id}.mp4"

    def _wav_file(self, video_id: str) -> Path:
        return self._video_dir(video_id) / f"{video_id}.wav"

    def _transcript_file(self, video_id: str) -> Path:
        return self._video_dir(video_id) / "transcript.json"

    def _visual_file(self, video_id: str) -> Path:
        return self._video_dir(video_id) / "visual_analysis.json"

    def write_media_meta(self, video_id: str, media_meta: dict[str, Any]) -> None:
        self._meta_file(video_id).write_text(
            json.dumps(media_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_media_meta(self, video_id: str) -> dict[str, Any] | None:
        path = self._meta_file(video_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def import_local_mp4(self, video_id: str, source_path: str, overwrite: bool = True) -> dict[str, Any]:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"local mp4 not found: {source}")
        if source.suffix.lower() != ".mp4":
            raise RuntimeError("only .mp4 file is supported")

        target = self._mp4_file(video_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise RuntimeError(f"target mp4 already exists: {target}")
        shutil.copyfile(source, target)

        for stale in (self._wav_file(video_id), self._transcript_file(video_id), self._visual_file(video_id)):
            if stale.exists():
                stale.unlink()

        frames_dir = self._video_dir(video_id) / "frames"
        if frames_dir.exists():
            shutil.rmtree(frames_dir)

        meta = self.read_media_meta(video_id) or {}
        meta.update(
            {
                "video_id": video_id,
                "local_mp4_path": str(target),
                "media_url": str(meta.get("media_url") or ""),
                "play_url": str(meta.get("play_url") or ""),
            }
        )
        self.write_media_meta(video_id, meta)
        return {
            "video_id": video_id,
            "mp4_path": str(target),
            "size_bytes": target.stat().st_size,
            "source_path": str(source),
        }

    def _download_file(self, url: str, target: Path) -> None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            )
        }
        with requests.get(url, headers=headers, stream=True, timeout=60, verify=False) as resp:
            resp.raise_for_status()
            with open(target, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        if not target.exists() or target.stat().st_size <= 0:
            raise RuntimeError("video download failed or empty file")

    def _ensure_audio(self, video_id: str, media_url: str = "") -> tuple[Path, Path]:
        mp4_path = self._mp4_file(video_id)
        wav_path = self._wav_file(video_id)

        if not mp4_path.exists() or mp4_path.stat().st_size <= 0:
            if not media_url:
                raise RuntimeError("no local mp4 cached and unable to resolve video play url for ASR")
            self._download_file(media_url, mp4_path)

        if not self.ffmpeg_exe.exists():
            raise RuntimeError(f"ffmpeg not found: {self.ffmpeg_exe}")

        if not wav_path.exists() or wav_path.stat().st_size <= 0:
            cmd = [
                str(self.ffmpeg_exe),
                "-y",
                "-i",
                str(mp4_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-sample_fmt",
                "s16",
                str(wav_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr or proc.stdout or "ffmpeg extract audio failed")
        return mp4_path, wav_path

    def _run_asr(self, video_id: str, wav_path: Path) -> dict[str, Any]:
        if not self.asr_python.exists():
            raise RuntimeError(f"asr python not found: {self.asr_python}")
        if not self.asr_model_dir.exists():
            raise RuntimeError(f"asr model dir not found: {self.asr_model_dir}")

        out_json = self._transcript_file(video_id)
        cmd = [
            str(self.asr_python),
            "scripts/run_sensevoice_asr.py",
            "--audio",
            str(wav_path),
            "--model-dir",
            str(self.asr_model_dir),
            "--output",
            str(out_json),
        ]
        proc = subprocess.run(cmd, cwd=str(Path.cwd()), capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "sensevoice asr failed")
        if not out_json.exists():
            raise RuntimeError("transcript output not generated")
        return json.loads(out_json.read_text(encoding="utf-8"))

    def transcribe_video(self, video_id: str, force_refresh: bool = False) -> dict[str, Any]:
        out_json = self._transcript_file(video_id)
        if out_json.exists() and not force_refresh:
            return json.loads(out_json.read_text(encoding="utf-8"))

        media = self.read_media_meta(video_id) or {}
        media_url = str(media.get("media_url") or "").strip()
        mp4_path = self._mp4_file(video_id)
        mp4_exists = mp4_path.exists() and mp4_path.stat().st_size > 0

        if not media_url and not mp4_exists:
            remote_media = fetch_video_media_info(video_id)
            if remote_media:
                media = remote_media
                media_url = str(media.get("media_url") or "").strip()
                self.write_media_meta(video_id, remote_media)

        mp4_path, wav_path = self._ensure_audio(video_id, media_url)
        payload = self._run_asr(video_id, wav_path)
        payload["video_id"] = video_id
        payload["media_url"] = media_url
        payload["mp4_path"] = str(mp4_path)
        payload["wav_path"] = str(wav_path)
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def read_cached_transcript(self, video_id: str) -> dict[str, Any] | None:
        out_json = self._transcript_file(video_id)
        if not out_json.exists():
            return None
        try:
            return json.loads(out_json.read_text(encoding="utf-8"))
        except Exception:
            return None

    def media_diagnostics(self, video_id: str) -> dict[str, Any]:
        video_dir = self._video_dir(video_id)
        mp4_path = self._mp4_file(video_id)
        wav_path = self._wav_file(video_id)
        transcript_path = self._transcript_file(video_id)
        visual_path = self._visual_file(video_id)
        meta = self.read_media_meta(video_id) or {}
        media_url = str(meta.get("media_url") or "").strip()

        media_url_host = ""
        if media_url.startswith("http"):
            parts = media_url.split("/")
            if len(parts) >= 3:
                media_url_host = parts[2]

        return {
            "video_id": video_id,
            "video_dir": str(video_dir.resolve()),
            "has_media_meta": bool(meta),
            "has_media_url": bool(media_url),
            "has_play_url": bool(str(meta.get("play_url") or "").strip()),
            "media_url_host": media_url_host,
            "has_local_mp4": mp4_path.exists() and mp4_path.stat().st_size > 0,
            "mp4_path": str(mp4_path),
            "mp4_size_bytes": mp4_path.stat().st_size if mp4_path.exists() else 0,
            "has_wav": wav_path.exists() and wav_path.stat().st_size > 0,
            "wav_path": str(wav_path),
            "has_transcript": transcript_path.exists() and transcript_path.stat().st_size > 0,
            "transcript_path": str(transcript_path),
            "has_visual_analysis": visual_path.exists() and visual_path.stat().st_size > 0,
            "visual_analysis_path": str(visual_path),
            "local_mp4_path_from_meta": str(meta.get("local_mp4_path") or ""),
        }

    def summarize_transcript(self, transcript: str) -> str:
        text = str(transcript or "").strip()
        if not text:
            return "暂无视频语音转写内容。"
        pieces = [part.strip() for part in text.replace("\r", "\n").split("\n") if part.strip()]
        if not pieces:
            return "暂无视频语音转写内容。"
        preview = pieces[0][:120]
        return f"视频语音内容主要集中在：{preview}"

    def build_key_clips(self, transcript: str, clip_len: int = 36, max_items: int = 5) -> list[str]:
        text = str(transcript or "").strip()
        if not text:
            return []
        normalized = text.replace("\r", "\n")
        chunks = [part.strip(" \n\t-") for part in normalized.split("\n") if part.strip()]
        if not chunks:
            chunks = [text]
        result: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            candidate = chunk[:clip_len].strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            result.append(candidate)
            if len(result) >= max_items:
                break
        return result

    def explain_transcript_error(self, error: str) -> str:
        text = str(error or "").strip()
        if not text:
            return ""
        if "WinError 10013" in text:
            return "当前环境访问抖音视频直链被系统拦截，导致 mp4 无法直接下载。可先导入本地 mp4，再继续语音转写和视频内容分析。"
        if "unable to resolve video play url" in text or "no local mp4 cached" in text:
            return "当前既没有可用的抖音播放直链，也没有本地缓存 mp4。请先重新查询视频，或先导入本地 mp4。"
        if "ffmpeg not found" in text:
            return "本地 ffmpeg 未找到，无法从视频中提取音频。"
        if "asr python not found" in text:
            return "ASR 独立环境未找到，无法执行本地转写。"
        if "asr model dir not found" in text:
            return "SenseVoiceSmall 模型目录未找到，无法执行本地转写。"
        return text

    def get_cached_mp4_path(self, video_id: str) -> str:
        mp4_path = self._mp4_file(video_id)
        return str(mp4_path) if mp4_path.exists() else ""


video_asr_service = VideoASRService()

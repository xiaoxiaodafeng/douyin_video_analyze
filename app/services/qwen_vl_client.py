from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

import requests

from app.core.config import settings


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


class QwenVLService:
    def __init__(self) -> None:
        self.api_key = settings.qwen_vl_api_key.strip()
        self.base_url = settings.qwen_vl_base_url.rstrip("/")
        self.model = settings.qwen_vl_model.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post_json(self, payload: dict[str, Any]) -> str:
        if not self.enabled:
            return ""
        url = f"{self.base_url}/chat/completions"
        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                data=json.dumps(payload, ensure_ascii=False),
                timeout=120,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception:
            return ""

    def _image_to_data_url(self, image_path: str) -> str:
        path = Path(image_path)
        if not path.exists():
            return ""
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime};base64,{encoded}"

    def analyze_video(
        self,
        video_meta: dict[str, Any],
        transcript: str = "",
        transcript_summary: str = "",
        key_clips: list[str] | None = None,
        visual_summary: str = "",
        visual_frames: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        visual_frames = visual_frames or []
        key_clips = key_clips or []

        limited_frames = list(visual_frames[: settings.qwen_vl_max_frames])
        frames_text = "\n".join(
            [
                (
                    f"- 帧{idx + 1} @{_safe_text(item.get('timestamp_sec'), '0')}s | "
                    f"画面观察：{_safe_text(item.get('observation'), '暂无')} | "
                    f"OCR：{_safe_text(item.get('ocr_text'), '暂无')}"
                )
                for idx, item in enumerate(limited_frames)
            ]
        )
        clips_text = "\n".join(f"- {item}" for item in key_clips[:5]) or "- 暂无关键片段"
        transcript_text = transcript[:3000] if transcript else "暂无视频语音转写"
        prompt = (
            "你是一名中文短视频理解助手。请基于这些关键帧、OCR、语音转写和视频信息，先理解视频内容，"
            "然后只输出一个 JSON 对象，不要输出 markdown，不要输出解释。"
            "\n\n"
            "JSON 字段必须包含：video_topic, content_type, target_audience, hook_analysis, "
            "timeline_summary, highlight_clips, visual_style, speech_and_copy, risk_points, reusable_patterns。"
            "\n\n"
            "字段要求：\n"
            "- video_topic: 一句话概括主题\n"
            "- content_type: 剧情型/口播型/记录型/才艺型/干货型/混合型 之一\n"
            "- target_audience: 核心受众判断\n"
            "- hook_analysis: 开头3秒钩子判断\n"
            "- timeline_summary: 2到5条数组\n"
            "- highlight_clips: 1到4条数组，每条包含 time/summary/reason\n"
            "- visual_style: 画面风格总结\n"
            "- speech_and_copy: 口播和字幕亮点总结\n"
            "- risk_points: 1到4条数组\n"
            "- reusable_patterns: 1到4条数组\n"
            "\n\n"
            f"视频基础信息：{video_meta}\n"
            f"视频语音转写全文：{transcript_text}\n"
            f"视频语音摘要：{transcript_summary or '暂无摘要'}\n"
            f"视频关键片段：\n{clips_text}\n"
            f"画面风格摘要：{visual_summary or '暂无画面风格摘要'}\n"
            f"关键帧观察与 OCR：\n{frames_text or '- 暂无关键帧信息'}\n"
        )

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for item in limited_frames:
            data_url = self._image_to_data_url(str(item.get("image_path") or ""))
            if not data_url:
                continue
            content.append({"type": "image_url", "image_url": {"url": data_url}})

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一个严谨的中文视频理解助手，只返回 JSON。"},
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
        }
        raw = self._post_json(payload)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return self.build_local_fallback(
            video_meta=video_meta,
            transcript=transcript,
            transcript_summary=transcript_summary,
            key_clips=key_clips,
            visual_summary=visual_summary,
            visual_frames=visual_frames,
        )

    def build_local_fallback(
        self,
        video_meta: dict[str, Any],
        transcript: str = "",
        transcript_summary: str = "",
        key_clips: list[str] | None = None,
        visual_summary: str = "",
        visual_frames: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        key_clips = key_clips or []
        visual_frames = visual_frames or []
        title = _safe_text(video_meta.get("title"), "当前视频")
        desc = _safe_text(video_meta.get("desc"))
        transcript_line = _safe_text(transcript[:120], "暂无视频语音转写")
        first_clip = key_clips[0] if key_clips else "暂无关键片段"
        first_frame = visual_frames[0] if visual_frames else {}
        first_frame_text = _safe_text(first_frame.get("observation"), "暂无关键帧观察")
        first_ocr_text = _safe_text(first_frame.get("ocr_text"), "暂无 OCR")

        return {
            "video_topic": title[:60],
            "content_type": "混合型",
            "target_audience": "基于现有内容推断，面向对该主题感兴趣的泛短视频用户。",
            "hook_analysis": f"开头更可能通过“{first_clip}”或首帧信息建立停留理由，需结合真实播放数据继续验证。",
            "timeline_summary": [
                f"开场围绕“{title[:26]}”快速建立主题。",
                f"中段通过语音内容“{transcript_line}”继续传递核心信息。",
                f"画面层面当前可见信息为“{first_frame_text}”，OCR 重点为“{first_ocr_text}”。",
                f"整体画面风格表现为：{visual_summary or '暂无画面风格摘要'}。",
            ],
            "highlight_clips": [
                {
                    "time": "开头片段",
                    "summary": first_clip,
                    "reason": "更容易承担开场钩子或核心信息承接作用。",
                }
            ],
            "visual_style": visual_summary or "暂无画面风格摘要。",
            "speech_and_copy": transcript_summary or transcript_line or desc or "暂无可用语音与字幕结论。",
            "risk_points": [
                "当前为本地兜底视频理解，缺少更细的镜头级时序判断。",
                "如果语音、字幕和画面不完全一致，可能影响复盘准确性。",
            ],
            "reusable_patterns": [
                "同类内容可优先强化开场钩子，再展开中段信息。",
                "若 OCR/字幕有记忆点，建议提前前置以提升停留。",
            ],
        }


qwen_vl_service = QwenVLService()

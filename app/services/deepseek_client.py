from __future__ import annotations

import json
from typing import Any

import requests

from app.core.config import settings


class DeepSeekService:
    def __init__(self) -> None:
        self.api_key = settings.deepseek_api_key.strip()
        self.base_url = settings.deepseek_base_url.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, model: str, prompt: str) -> str:
        if not self.enabled:
            return ""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是短视频评论分析助手。请输出简洁、可执行、结构化建议。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        try:
            resp = requests.post(url, headers=self._headers(), data=json.dumps(payload), timeout=120)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            message = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
            content = str(message.get("content") or "").strip()
            reasoning = str(message.get("reasoning_content") or "").strip()
            if content:
                return content
            if reasoning:
                return reasoning
            return ""
        except Exception:
            return ""

    def analyze_video_content(
        self,
        video_meta: dict[str, Any],
        qwen_insight: dict[str, Any] | None = None,
        sentiment_counter: dict[str, Any] | None = None,
        keyword_stats: list[dict[str, Any]] | None = None,
        top_comments: list[str] | None = None,
        comment_summary: str = "",
        transcript: str = "",
        transcript_summary: str = "",
        key_clips: list[str] | None = None,
        visual_summary: str = "",
        visual_frames: list[dict[str, Any]] | None = None,
    ) -> str:
        sentiment_counter = sentiment_counter or {}
        keyword_stats = keyword_stats or []
        top_comments = top_comments or []
        key_clips = key_clips or []
        visual_frames = visual_frames or []
        qwen_insight = qwen_insight or {}
        kw_text = "、".join(str(item.get("keyword") or "") for item in keyword_stats[:10] if item.get("keyword"))
        top_comment_text = "\n".join(f"- {c}" for c in top_comments[:5])
        clip_text = "\n".join(f"- {c}" for c in key_clips[:5])
        qwen_text = json.dumps(qwen_insight, ensure_ascii=False, indent=2) if qwen_insight else "暂无 Qwen 视频理解结果"
        ocr_summary_rows: list[str] = []
        for idx, item in enumerate(visual_frames[:6]):
            ocr_lines = list(item.get("ocr_lines") or [])
            ocr_texts = [str(row.get("text") or "").strip() for row in ocr_lines if str(row.get("text") or "").strip()]
            if not ocr_texts and item.get("ocr_text"):
                ocr_texts = [str(item.get("ocr_text") or "").strip()]
            if ocr_texts:
                ocr_summary_rows.append(f"- 第{idx + 1}帧 @{str(item.get('timestamp_sec', '0'))}s: {'；'.join(ocr_texts[:6])}")
        frame_text = "\n".join(
            (
                f"- 第{idx + 1}帧 @{str(item.get('timestamp_sec', '0'))}s: "
                f"{str(item.get('observation') or '').strip() or ('亮度 ' + str(item.get('metrics', {}).get('brightness', '-')))}"
            )
            for idx, item in enumerate(visual_frames[:6])
        )
        ocr_text = "\n".join(ocr_summary_rows)
        total_comments = int(sum(int(sentiment_counter.get(k) or 0) for k in ("Positive", "Neutral", "Negative")))
        prompt = (
            "你是一名资深短视频内容策略顾问。"
            "这一次你只负责输出“视频内容复盘”，不要重复评论总结里的内容，不要重复运营建议里的执行动作。"
            "你的重点是解释这条视频本身为什么成立、爆点来自哪里、内容结构哪里强哪里弱。\n"
            "\n"
            "你必须综合以下信息进行判断：\n"
            f"视频基础信息: {video_meta}\n"
            f"Qwen 视频理解结果:\n{qwen_text}\n"
            f"视频画面风格摘要: {visual_summary or '暂无画面风格摘要'}\n"
            f"关键帧画面指标:\n{frame_text or '- 暂无关键帧信息'}\n"
            f"关键帧 OCR/字幕/画面文字:\n{ocr_text or '- 暂无画面文字识别结果'}\n"
            f"视频语音转写全文: {transcript[:2500] if transcript else '暂无视频语音文本'}\n"
            f"视频语音摘要: {transcript_summary or '暂无摘要'}\n"
            f"视频关键片段:\n{clip_text or '- 暂无关键片段'}\n"
            f"评论总量: {total_comments}\n"
            f"评论情绪分布: {sentiment_counter}\n"
            f"评论高频关键词: {kw_text or '暂无关键词'}\n"
            f"评论总结: {comment_summary or '暂无评论总结'}\n"
            f"高赞评论样本:\n{top_comment_text or '- 暂无高赞评论'}\n"
            "\n"
            "请严格按下面 6 个部分输出，每个部分都要具体，贴近抖音运营：\n"
            "1. 内容定位复盘\n"
            "要求：判断这是剧情型、观点型、才艺型、干货型、情绪共鸣型还是混合型内容；说明核心受众是谁，用户为什么会停留。\n"
            "\n"
            "2. 爆点拆解\n"
            "要求：拆出 3-5 个最可能促成播放、点赞、评论或转发的爆点，重点分析开场钩子、情绪张力、反差感、金句、节奏、话题性。"
            "如果画面中有字幕、封面文案、歌词、标题条、身份介绍、价格信息、角色名或剧情提示，要判断这些文字是否构成停留钩子。\n"
            "\n"
            "3. 内容与评论的耦合点\n"
            "要求：只说明“视频内容的哪一部分”触发了评论区反馈，帮助理解内容机制；不要再重复一整段评论总结。\n"
            "\n"
            "4. 风险与短板\n"
            "要求：指出内容可能存在的表达重复、信息不清、情绪过满、争议点放大、标题封面错配、转化链路不足等问题。"
            "如果语音内容、画面文字、评论区理解之间有错位，也要明确指出。\n"
            "\n"
            "5. 内容层优化方向\n"
            "要求：只讲内容本身应该如何优化，例如结构、节奏、钩子、信息密度、字幕文案、画面调度。"
            "不要写成运营动作清单，不要展开评论区互动建议。\n"
            "\n"
            "6. 可复用爆点结论\n"
            "要求：最后单独输出 3 条可复用的方法论，格式尽量像：'如果是XX类内容，下次优先保留XX，放大XX，避免XX'。\n"
            "\n"
            "整体要求：\n"
            "- 语言务必像真实运营复盘，不要空话。\n"
            "- 不要把“AI 评论总结”里的内容大段重写一遍。\n"
            "- 不要把“AI 运营建议”写成待办清单式重复内容。\n"
            "- 如果信息不足，要明确说“基于现有评论/转写推断”。\n"
            "- 适当引用视频语音内容、关键片段、OCR 文字和评论现象来支撑判断。\n"
            "- 如果 OCR 文字像歌词、台词、封面文案或话题标签，要结合它判断视频节奏和记忆点。\n"
            "- 输出要有洞察，不要只做摘要。"
        )
        return self._post(settings.deepseek_reasoner_model, prompt)

    def summarize_comments(
        self,
        comments: list[str],
        video_meta: dict[str, Any] | None = None,
        sentiment_counter: dict[str, Any] | None = None,
        keyword_stats: list[dict[str, Any]] | None = None,
    ) -> str:
        if not comments:
            return "暂无评论可总结。"
        sample = comments[:100]
        video_meta = video_meta or {}
        sentiment_counter = sentiment_counter or {}
        keyword_stats = keyword_stats or []
        kw_text = "、".join(str(item.get("keyword") or "") for item in keyword_stats[:12] if item.get("keyword"))
        prompt = (
            "你是一名短视频运营复盘分析师。"
            "这一次你只负责输出“评论区结论总结”，不要给运营动作建议，不要分析视频内容结构本身。"
            "重点是把评论区发生了什么讲清楚。\n"
            "\n"
            "你必须参考以下信息：\n"
            f"视频标题: {video_meta.get('title', '')}\n"
            f"视频描述: {video_meta.get('desc', '')}\n"
            f"作者: {video_meta.get('author_name', '')}\n"
            f"情绪分布: {sentiment_counter}\n"
            f"高频关键词: {kw_text or '暂无关键词'}\n"
            "评论样本:\n"
            + "\n".join(f"- {c}" for c in sample)
            + "\n\n"
            + "请严格输出以下 5 个部分：\n"
            + "1. 整体评论氛围\n"
            + "要求：判断评论区总体是认可、围观、争议、吐槽还是混合状态，并说明原因。\n"
            + "\n"
            + "2. 用户最买单的点\n"
            + "要求：总结用户最认可、最容易点赞或共鸣的内容点，尽量指出具体表达、设定、情绪或桥段。\n"
            + "\n"
            + "3. 用户最关注的讨论点\n"
            + "要求：提炼评论区里最反复出现的话题、问题或观点，尽量结合关键词说明。\n"
            + "\n"
            + "4. 负面反馈与风险点\n"
            + "要求：指出用户吐槽、质疑、不满或可能放大争议的地方；如果负面不明显，也要说明当前主要隐患。\n"
            + "\n"
            + "5. 对运营有价值的结论\n"
            + "要求：最后总结 3-5 条最值得拿去指导后续内容或互动策略的结论，写得像复盘结论，不要空话。\n"
            "\n"
            "整体要求：\n"
            "- 输出要像复盘结论，不要像普通摘要。\n"
            "- 尽量引用评论现象来支撑判断。\n"
            "- 不要写“下一条怎么拍”“标题怎么改”“评论区怎么运营”这类动作建议。\n"
            "- 不要展开视频内容结构、镜头语言、爆点机制分析。\n"
            "- 如果信息不足，要明确说“基于现有评论推断”。\n"
            "- 语言简洁但要有洞察。"
        )
        result = self._post(settings.deepseek_chat_model, prompt)
        if result:
            return result
        return ""

    def generate_suggestion(
        self,
        video_meta: dict[str, Any],
        comment_summary: str,
        warning: dict[str, Any],
        keyword_stats: list[dict[str, Any]] | None = None,
        top_comments: list[str] | None = None,
    ) -> str:
        keyword_stats = keyword_stats or []
        top_comments = top_comments or []
        kw_text = "、".join(str(item.get("keyword") or "") for item in keyword_stats[:10] if item.get("keyword"))
        comment_text = "\n".join(f"- {c}" for c in top_comments[:5])
        total_comments = len(top_comments)
        prompt = (
            "你是一名资深短视频运营负责人。"
            "这一次你只负责输出“运营动作建议”，不要重复评论总结，不要重复视频内容复盘。"
            "请直接告诉我下一步要做什么。\n"
            "\n"
            "你必须参考以下信息：\n"
            f"视频信息: {video_meta}\n"
            f"评论总结: {comment_summary or '暂无评论总结'}\n"
            f"舆情预警: {warning}\n"
            f"高频关键词: {kw_text or '暂无关键词'}\n"
            f"高赞评论样本（{total_comments} 条）:\n{comment_text or '- 暂无高赞评论'}\n"
            "\n"
            "请严格输出以下 6 个部分：\n"
            "1. 内容方向建议\n"
            "要求：判断这条内容接下来应该继续放大什么，不该继续重复什么，是否适合做系列化。\n"
            "\n"
            "2. 下一条视频建议\n"
            "要求：直接给出下一条视频应该怎么拍，最好包含角度、表达方式、情绪调性或结构建议。\n"
            "\n"
            "3. 标题与封面建议\n"
            "要求：指出标题和封面应该强化什么信息，应该突出反差、情绪、结果还是观点。\n"
            "\n"
            "4. 评论区互动建议\n"
            "要求：说明置顶评论怎么写、应该回应哪类高赞评论、如何放大二级讨论。\n"
            "\n"
            "5. 风险处理建议\n"
            "要求：如果有负面情绪、敏感词或争议点，要告诉我如何在评论区或后续视频里处理；如果没有明显风险，也要说明当前主要风险预防点。\n"
            "\n"
            "6. 最终执行清单\n"
            "要求：最后单独列出 5 条短句式待办，每条都要像可立刻执行的动作，例如“下一条开头 3 秒直接抛出XX问题”。\n"
            "\n"
            "整体要求：\n"
            "- 语言风格像真实运营复盘会后的执行建议。\n"
            "- 建议必须具体，避免“持续优化”“加强互动”这种空话。\n"
            "- 不要大段复述评论区现象，只在必要时引用作为依据。\n"
            "- 不要重写视频内容复盘里的爆点分析和结构分析。\n"
            "- 尽量结合评论关键词、高赞评论和视频数据表现来判断。\n"
            "- 如果信息不足，可以明确说明“基于现有评论推断”。"
        )
        result = self._post(settings.deepseek_reasoner_model, prompt)
        if result:
            return result
        return ""


deepseek_service = DeepSeekService()

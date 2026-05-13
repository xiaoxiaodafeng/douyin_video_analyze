from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import jieba
import numpy as np
from sklearn.cluster import KMeans

from app.core.config import settings
from app.services.sentiment_model import sentiment_service


STOPWORDS = {
    "的", "了", "是", "我", "你", "他", "她", "它", "和", "就", "都", "也", "很", "在", "不", "有", "这", "那", "啊", "呢", "吗", "吧",
}
POS_WORDS = {"好", "喜欢", "支持", "优秀", "不错", "推荐", "赞", "爱", "棒", "满意", "舒服", "真实", "有用"}
NEG_WORDS = {"差", "讨厌", "垃圾", "失望", "坑人", "骗", "假", "慢", "贵", "离谱", "难用", "无语", "生气", "糟糕"}


@dataclass
class CommentAnalysis:
    comment_id: str
    sentiment: str
    keywords: list[str]
    topic: str
    summary: str
    suggestion: str


def tokenize(text: str) -> list[str]:
    words = [w.strip().lower() for w in jieba.cut(text) if w.strip()]
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def top_keywords(texts: Iterable[str], top_n: int = 50) -> list[str]:
    counter = Counter()
    for t in texts:
        counter.update(tokenize(t))
    return [k for k, _ in counter.most_common(top_n)]


def top_keywords_with_counts(texts: Iterable[str], top_n: int = 50) -> list[dict[str, int | str]]:
    counter = Counter()
    for t in texts:
        counter.update(tokenize(t))
    return [{"keyword": k, "count": int(v)} for k, v in counter.most_common(top_n)]


def rule_sentiment(text: str) -> str:
    words = tokenize(text)
    if not words:
        return "Neutral"
    pos = sum(1 for w in words if w in POS_WORDS)
    neg = sum(1 for w in words if w in NEG_WORDS)
    if pos > neg:
        return "Positive"
    if neg > pos:
        return "Negative"
    return "Neutral"


def sentiment(text: str) -> str:
    ml = sentiment_service.classify(text)
    if ml is not None:
        return ml.label
    return rule_sentiment(text)


def simple_topic(words: list[str]) -> str:
    if not words:
        return "其他"
    return words[0]


def cluster_topics(texts: list[str], k: int | None = None) -> list[int]:
    # Using simple bag-of-words vectors to avoid heavyweight dependencies for MVP.
    vocab = top_keywords(texts, top_n=200)
    if not vocab or len(texts) < 2:
        return [0] * len(texts)
    word_idx = {w: i for i, w in enumerate(vocab)}
    mat = np.zeros((len(texts), len(vocab)), dtype=np.float32)
    for i, text in enumerate(texts):
        for w in tokenize(text):
            j = word_idx.get(w)
            if j is not None:
                mat[i, j] += 1

    cluster_count = k or settings.topic_cluster_count
    cluster_count = max(1, min(cluster_count, len(texts)))
    if cluster_count == 1:
        return [0] * len(texts)

    model = KMeans(n_clusters=cluster_count, random_state=42, n_init=10)
    labels = model.fit_predict(mat)
    return labels.tolist()


def behavior_stats(comment_times: list[datetime | None]) -> dict:
    hour_counter = Counter()
    for t in comment_times:
        if t:
            hour_counter[t.hour] += 1
    peak_hour = None
    peak_count = 0
    for h, c in hour_counter.items():
        if c > peak_count:
            peak_hour = h
            peak_count = c
    return {
        "active_hours": dict(sorted(hour_counter.items())),
        "peak_hour": peak_hour,
        "peak_count": peak_count,
    }


def sentiment_warning(sentiments: list[str], comments: list[str]) -> dict:
    total = len(sentiments)
    neg = sentiments.count("Negative")
    neg_ratio = (neg / total) if total else 0

    sensitive_words = [w.strip() for w in settings.sensitive_keywords.split(",") if w.strip()]
    hits = 0
    for c in comments:
        if any(w in c for w in sensitive_words):
            hits += 1
    sensitive_ratio = (hits / len(comments)) if comments else 0

    warning = neg_ratio >= 0.35 or sensitive_ratio >= 0.1
    return {
        "warning": warning,
        "negative_ratio": round(neg_ratio, 4),
        "sensitive_ratio": round(sensitive_ratio, 4),
        "negative_count": neg,
        "sensitive_count": hits,
    }


def build_local_comment_summary(
    video_meta: dict,
    comments: list[str],
    sentiments: list[str],
    keyword_stats: list[dict[str, int | str]],
) -> str:
    if not comments:
        return "暂无评论可总结。"

    total = len(comments)
    pos = sentiments.count("Positive")
    neu = sentiments.count("Neutral")
    neg = sentiments.count("Negative")
    title = str(video_meta.get("title") or "当前视频")
    keywords = [str(item.get("keyword") or "") for item in keyword_stats[:8] if item.get("keyword")]

    lines = [
        f"1. 当前视频主题围绕“{title[:28]}”，已累计分析 {total} 条评论，整体讨论热度较高。",
        f"2. 情绪分布上，正向 {pos} 条、中性 {neu} 条、负向 {neg} 条，当前评论整体以{'认可/围观' if pos + neu >= neg else '争议反馈'}为主。",
    ]
    if keywords:
        lines.append(f"3. 高频讨论词主要集中在：{'、'.join(keywords[:6])}，说明用户关注点较为明确。")

    pos_samples = [c for c, s in zip(comments, sentiments) if s == "Positive"][:2]
    neg_samples = [c for c, s in zip(comments, sentiments) if s == "Negative"][:2]
    if pos_samples:
        lines.append(f"4. 正向反馈中常见的表达有：{'；'.join(x[:28] for x in pos_samples)}。")
    if neg_samples:
        lines.append(f"5. 负向反馈主要集中在：{'；'.join(x[:28] for x in neg_samples)}。")
    else:
        lines.append("5. 暂未出现集中的强负面槽点，适合继续放大当前内容亮点。")
    return "\n".join(lines[:5])


def build_local_ops_suggestion(
    video_meta: dict,
    warning: dict,
    keyword_stats: list[dict[str, int | str]],
    top_comments: list[str],
) -> str:
    title = str(video_meta.get("title") or "当前视频")
    keywords = [str(item.get("keyword") or "") for item in keyword_stats[:5] if item.get("keyword")]
    hot_terms = "、".join(keywords) if keywords else "评论高频关注点"
    hot_comment = top_comments[0][:32] if top_comments else "当前高赞评论"
    warning_text = "优先处理负面高频问题，并尽快在评论区或后续视频中回应。" if warning.get("warning") else "当前舆情整体稳定，可以继续放大有效表达。"

    return "\n".join(
        [
            f"1. 围绕“{title[:26]}”继续做系列化内容，把当前视频里最有效的表达方式复用到后续选题。",
            f"2. 下一条内容建议优先承接评论区的高频讨论点：{hot_terms}，提高连续观看与追更意愿。",
            f"3. 置顶评论可直接回应“{hot_comment}”这类高赞观点，主动放大二级互动。",
            f"4. {warning_text}",
            "5. 把高赞评论中的用户原话沉淀到标题、封面和开场钩子里，提升内容共鸣感。",
        ]
    )


def build_local_video_insight(
    video_meta: dict,
    sentiment_counter: dict,
    keyword_stats: list[dict[str, int | str]],
    top_comments: list[str],
    transcript: str = "",
    transcript_summary: str = "",
    key_clips: list[str] | None = None,
    visual_summary: str = "",
    qwen_insight: dict | None = None,
) -> str:
    qwen_insight = qwen_insight or {}
    title = str(video_meta.get("title") or "")
    desc = str(video_meta.get("desc") or "")
    author = str(video_meta.get("author_name") or "")
    pos = int(sentiment_counter.get("Positive") or 0)
    neu = int(sentiment_counter.get("Neutral") or 0)
    neg = int(sentiment_counter.get("Negative") or 0)
    keywords = [str(item.get("keyword") or "") for item in keyword_stats[:6] if item.get("keyword")]
    top_line = top_comments[0][:36] if top_comments else "当前高赞评论反馈"
    transcript_line = transcript[:120] if transcript else "暂无视频语音转写文本"
    transcript_summary = transcript_summary or "暂无摘要"
    key_clips = key_clips or []
    clip_text = "；".join(key_clips[:3]) if key_clips else "暂无关键片段"
    visual_summary = visual_summary or "暂无画面风格信息"
    qwen_topic = str(qwen_insight.get("video_topic") or "").strip()
    qwen_type = str(qwen_insight.get("content_type") or "").strip()
    qwen_hook = str(qwen_insight.get("hook_analysis") or "").strip()
    qwen_style = str(qwen_insight.get("visual_style") or "").strip()
    qwen_speech = str(qwen_insight.get("speech_and_copy") or "").strip()
    qwen_timeline = list(qwen_insight.get("timeline_summary") or [])
    qwen_risks = list(qwen_insight.get("risk_points") or [])
    qwen_patterns = list(qwen_insight.get("reusable_patterns") or [])

    positioning = qwen_topic or f"该视频由“{author}”发布，主题集中在“{title[:30]}”，描述内容为“{desc[:40]}”。"
    type_text = f"内容类型倾向于“{qwen_type}”。" if qwen_type else "内容类型仍需结合更多样本进一步判断。"
    hook_text = qwen_hook or "开头钩子信息暂不充分，建议重点复盘前 3 秒的停留理由。"
    timeline_text = "；".join(str(item) for item in qwen_timeline[:3] if str(item).strip()) or "暂无清晰的时间线总结。"
    risks_text = "；".join(str(item) for item in qwen_risks[:3] if str(item).strip()) or "当前未识别到明确风险点，但仍建议结合播放/完播数据复核。"
    patterns_text = "；".join(str(item) for item in qwen_patterns[:3] if str(item).strip()) or "可优先强化当前有效表达，再逐步沉淀成系列化方法。"
    speech_text = qwen_speech or transcript_summary
    merged_visual_style = qwen_style or visual_summary
    return "\n".join(
        [
            f"1. 视频内容定位：{positioning} {type_text}",
            f"2. 内容亮点：开头钩子方面，{hook_text}；评论正向 {pos} 条、中性 {neu} 条，当前高频讨论集中在 {('、'.join(keywords) if keywords else '核心内容表达')}；画面风格上 {merged_visual_style}",
            f"3. 内容推进与风险：视频时间线可概括为 {timeline_text}；当前负向评论 {neg} 条，潜在问题包括：{risks_text}",
            f"4. 视频语音内容参考：{transcript_line}。",
            f"5. 视频语音摘要：{speech_text}；关键片段参考：{clip_text}。",
            f"6. 后续优化方向：建议围绕高赞反馈“{top_line}”继续延展选题，把当前视频的核心亮点拆成系列内容，并在标题和开场中强化最能激发评论的表达；可复用方法包括：{patterns_text}",
        ]
    )

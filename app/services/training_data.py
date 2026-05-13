from __future__ import annotations

import csv
import random
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisResult, CommentInfo
from app.services.analyzer import rule_sentiment


LABEL_MAP = {"Negative": 0, "Neutral": 1, "Positive": 2}


def _norm_label(label: str) -> str:
    v = (label or "").strip().capitalize()
    if v in {"Positive", "Neutral", "Negative"}:
        return v
    return "Neutral"


def _read_manual_csv(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            text = (r.get("text") or "").strip()
            label = _norm_label(r.get("label") or "")
            if text:
                out.append({"text": text, "label": label, "label_id": LABEL_MAP[label]})
    return out


def build_trainset(
    db: Session,
    output_csv: str,
    video_id: str | None = None,
    sample_size: int = 1000,
    strategy: str = "weak_label",
    manual_csv: str | None = None,
) -> dict:
    stmt = select(CommentInfo)
    if video_id:
        stmt = stmt.where(CommentInfo.video_id == video_id)

    comments = db.execute(stmt).scalars().all()
    rows = []
    for c in comments:
        text = (c.content or "").strip()
        if text:
            rows.append({"comment_id": c.comment_id, "text": text})

    random.shuffle(rows)
    rows = rows[:sample_size]

    labeled = []

    if strategy in {"manual_only", "hybrid"} and manual_csv:
        labeled.extend(_read_manual_csv(Path(manual_csv)))

    if strategy in {"weak_label", "hybrid"}:
        analysis_stmt = select(AnalysisResult.comment_id, AnalysisResult.sentiment)
        if video_id:
            analysis_stmt = (
                select(AnalysisResult.comment_id, AnalysisResult.sentiment)
                .join(CommentInfo, AnalysisResult.comment_id == CommentInfo.comment_id)
                .where(CommentInfo.video_id == video_id)
            )

        existing = {cid: _norm_label(sent) for cid, sent in db.execute(analysis_stmt).all()}

        for r in rows:
            text = r["text"]
            label = existing.get(r["comment_id"]) or rule_sentiment(text)
            label = _norm_label(label)
            labeled.append({"text": text, "label": label, "label_id": LABEL_MAP[label]})

    uniq = {}
    for r in labeled:
        uniq[r["text"]] = r
    final_rows = list(uniq.values())
    random.shuffle(final_rows)

    out = Path(output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["text", "label", "label_id"])
        writer.writeheader()
        writer.writerows(final_rows)

    label_dist = {"Negative": 0, "Neutral": 0, "Positive": 0}
    for r in final_rows:
        label_dist[r["label"]] += 1

    return {
        "output_csv": str(out.resolve()),
        "rows": len(final_rows),
        "strategy": strategy,
        "label_distribution": label_dist,
    }

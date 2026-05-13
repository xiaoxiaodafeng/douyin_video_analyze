from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

from app.core.config import settings


@dataclass
class SentimentOutput:
    label: str
    score: float


DEFAULT_LABEL_MAP = {
    "0": "Negative",
    "1": "Neutral",
    "2": "Positive",
}


class SentimentService:
    def __init__(self) -> None:
        self._pipe = None
        self._ready = False
        self._model_name = ""
        self._id2label: dict[str, str] = DEFAULT_LABEL_MAP.copy()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def id2label(self) -> dict[str, str]:
        return self._id2label

    def reset(self) -> None:
        self._pipe = None
        self._ready = False
        self._model_name = ""
        self._id2label = DEFAULT_LABEL_MAP.copy()

    def _load_id2label(self, model_dir: Path) -> None:
        cfg = model_dir / "config.json"
        if not cfg.exists():
            return
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            raw = data.get("id2label") or {}
            mapped = {}
            for k, v in raw.items():
                ks = str(k)
                vv = str(v)
                if vv in {"Negative", "Neutral", "Positive"}:
                    mapped[ks] = vv
                elif vv.upper() in {"LABEL_0", "LABEL_1", "LABEL_2"}:
                    mapped[ks] = DEFAULT_LABEL_MAP.get(vv.split("_")[-1], "Neutral")
                else:
                    mapped[ks] = DEFAULT_LABEL_MAP.get(ks, "Neutral")
            if mapped:
                self._id2label = mapped
        except Exception:
            pass

    def _build(self):
        if self._ready:
            return self._pipe

        model_dir = Path(settings.sentiment_model_dir)
        if model_dir.exists() and (model_dir / "config.json").exists():
            try:
                self._load_id2label(model_dir)
                tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
                model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
                self._pipe = pipeline(
                    "text-classification",
                    model=model,
                    tokenizer=tokenizer,
                    device=-1,
                    truncation=True,
                    max_length=settings.sentiment_max_length,
                )
                self._model_name = str(model_dir)
                self._ready = True
                return self._pipe
            except Exception:
                pass

        # Fallback to base model (not fine-tuned), still ensures requested backbone is used.
        try:
            base = settings.sentiment_base_model
            tokenizer = AutoTokenizer.from_pretrained(base)
            model = AutoModelForSequenceClassification.from_pretrained(base, num_labels=3)
            self._pipe = pipeline(
                "text-classification",
                model=model,
                tokenizer=tokenizer,
                device=-1,
                truncation=True,
                max_length=settings.sentiment_max_length,
            )
            self._model_name = base
            self._ready = True
            return self._pipe
        except Exception:
            self._ready = True
            self._pipe = None
            return None

    def classify(self, text: str) -> SentimentOutput | None:
        p = self._build()
        if p is None:
            return None
        try:
            out = p(text[:1024])[0]
            raw_label = str(out.get("label", "")).strip()
            score = float(out.get("score", 0.0))

            if raw_label in {"Positive", "Neutral", "Negative"}:
                label = raw_label
            elif raw_label.upper().startswith("LABEL_"):
                idx = raw_label.split("_")[-1]
                label = self._id2label.get(idx, DEFAULT_LABEL_MAP.get(idx, "Neutral"))
            else:
                idx = raw_label if raw_label.isdigit() else "1"
                label = self._id2label.get(idx, DEFAULT_LABEL_MAP.get(idx, "Neutral"))

            return SentimentOutput(label=label, score=score)
        except Exception:
            return None


sentiment_service = SentimentService()

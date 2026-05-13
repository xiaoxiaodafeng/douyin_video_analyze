from __future__ import annotations

import argparse
import os
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

LABEL2ID = {"Negative": 0, "Neutral": 1, "Positive": 2}
ID2LABEL = {0: "Negative", 1: "Neutral", 2: "Positive"}


class SentimentDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_length: int):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        text = str(self.texts[idx])
        label = int(self.labels[idx])
        enc = self.tokenizer(
            text,
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt",
        )
        item = {k: v.squeeze(0) for k, v in enc.items()}
        item["labels"] = torch.tensor(label, dtype=torch.long)
        return item


class WeightedTrainer(Trainer):
    def __init__(self, class_weights: torch.Tensor | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        labels = inputs.get("labels")
        outputs = model(**inputs)
        logits = outputs.get("logits")

        if self.class_weights is not None:
            loss_fct = nn.CrossEntropyLoss(weight=self.class_weights.to(logits.device))
            loss = loss_fct(logits.view(-1, self.model.config.num_labels), labels.view(-1))
        else:
            loss_fct = nn.CrossEntropyLoss()
            loss = loss_fct(logits.view(-1, self.model.config.num_labels), labels.view(-1))

        return (loss, outputs) if return_outputs else loss


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=1)
    return {
        "accuracy": accuracy_score(labels, preds),
        "f1_macro": f1_score(labels, preds, average="macro"),
    }


def main():
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
    os.environ["DISABLE_SAFETENSORS_CONVERSION"] = "1"

    parser = argparse.ArgumentParser(description="Fine-tune hfl/chinese-roberta-wwm-ext for 3-class sentiment")
    parser.add_argument("--train-csv", required=True)
    parser.add_argument("--output-dir", default="./models/roberta_sentiment_3cls")
    parser.add_argument("--base-model", default="hfl/chinese-roberta-wwm-ext")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--eval-ratio", type=float, default=0.15)
    parser.add_argument("--warmup-ratio", type=float, default=0.1)
    parser.add_argument("--grad-accum-steps", type=int, default=1)
    parser.add_argument("--use-class-weights", action="store_true")
    args = parser.parse_args()

    df = pd.read_csv(args.train_csv)
    if "text" not in df.columns:
        raise ValueError("train csv must include text column")

    if "label_id" not in df.columns:
        if "label" not in df.columns:
            raise ValueError("train csv must include label or label_id")
        df["label_id"] = df["label"].map(LABEL2ID)

    df = df.dropna(subset=["text", "label_id"]).copy()
    df["label_id"] = df["label_id"].astype(int)
    df = df[df["label_id"].isin([0, 1, 2])]

    train_df, eval_df = train_test_split(
        df,
        test_size=args.eval_ratio,
        random_state=42,
        stratify=df["label_id"] if len(df["label_id"].unique()) > 1 else None,
    )

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        num_labels=3,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        use_safetensors=False,
    )

    train_ds = SentimentDataset(train_df["text"].tolist(), train_df["label_id"].tolist(), tokenizer, args.max_length)
    eval_ds = SentimentDataset(eval_df["text"].tolist(), eval_df["label_id"].tolist(), tokenizer, args.max_length)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(out / "checkpoints"),
        eval_strategy="epoch",
        save_strategy="epoch",
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        num_train_epochs=args.epochs,
        weight_decay=0.01,
        logging_steps=20,
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
        greater_is_better=True,
        save_total_limit=2,
        fp16=torch.cuda.is_available(),
        warmup_ratio=args.warmup_ratio,
        gradient_accumulation_steps=args.grad_accum_steps,
    )

    class_weights = None
    if args.use_class_weights:
        counts = train_df["label_id"].value_counts().to_dict()
        total = float(len(train_df))
        weights = []
        for i in range(3):
            c = float(counts.get(i, 1))
            weights.append(total / (3.0 * c))
        class_weights = torch.tensor(weights, dtype=torch.float32)

    trainer = WeightedTrainer(
        class_weights=class_weights,
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    metrics = trainer.evaluate()

    preds = trainer.predict(eval_ds)
    y_pred = np.argmax(preds.predictions, axis=1)
    y_true = eval_df["label_id"].values
    report = classification_report(y_true, y_pred, target_names=["Negative", "Neutral", "Positive"], output_dict=True)

    trainer.save_model(str(out))
    tokenizer.save_pretrained(str(out))

    result = {
        "metrics": metrics,
        "report": report,
        "train_size": int(len(train_df)),
        "eval_size": int(len(eval_df)),
        "class_weights": class_weights.tolist() if class_weights is not None else None,
    }
    (out / "eval_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

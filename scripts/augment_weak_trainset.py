from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd


NEG_MARKERS = [
    "很焦虑",
    "太难受了",
    "真的戒不掉",
    "这体验很差",
    "有点失望",
]
POS_MARKERS = [
    "确实有帮助",
    "真的很有用",
    "我很支持",
    "效果不错",
    "值得推荐",
]
NEU_MARKERS = [
    "个人感受",
    "仅供参考",
    "中立看法",
    "还需要观察",
    "先观望一下",
]


def augment_text(text: str, label: str) -> str:
    t = text.strip()
    if label == "Negative":
        return f"{t}，{random.choice(NEG_MARKERS)}"
    if label == "Positive":
        return f"{t}，{random.choice(POS_MARKERS)}"
    return f"{t}，{random.choice(NEU_MARKERS)}"


def main():
    parser = argparse.ArgumentParser(description="Augment weak sentiment dataset to larger size")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--output-csv", default="./datasets/sentiment_train_hybrid.csv")
    parser.add_argument("--target-size", type=int, default=2200)
    parser.add_argument("--max-repeat", type=int, default=12)
    args = parser.parse_args()

    df = pd.read_csv(args.input_csv)
    df = df.dropna(subset=["text", "label", "label_id"]).copy()
    df["text"] = df["text"].astype(str)
    df["label"] = df["label"].astype(str)
    df["label_id"] = df["label_id"].astype(int)

    rows = df.to_dict(orient="records")
    out = rows[:]

    per_label = {k: [r for r in rows if r["label"] == k] for k in ["Negative", "Neutral", "Positive"]}
    for k in per_label:
        if not per_label[k]:
            raise RuntimeError(f"label {k} is empty in input set")

    i = 0
    while len(out) < args.target_size:
        i += 1
        if i > args.target_size * args.max_repeat:
            break
        for label in ["Negative", "Positive", "Neutral"]:
            base = random.choice(per_label[label])
            new_text = augment_text(base["text"], label)
            out.append({"text": new_text, "label": label, "label_id": int(base["label_id"])})
            if len(out) >= args.target_size:
                break

    out_df = pd.DataFrame(out).drop_duplicates(subset=["text"], keep="first")
    if len(out_df) > args.target_size:
        out_df = out_df.sample(n=args.target_size, random_state=42)

    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output, index=False, encoding="utf-8")

    print("output", output.resolve())
    print("rows", len(out_df))
    print("dist", out_df["label"].value_counts().to_dict())


if __name__ == "__main__":
    main()

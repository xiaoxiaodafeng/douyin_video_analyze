from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path


def weak_label(text: str) -> str:
    pos = [
        "好", "喜欢", "支持", "优秀", "不错", "推荐", "赞", "爱", "棒", "满意", "佩服", "厉害", "成功", "戒掉", "改善", "帮助",
    ]
    neg = [
        "焦虑", "躯体化", "失眠", "头疼", "心慌", "手抖", "冒虚汗", "酗酒", "依赖", "戒断", "上瘾", "戒不掉", "痛苦", "难喝", "醉死", "假酒", "记忆力不好", "记不起来",
    ]
    t = (text or "").strip()
    if not t:
        return "Neutral"
    s = 0
    for w in pos:
        if w in t:
            s += 1
    for w in neg:
        if w in t:
            s -= 1
    if s >= 1:
        return "Positive"
    if s <= -1:
        return "Negative"
    return "Neutral"


def iter_texts(comments_json: Path):
    data = json.loads(comments_json.read_text(encoding="utf-8"))
    for c in data:
        t = str(c.get("text") or "").strip()
        if t:
            yield t
        for r in c.get("replies") or []:
            rt = str(r.get("text") or "").strip()
            if rt:
                yield rt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--comments-json", required=True)
    parser.add_argument("--manual-csv", default="")
    parser.add_argument("--output-csv", default="./datasets/sentiment_train_hybrid.csv")
    parser.add_argument("--neutral-cap", type=int, default=0, help="0 means auto cap")
    args = parser.parse_args()

    rows = []
    for t in iter_texts(Path(args.comments_json)):
        rows.append((t, weak_label(t)))

    if args.manual_csv:
        mpath = Path(args.manual_csv)
        if mpath.exists():
            with mpath.open("r", encoding="utf-8") as f:
                rd = csv.DictReader(f)
                for r in rd:
                    t = (r.get("text") or "").strip()
                    l = (r.get("label") or "").strip().capitalize()
                    if t and l in {"Negative", "Neutral", "Positive"}:
                        rows.append((t, l))

    uniq = {}
    for t, l in rows:
        uniq[t] = l
    rows = list(uniq.items())

    neg = [x for x in rows if x[1] == "Negative"]
    pos = [x for x in rows if x[1] == "Positive"]
    neu = [x for x in rows if x[1] == "Neutral"]
    random.shuffle(neg)
    random.shuffle(pos)
    random.shuffle(neu)

    cap = args.neutral_cap if args.neutral_cap > 0 else max(len(neg) + len(pos), 120)
    if len(neu) > cap:
        neu = neu[:cap]

    rows = neg + pos + neu
    random.shuffle(rows)

    out = Path(args.output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    label_map = {"Negative": 0, "Neutral": 1, "Positive": 2}
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["text", "label", "label_id"])
        for t, l in rows:
            w.writerow([t, l, label_map[l]])

    print("output", out)
    print("rows", len(rows))
    print("dist", dict(Counter([l for _, l in rows])))


if __name__ == "__main__":
    main()

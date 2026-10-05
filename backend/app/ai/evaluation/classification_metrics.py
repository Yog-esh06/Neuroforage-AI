"""Classification metrics: per-class precision / recall / F1, macro & micro averages, confusion matrix."""
from __future__ import annotations

from collections import Counter, defaultdict


def evaluate_classification(truth: dict[str, str], predicted: dict[str, str]) -> dict:
    labels = sorted(set(truth.values()) | set(predicted.values()))
    tp, fp, fn = Counter(), Counter(), Counter()
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for doc, t in truth.items():
        p = predicted.get(doc, "Unknown")
        confusion[t][p] += 1
        if p == t:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1
    per_class = {}
    for c in labels:
        prec = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) else 0.0
        rec = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[c] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4), "support": tp[c] + fn[c]}
    supported = [c for c in labels if per_class[c]["support"] > 0]
    macro = {m: round(sum(per_class[c][m] for c in supported) / len(supported), 4) for m in ("precision", "recall", "f1")} if supported else {}
    total = sum(1 for _ in truth)
    micro_acc = round(sum(tp.values()) / total, 4) if total else 0.0
    return {"accuracy": micro_acc, "macro": macro, "per_class": per_class, "confusion": {k: dict(v) for k, v in confusion.items()},
            "errors": [{"document": d, "expected": t, "predicted": predicted.get(d, "Unknown")} for d, t in truth.items() if predicted.get(d, "Unknown") != t]}

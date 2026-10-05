"""Retrieval metrics: Recall@K, Precision@K, MRR (and nDCG@K as a rank-sensitive companion).

A retrieved passage is *relevant* for a question when it comes from an expected document AND contains at least one of
that expectation's key phrases (case-insensitive). Judgments are therefore tied to ground-truth text, not to scores.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass
class Expectation:
    document: str  # file name
    phrases: list[str]  # any one phrase must occur in the passage
    page: int | None = None


@dataclass
class RetrievedItem:
    document: str
    page: int
    text: str


def is_relevant(item: RetrievedItem, expectations: Sequence[Expectation]) -> int | None:
    """Index of the first expectation the item satisfies, else None."""
    low = item.text.lower()
    for i, e in enumerate(expectations):
        if item.document != e.document or (e.page is not None and item.page != e.page):
            continue
        if any(p.lower() in low for p in e.phrases):
            return i
    return None


def recall_at_k(ranked: Sequence[RetrievedItem], exps: Sequence[Expectation], k: int) -> float:
    """Share of expectations covered by the top-k (each expectation counted once)."""
    if not exps:
        return 0.0
    hit = {i for it in ranked[:k] if (i := is_relevant(it, exps)) is not None}
    return len(hit) / len(exps)


def precision_at_k(ranked: Sequence[RetrievedItem], exps: Sequence[Expectation], k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for it in top if is_relevant(it, exps) is not None) / len(top)


def reciprocal_rank(ranked: Sequence[RetrievedItem], exps: Sequence[Expectation]) -> float:
    for r, it in enumerate(ranked, start=1):
        if is_relevant(it, exps) is not None:
            return 1.0 / r
    return 0.0


def ndcg_at_k(ranked: Sequence[RetrievedItem], exps: Sequence[Expectation], k: int) -> float:
    gains = [1.0 if is_relevant(it, exps) is not None else 0.0 for it in ranked[:k]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(exps), k)))
    return dcg / ideal if ideal else 0.0


def evaluate_retrieval(questions: list[dict], search: Callable[[str], list[RetrievedItem]], ks: Sequence[int] = (1, 3, 5, 10)) -> dict:
    """`questions`: [{"id","question","expected":[{"document","phrases","page?"}]}]. Returns per-question rows + macro averages."""
    rows = []
    for q in questions:
        exps = [Expectation(e["document"], e["phrases"], e.get("page")) for e in q["expected"]]
        ranked = search(q["question"])
        row = {"id": q["id"], "question": q["question"], "mrr": reciprocal_rank(ranked, exps)}
        for k in ks:
            row[f"recall@{k}"] = recall_at_k(ranked, exps, k)
            row[f"precision@{k}"] = precision_at_k(ranked, exps, k)
            row[f"ndcg@{k}"] = ndcg_at_k(ranked, exps, k)
        rows.append(row)
    keys = [k for k in rows[0] if k not in ("id", "question")] if rows else []
    summary = {k: round(sum(r[k] for r in rows) / len(rows), 4) for k in keys}
    return {"n_questions": len(rows), "summary": summary, "per_question": rows}

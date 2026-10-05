"""Generation metrics, computed independently of the generator's own bookkeeping.

* citation coverage  = statements carrying at least one valid citation / all statements in the answer
* groundedness       = statements whose content terms are >= GROUND_MIN covered by their cited evidence (and whose numbers
                       all occur there) / all statements
* answer relevance   = share of the question's expected key facts (phrases) found in the answer's statements; for
                       questions that must be refused, 1.0 only if the system refused
"""
from __future__ import annotations

from typing import Sequence

from app.ai.reasoning.grounded_generation import support_score

GROUND_MIN = 0.6


def citation_coverage(answer: dict) -> float:
    ev_ids = {e["evidence_id"] for e in answer.get("evidence", [])}
    stmts = [s for f in answer.get("findings", []) for s in f["statements"]]
    if not stmts:
        return 0.0
    return sum(1 for s in stmts if s.get("evidence") and set(s["evidence"]) <= ev_ids) / len(stmts)


def groundedness(answer: dict) -> float:
    ev = {e["evidence_id"]: e["text"] for e in answer.get("evidence", [])}
    stmts = [s for f in answer.get("findings", []) for s in f["statements"]]
    if not stmts:
        return 0.0
    ok = 0
    for s in stmts:
        cited = " ".join(ev.get(i, "") for i in s.get("evidence", []))
        share, missing = support_score(s["text"], cited)
        ok += int(share >= GROUND_MIN and not missing)
    return ok / len(stmts)


def answer_relevance(answer: dict, key_facts: Sequence[str], must_refuse: bool = False) -> float:
    if must_refuse:
        return 1.0 if answer.get("refused") else 0.0
    if answer.get("refused") or not key_facts:
        return 0.0
    text = " ".join(s["text"] for f in answer.get("findings", []) for s in f["statements"]).lower()
    return sum(1 for k in key_facts if k.lower() in text) / len(key_facts)


def evaluate_answers(cases: list[dict], ask) -> dict:
    """`cases`: [{"id","question","key_facts":[...],"must_refuse":bool}]; `ask(question) -> answer dict`."""
    rows = []
    for c in cases:
        a = ask(c["question"])
        refused = bool(a.get("refused"))
        rows.append({
            "id": c["id"], "question": c["question"], "refused": refused, "must_refuse": c.get("must_refuse", False),
            "citation_coverage": citation_coverage(a) if not refused else None, "groundedness": groundedness(a) if not refused else None,
            "answer_relevance": answer_relevance(a, c.get("key_facts", []), c.get("must_refuse", False)),
            "confidence": a.get("confidence", {}).get("score"),
        })
    def avg(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None
    return {"n_cases": len(rows), "summary": {"citation_coverage": avg("citation_coverage"), "groundedness": avg("groundedness"),
                                              "answer_relevance": avg("answer_relevance")}, "per_case": rows}

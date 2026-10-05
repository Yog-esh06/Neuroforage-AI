"""Confidence engine.

IMPORTANT: the score is an *engineering confidence index* — a weighted combination of observable quality signals.
It is NOT a calibrated probability: 0.8 does not mean "80% of such answers are correct". Calibration against labelled
outcomes (see docs/evaluation.md) would be required before reading it probabilistically.

score = (sum_i w_i * component_i) * (1 - contradiction_penalty)

components (each 0..1):
  retrieval_quality    mean of the top-3 reranked relevance scores, scaled (0.65 => 1.0)
  evidence_quantity    1 - exp(-n_cited_evidence / 3), with a small bonus for independent documents
  evidence_agreement   corroboration (statements backed by >=2 items/documents) blended with absence of conflicts
  source_reliability   mean quality of cited sources (native text > OCR)
  model_certainty      groundedness (supported statements share) reduced by self-reported uncertainty notes
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

WEIGHTS = {"retrieval_quality": 0.25, "evidence_quantity": 0.15, "evidence_agreement": 0.20,
           "source_reliability": 0.15, "model_certainty": 0.25}
HIGH, MEDIUM = 0.75, 0.50
DISCLAIMER = ("Engineering confidence index (weighted quality signals), not a calibrated probability. "
              "Do not interpret 0.9 as a 90% chance of correctness.")


@dataclass
class ConfidenceInput:
    relevance_scores: list[float]                 # of cited evidence, best first
    cited_doc_ids: list[int]
    source_qualities: list[float]
    statement_support: list[int] = field(default_factory=list)  # per supported statement: number of supporting evidence items
    statement_docs: list[int] = field(default_factory=list)     # per supported statement: number of distinct documents
    groundedness: float = 1.0                     # supported statements / total statements
    uncertainty_notes: int = 0
    conflict_confidences: list[float] = field(default_factory=list)


@dataclass
class ConfidenceResult:
    score: float
    level: str
    breakdown: dict[str, float]
    penalties: dict[str, float]
    explanation: str
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return {"score": self.score, "level": self.level, "breakdown": self.breakdown, "penalties": self.penalties,
                "explanation": self.explanation, "disclaimer": self.disclaimer}


def level_for(score: float) -> str:
    return "HIGH" if score >= HIGH else "MEDIUM" if score >= MEDIUM else "LOW"


def compute_confidence(inp: ConfidenceInput) -> ConfidenceResult:
    if not inp.relevance_scores:  # nothing cited => nothing to be confident about, regardless of other signals
        zero = {k: 0.0 for k in WEIGHTS}
        return ConfidenceResult(0.0, "LOW", zero, {"contradiction": 0.0}, "No supporting evidence was cited.")
    top3 = sorted(inp.relevance_scores, reverse=True)[:3]
    retrieval = min(1.0, (sum(top3) / len(top3)) / 0.65) if top3 else 0.0
    n = len(inp.relevance_scores)
    distinct_docs = len(set(inp.cited_doc_ids))
    quantity = min(1.0, (1 - math.exp(-n / 3)) + 0.08 * max(distinct_docs - 1, 0)) if n else 0.0

    if inp.statement_support:
        corroborated = sum(1 for s, d in zip(inp.statement_support, inp.statement_docs or inp.statement_support) if s >= 2 or d >= 2)
        corroboration = corroborated / len(inp.statement_support)
    else:
        corroboration = 0.0
    conflict_weight = min(1.0, sum(inp.conflict_confidences)) if inp.conflict_confidences else 0.0
    agreement = 0.55 * (1 - conflict_weight) + 0.45 * corroboration
    reliability = sum(inp.source_qualities) / len(inp.source_qualities) if inp.source_qualities else 0.0
    certainty = max(0.0, inp.groundedness * (1 - 0.12 * min(inp.uncertainty_notes, 4)))

    comps = {"retrieval_quality": retrieval, "evidence_quantity": quantity, "evidence_agreement": agreement,
             "source_reliability": reliability, "model_certainty": certainty}
    base = sum(WEIGHTS[k] * v for k, v in comps.items())
    penalty = min(0.5, 0.35 * max(inp.conflict_confidences, default=0.0) + 0.05 * max(len(inp.conflict_confidences) - 1, 0))
    score = round(max(0.0, min(1.0, base * (1 - penalty))), 3)
    parts = [f"{k.replace('_', ' ')} {v:.2f}" for k, v in comps.items()]
    expl = "Signals: " + ", ".join(parts)
    if penalty:
        expl += f". Reduced by {penalty:.0%} because {len(inp.conflict_confidences)} conflicting claim(s) touch the cited evidence."
    return ConfidenceResult(score, level_for(score), {k: round(v, 3) for k, v in comps.items()},
                            {"contradiction": round(penalty, 3)}, expl)

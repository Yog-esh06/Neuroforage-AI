"""Local, deterministic 'provider' that composes an answer purely from evidence sentences (no LLM, no API key).

Every statement is a verbatim sentence from the cited evidence, so groundedness is guaranteed by construction.
It does not paraphrase or infer; use a real LLM provider for synthesis. Risk questions use the shared risk rules.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from app.ai.extraction import values as V
from app.ai.providers.base import GenerationRequest, LLMProvider, LLMResult
from app.ai.reasoning.risk_rules import SEVERITY_SCORE, scan_sentence
from app.schemas.evidence import Evidence
from app.utils.text import split_sentences, stem_tokens, truncate

VERSION = "extractive-v1"
MIN_OVERLAP = 1


def _sent_score(sent: str, q_stems: set[str], intents: list[str]) -> float:
    toks = set(stem_tokens(sent))
    if not toks or not q_stems:
        return 0.0
    overlap = len(toks & q_stems)
    score = overlap / max(len(q_stems), 1)
    if "date" in intents and V.parse_dates(sent):
        score += 0.25
    if "money" in intents and V.parse_money(sent):
        score += 0.25
    if "obligation" in intents and re.search(r"\b(shall|must|required|obligat\w+)\b", sent, re.I):
        score += 0.2
    return score if overlap >= MIN_OVERLAP or score >= 0.25 else 0.0


class ExtractiveProvider(LLMProvider):
    name = "extractive"
    model = "extractive-composer"

    @property
    def is_llm(self) -> bool:
        return False

    def generate(self, req: GenerationRequest) -> LLMResult:
        ev = req.evidence
        if not ev:
            out = {"summary": "", "refused": True, "refusal_reason": "No evidence was retrieved for this question.",
                   "findings": [], "uncertainty_notes": []}
            return LLMResult(json.dumps(out), self.name, self.model, VERSION)

        q_stems = set(stem_tokens(req.question))
        findings: list[dict] = []

        if "risk" in req.intents:
            groups: dict[str, dict] = {}
            for e in ev:
                for s in split_sentences(e.text):
                    for hit in scan_sentence(s):
                        g = groups.setdefault(hit.rule_id, {"hit": hit, "stmts": [], "ev": [], "score": hit.severity_score})
                        if all(st["text"] != s for st in g["stmts"]):
                            g["stmts"].append({"text": s.strip(), "type": "fact", "evidence": [e.evidence_id]})
                        if e.evidence_id not in g["ev"]:
                            g["ev"].append(e.evidence_id)
                        g["score"] = max(g["score"], hit.severity_score)
            for rid, g in sorted(groups.items(), key=lambda kv: (-kv[1]["score"], -len(kv[1]["ev"])))[:8]:
                h = g["hit"]
                findings.append({"title": h.title, "severity": h.severity, "statements": g["stmts"][:3], "entities": [],
                                 "reasoning": h.reasoning, "contradictory_evidence": [], "recommended_action": h.action,
                                 "_category": h.category})

        if not findings:
            scored: list[tuple[float, Evidence, str]] = []
            for e in ev:
                for s in split_sentences(e.text):
                    sc = _sent_score(s, q_stems, req.intents)
                    if sc > 0:
                        scored.append((sc * (0.6 + 0.4 * e.relevance_score), e, s.strip()))
            scored.sort(key=lambda x: -x[0])
            by_ev: dict[str, dict] = defaultdict(lambda: {"stmts": [], "e": None})
            for sc, e, s in scored[:8]:
                g = by_ev[e.evidence_id]
                g["e"] = e
                if len(g["stmts"]) < 3 and all(x["text"] != s for x in g["stmts"]):
                    g["stmts"].append({"text": s, "type": "fact", "evidence": [e.evidence_id]})
            for eid, g in list(by_ev.items())[:5]:
                e: Evidence = g["e"]
                findings.append({"title": e.section or f"{e.document_name}, page {e.page_number}", "severity": "info",
                                 "statements": g["stmts"], "entities": [], "reasoning": "Sentences selected by query-term overlap from the cited passage.",
                                 "contradictory_evidence": [], "recommended_action": ""})

        if not findings:
            out = {"summary": "", "refused": True,
                   "refusal_reason": "Retrieved passages contain no sentences that address the question; refusing to guess.",
                   "findings": [], "uncertainty_notes": []}
            return LLMResult(json.dumps(out), self.name, self.model, VERSION)

        top = [s for f in findings for s in f["statements"]][:2]
        summary = " ".join(f"{s['text']} [{','.join(s['evidence'])}]" for s in top)
        notes = ["Answer composed by the local extractive composer: statements are verbatim evidence sentences, with no synthesis."]
        out = {"summary": truncate(summary, 700), "refused": False, "refusal_reason": "", "findings": findings, "uncertainty_notes": notes}
        return LLMResult(json.dumps(out), self.name, self.model, VERSION)

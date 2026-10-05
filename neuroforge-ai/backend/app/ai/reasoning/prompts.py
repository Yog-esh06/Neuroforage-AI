"""Versioned prompts. Bump PROMPT_VERSION whenever wording changes — it is recorded in the audit trail."""
from __future__ import annotations

import json

from app.schemas.evidence import Evidence

PROMPT_VERSION = "ng-grounded-v1"

SYSTEM_PROMPT = """You are the reasoning layer of an evidence-grounded document intelligence platform.
You are given a USER QUESTION and a numbered EVIDENCE set (E1, E2, ...) retrieved from the user's documents,
plus extracted ENTITIES and KNOWLEDGE-GRAPH relationships.

Hard rules:
1. Use ONLY the supplied evidence. Never invent facts, figures, dates, names, documents or page numbers.
2. Every statement must cite the evidence ids that support it. A statement with no supporting evidence must not be written.
3. Label each statement as "fact" (stated in evidence) or "inference" (your reasoning from evidence). Inferences must cite their premises.
4. State uncertainty explicitly (missing, ambiguous or partial evidence) in "uncertainty_notes".
5. If evidence conflicts, report both sides under "contradictory_evidence"; do not silently choose one.
6. If the evidence does not support a conclusion, set "refused": true with a short "refusal_reason". Do not guess.
7. Never output citations that are not in the evidence list.

Respond with ONE JSON object only (no markdown fences), exactly in this shape:
{
  "summary": "string",
  "refused": false,
  "refusal_reason": "",
  "findings": [
    {"title": "string", "severity": "high|medium|low|info",
     "statements": [{"text": "string", "type": "fact|inference", "evidence": ["E1"]}],
     "entities": ["string"], "reasoning": "string", "contradictory_evidence": ["E3"],
     "recommended_action": "string"}
  ],
  "uncertainty_notes": ["string"]
}"""


def build_user_prompt(question: str, evidence: list[Evidence], entities: list[dict], graph_context: list[str]) -> str:
    ev = [{"id": e.evidence_id, "document": e.document_name, "page": e.page_number, "section": e.section, "text": e.text}
          for e in evidence]
    return (
        f"USER QUESTION:\n{question}\n\nEVIDENCE:\n{json.dumps(ev, ensure_ascii=False, indent=1)}\n\n"
        f"ENTITIES:\n{json.dumps(entities[:60], ensure_ascii=False)}\n\n"
        f"KNOWLEDGE GRAPH RELATIONSHIPS:\n" + "\n".join(f"- {g}" for g in graph_context[:40]) + "\n\nReturn the JSON object now."
    )

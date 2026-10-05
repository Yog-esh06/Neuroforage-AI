"""Query understanding: intent, keywords, entities, soft hints (document type / page) used by retrieval and reranking."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.extraction.entities import extract_entities
from app.utils.text import stem_tokens

INTENT_PATTERNS = {
    "risk": r"\b(risks?|exposure|liabilit\w+|penalt\w+|breach|threat|vulnerab\w+|danger|concern|problem|issue)\b",
    "contradiction": r"\b(conflict\w*|contradict\w*|inconsisten\w*|discrepanc\w+|disagree\w*|mismatch\w*|differ\w*)\b",
    "date": r"\b(when|date|deadline|expir\w+|renew\w*|terminat\w+|effective|due)\b",
    "money": r"\b(how much|cost|price|fee|payment|amount|total|budget|revenue|spend|\$|€|£|₹)\b",
    "obligation": r"\b(obligat\w+|must|shall|required|responsib\w+|duty|duties|commit\w+)\b",
    "definition": r"^\s*(what is|what are|define|who is|who are)\b",
    "summary": r"\b(summar\w+|overview|key points|main points|highlights)\b",
}
DOC_TYPE_HINTS = {
    "Contract": r"\bcontracts?\b|\bagreements?\b", "Invoice": r"\binvoices?\b|\bbills?\b",
    "Research Paper": r"\bpapers?\b|\bresearch\b|\bstud(?:y|ies)\b", "Financial Report": r"\bfinancial (?:reports?|statements?)\b|\bannual reports?\b|\bearnings\b",
    "Policy": r"\bpolic(?:y|ies)\b", "Resume": r"\bresumes?\b|\bcvs?\b|\bcandidates?\b", "Legal Document": r"\blegal\b|\bcourt\b|\blawsuit\b",
    "Technical Documentation": r"\bdocumentation\b|\bmanual\b|\bapi\b",
}
RECENCY = re.compile(r"\b(latest|recent(?:ly)?|newest|current|up[- ]to[- ]date|most recent|now)\b", re.I)
PAGE_REF = re.compile(r"\bpages?\s+(\d{1,4})(?:\s*(?:-|to|–)\s*(\d{1,4}))?\b", re.I)


@dataclass
class QueryUnderstanding:
    text: str
    keywords: list[str]
    entities: list[dict]
    intents: list[str]
    doc_type_hints: list[str]
    page_hint: tuple[int, int] | None
    wants_recency: bool
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"keywords": self.keywords, "entities": self.entities, "intents": self.intents,
                "doc_type_hints": self.doc_type_hints, "page_hint": list(self.page_hint) if self.page_hint else None,
                "wants_recency": self.wants_recency, "notes": self.notes}


def understand(query: str) -> QueryUnderstanding:
    q = query.strip()
    intents = [name for name, pat in INTENT_PATTERNS.items() if re.search(pat, q, re.I)] or ["general"]
    hints = [t for t, pat in DOC_TYPE_HINTS.items() if re.search(pat, q, re.I)]
    m = PAGE_REF.search(q)
    page_hint = (int(m.group(1)), int(m.group(2) or m.group(1))) if m else None
    ents = [{"text": e.text, "type": e.type, "canonical": e.canonical} for e in extract_entities(q, use_spacy=False)
            if e.type in ("ORG", "PERSON", "CONTRACT", "REGULATION", "PRODUCT", "LOCATION", "TECHNOLOGY")]
    notes = []
    if hints:
        notes.append(f"document-type hint(s) applied as soft boost: {', '.join(hints)}")
    if page_hint:
        notes.append(f"page hint {page_hint[0]}–{page_hint[1]} applied as soft boost")
    return QueryUnderstanding(q, stem_tokens(q), ents, intents, hints, page_hint, bool(RECENCY.search(q)), notes)

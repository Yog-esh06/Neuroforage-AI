"""Contradiction detection between factual claims (never silently picks a side).

Pipeline: sentences -> typed facts (topic, value, subject, qualifiers) -> compare facts with the same topic across
documents (or distant pages of one document) -> report materially different values with a conflict confidence.

Conflict confidence (engineering score, not a probability) =
    0.50 base + subject agreement (0..0.20) + sentence similarity (0..0.20) + precision alignment (0..0.10),
clipped to [0.30, 0.97]; only >= MIN_CONFIDENCE are reported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations

from app.ai.extraction import values as V
from app.ai.extraction.entities import extract_entities
from app.utils.text import canonical_key, split_sentences, stem_tokens

MIN_CONFIDENCE = 0.55
INDEPENDENT_RECORD_TYPES = {"Invoice", "Resume"}


@dataclass
class TextUnit:
    chunk_id: int
    document_id: int
    document_name: str
    page: int
    text: str
    doc_type: str = ""


@dataclass
class Fact:
    topic: str
    kind: str  # date | money | duration | percent | text | bool
    value: object
    display: str
    subject: str | None
    qualifiers: frozenset[str]
    sentence: str
    unit: TextUnit
    precision: str = ""


@dataclass
class Conflict:
    topic: str
    subject: str | None
    kind: str
    value_a: str
    value_b: str
    evidence_a: Fact
    evidence_b: Fact
    confidence: float
    explanation: str = ""

    def to_dict(self) -> dict:
        def ev(f: Fact) -> dict:
            return {"document_id": f.unit.document_id, "document_name": f.unit.document_name, "page_number": f.unit.page,
                    "chunk_id": f.unit.chunk_id, "text": f.sentence, "value": f.display}
        return {"topic": self.topic, "subject": self.subject, "kind": self.kind, "value_a": self.value_a, "value_b": self.value_b,
                "evidence_a": ev(self.evidence_a), "evidence_b": ev(self.evidence_b), "confidence": self.confidence,
                "explanation": self.explanation}


# topic -> (pattern, value kind)
TOPICS: dict[str, tuple[re.Pattern, str]] = {
    "Contract expiration": (re.compile(r"\b(?:expir\w+|terminat\w+|term (?:ends?|expires?)|valid until|end date|ends? on|through)\b", re.I), "date"),
    "Effective date": (re.compile(r"\b(?:effective (?:date|as of|on)|commenc\w+|start date|begins? on|dated as of)\b", re.I), "date"),
    "Contract value": (re.compile(r"\b(?:total (?:contract )?(?:value|fees?|price|amount)|contract value|purchase price|annual fee|monthly fee|license fee|"
                                  r"fees? (?:of|are|is|shall be)|aggregate (?:amount|fees)|amount due|payment of|shall pay|total)\b", re.I), "money"),
    "Liability cap": (re.compile(r"\b(?:liability cap|limit(?:ation)? of liability|aggregate liability|liability shall not exceed|cap(?:ped)? (?:at|of))\b", re.I), "money"),
    "Term length": (re.compile(r"\b(?:initial term|term of|renewal term|subscription term|for a (?:period|term) of)\b", re.I), "duration"),
    "Notice period": (re.compile(r"\b(?:notice period|written notice|prior notice|days'? notice|notice of (?:termination|non-renewal))\b", re.I), "duration"),
    "Payment terms": (re.compile(r"\b(?:payment terms?|payable within|due within|net ?\d+|pay(?:ment)? (?:is )?due)\b", re.I), "duration"),
    "Late payment rate": (re.compile(r"\b(?:interest|late (?:fee|charge|payment))\b", re.I), "percent"),
    "Revenue": (re.compile(r"\b(?:total )?revenues?\b", re.I), "money"),
    "Net income": (re.compile(r"\bnet (?:income|profit|loss)\b", re.I), "money"),
    "EBITDA": (re.compile(r"\bebitda\b", re.I), "money"),
    "Headcount": (re.compile(r"\b(?:headcount|employees|staff)\b", re.I), "number"),
    "Governing law": (re.compile(r"\bgoverned by (?:the )?laws? of\s+([A-Z][A-Za-z ]{2,40})|\bgoverning law[: ]+(?:the )?(?:laws? of )?([A-Z][A-Za-z ]{2,40})", re.I), "text"),
    "Automatic renewal": (re.compile(r"\bauto(?:matic(?:ally)?)?[- ]?renew\w*|\brenews? automatically\b", re.I), "bool"),
}
QUALIFIER_WORDS = ["annual", "annually", "monthly", "quarterly", "weekly", "initial", "renewal", "total", "late", "maximum", "minimum", "optional",
                   "additional", "per", "each", "first", "second", "net", "gross", "adjusted", "projected", "forecast", "budget", "estimated"]
_NEG = re.compile(r"\b(?:not|no|neither|without|shall not|does not|will not|never)\b", re.I)
_NOISE_QUALS = {"total", "per", "each"}


def _subject(sentence: str, unit: TextUnit) -> str | None:
    ents = [e for e in extract_entities(sentence, use_spacy=False) if e.type in ("CONTRACT", "ORG")]
    for e in ents:
        if e.type == "CONTRACT":
            return canonical_key(e.text)
    return canonical_key(ents[0].text) if ents else None


def extract_facts(units: list[TextUnit]) -> list[Fact]:
    facts: list[Fact] = []
    for u in units:
        for sent in split_sentences(u.text):
            if len(sent) < 15:
                continue
            quals = frozenset(w for w in QUALIFIER_WORDS if re.search(rf"\b{w}\b", sent, re.I)) - _NOISE_QUALS
            subject = None
            for topic, (pat, kind) in TOPICS.items():
                m = pat.search(sent)
                if not m:
                    continue
                if subject is None:
                    subject = _subject(sent, u)
                after = sent[m.start():]  # values after the trigger are the ones the trigger governs
                if kind == "date":
                    vals = [v for v in V.parse_dates(sent) if v.precision != "year" or "expir" in sent.lower() or "term" in sent.lower()]
                    # a date belongs to the nearest preceding date-topic trigger (so "commences ... and expires on X" gives X to expiration)
                    for v in vals:
                        owner, best = None, -1
                        for t2, (p2, k2) in TOPICS.items():
                            if k2 != "date":
                                continue
                            for m2 in p2.finditer(sent):
                                if m2.start() < v.start and m2.start() > best:
                                    owner, best = t2, m2.start()
                        if owner == topic:
                            facts.append(Fact(topic, "date", v.value, v.raw, subject, quals, sent, u, v.precision))
                            break
                elif kind == "money":
                    vals = V.parse_money(after) or V.parse_money(sent)
                    if vals:
                        v = max(vals[:2], key=lambda x: 0) if len(vals) > 1 else vals[0]
                        facts.append(Fact(topic, "money", float(v.value), v.raw, subject, quals, sent, u))
                elif kind == "duration":
                    vals = V.parse_durations(after) or V.parse_durations(sent)
                    if vals:
                        facts.append(Fact(topic, "duration", vals[0].value, vals[0].raw, subject, quals, sent, u))
                elif kind == "percent":
                    vals = V.parse_percents(after)
                    if vals:
                        facts.append(Fact(topic, "percent", vals[0].value, vals[0].raw, subject, quals, sent, u))
                elif kind == "number":
                    nm = re.search(r"\b(\d{1,3}(?:,\d{3})+|\d{2,7})\b", after)
                    if nm and not V.parse_money(after):
                        facts.append(Fact(topic, "number", float(nm.group(1).replace(",", "")), nm.group(1), subject, quals, sent, u))
                elif kind == "text":
                    val = (m.group(1) or m.group(2) or "").strip()
                    val = re.split(r"\b(?:and|without|,|\.)", val)[0].strip()
                    if val:
                        facts.append(Fact(topic, "text", canonical_key(val), val, subject, quals, sent, u))
                elif kind == "bool":
                    neg = bool(_NEG.search(sent[max(0, m.start() - 40):m.start()]))
                    facts.append(Fact(topic, "bool", not neg, "does NOT auto-renew" if neg else "auto-renews", subject, quals, sent, u))
    return facts


def _differs(a: Fact, b: Fact) -> bool:
    if a.kind != b.kind:
        return False
    if a.kind == "date":
        # compare at the coarsest shared precision
        la = 4 if "year" in (a.precision, b.precision) else 7 if "month" in (a.precision, b.precision) else 10
        return str(a.value)[:la] != str(b.value)[:la]
    if a.kind in ("money", "number"):
        return not V.money_close(float(a.value), float(b.value), 0.005)
    if a.kind in ("duration", "percent"):
        return abs(float(a.value) - float(b.value)) > 1e-9
    return a.value != b.value


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(stem_tokens(a)), set(stem_tokens(b))
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def _subjects_compatible(a: Fact, b: Fact) -> tuple[bool, float]:
    if a.subject and b.subject:
        ta, tb = set(a.subject.split()), set(b.subject.split())
        if ta & tb:
            return True, 0.20 if a.subject == b.subject else 0.14
        return False, 0.0
    return True, 0.05


def detect_conflicts(units: list[TextUnit], *, include_same_document: bool = False,
                     min_confidence: float = MIN_CONFIDENCE) -> list[Conflict]:
    facts = extract_facts(units)
    by_topic: dict[str, list[Fact]] = {}
    for f in facts:
        by_topic.setdefault(f.topic, []).append(f)
    out: list[Conflict] = []
    seen: set[tuple] = set()
    for topic, fs in by_topic.items():
        for a, b in combinations(fs, 2):
            same_doc = a.unit.document_id == b.unit.document_id
            if same_doc and (not include_same_document or a.unit.chunk_id == b.unit.chunk_id):
                continue
            if a.qualifiers != b.qualifiers and (a.qualifiers or b.qualifiers):
                continue  # e.g. "annual fee" vs "monthly fee" are different quantities
            if not same_doc and a.unit.doc_type and a.unit.doc_type == b.unit.doc_type and a.unit.doc_type in INDEPENDENT_RECORD_TYPES:
                continue  # two invoices / resumes are separate records, not competing statements
            ok, subj_score = _subjects_compatible(a, b)
            if not ok or not _differs(a, b):
                continue
            sim = _jaccard(a.sentence, b.sentence)
            if sim < (0.12 if (a.subject and b.subject) else 0.22):
                continue
            prec = 0.10 if (a.precision == b.precision) else 0.04
            conf = max(0.30, min(0.97, 0.50 + subj_score + 0.20 * min(1.0, sim / 0.5) + prec))
            if conf < min_confidence:
                continue
            key = (topic, tuple(sorted([(a.unit.document_id, str(a.value)), (b.unit.document_id, str(b.value))])))
            if key in seen:
                continue
            seen.add(key)
            out.append(Conflict(topic, a.subject or b.subject, a.kind, a.display, b.display, a, b, round(conf, 3),
                                f"{topic}: '{a.display}' in {a.unit.document_name} (p.{a.unit.page}) vs "
                                f"'{b.display}' in {b.unit.document_name} (p.{b.unit.page})."))
    return sorted(out, key=lambda c: -c.confidence)

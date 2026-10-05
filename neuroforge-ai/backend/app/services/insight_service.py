"""Insight generation: deterministic risk/finding extraction per document + cross-document contradiction scan.

Every insight stores its evidence (document, page, chunk, sentence, bbox) and the rule/method that produced it,
and is written to the audit trail. Workflows are triggered for each new insight / contradiction.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.ai.extraction.entities import extract_entities
from app.ai.extraction.tables import profile_table
from app.ai.reasoning.confidence import ConfidenceInput, compute_confidence
from app.ai.reasoning.contradiction import TextUnit, detect_conflicts, extract_facts
from app.ai.reasoning.risk_rules import scan_sentence, severity_from_score
from app.ai.retrieval.metadata import source_quality
from app.db.models.document import Chunk, Document, DocumentElement
from app.db.models.reasoning import Citation, Contradiction, Insight
from app.db.models.user import User
from app.services import audit_service
from app.services.reasoning_service import persist_conflicts
from app.utils.text import split_sentences, truncate
from app.workflows import engine as wf_engine

log = logging.getLogger(__name__)
MAX_INSIGHTS_PER_DOC = 60
KEY_DATE_TYPES = {"Contract", "Legal Document", "Policy"}


def _confidence(precision: float, quality: float, support: int = 1) -> dict:
    """Insight confidence = rule precision prior x source reliability (OCR'd or poorly classified sources lower it).

    The rule's precision is an engineering estimate of how often the pattern is a true positive, not a measured rate.
    """
    from app.ai.reasoning.confidence import DISCLAIMER, level_for

    score = round(max(0.0, min(0.99, precision * (0.55 + 0.45 * quality))), 3)
    return {"score": score, "level": level_for(score), "breakdown": {"rule_precision_prior": round(precision, 3), "source_reliability": round(quality, 3)},
            "penalties": {"contradiction": 0.0},
            "explanation": f"rule precision prior {precision:.2f} x (0.55 + 0.45 x source reliability {quality:.2f})", "disclaimer": DISCLAIMER}


def _entity_names(sentence: str) -> list[dict]:
    return [{"name": e.text, "type": e.type} for e in extract_entities(sentence, use_spacy=False)
            if e.type in ("ORG", "CONTRACT", "MONEY", "DATE", "PERSON", "REGULATION")][:8]


def _clear_previous(db: Session, document_id: int) -> None:
    ids = [i for (i,) in db.query(Insight.id).filter(Insight.document_id == document_id, Insight.method.like("rule:%")).all()]
    if ids:
        db.query(Citation).filter(Citation.insight_id.in_(ids)).delete(synchronize_session=False)
        db.query(Insight).filter(Insight.id.in_(ids)).delete(synchronize_session=False)


def analyze_document(db: Session, doc: Document, user: User | None = None) -> list[Insight]:
    _clear_previous(db, doc.id)
    quality = source_quality(doc)
    chunks = db.query(Chunk).filter(Chunk.document_id == doc.id).order_by(Chunk.chunk_index).all()
    created: list[Insight] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, category: str, title: str, description: str, score: float, precision: float, ch: Chunk | None, sentence: str,
            method: str, action: str, reasoning: str, page: int | None = None) -> None:
        if len(created) >= MAX_INSIGHTS_PER_DOC:
            return
        ev = [{"document_id": doc.id, "document_name": doc.filename, "page_number": page or (ch.page_number if ch else 1),
               "section": ch.section if ch else None, "chunk_id": ch.id if ch else None, "text": sentence,
               "relevance_score": round(precision, 3), "retrieval_method": method, "bbox": ch.bbox if ch else None}]
        conf = _confidence(precision, quality)
        ins = Insight(kind=kind, category=category, title=truncate(title, 280), description=description, severity=severity_from_score(score),
                      severity_score=score, confidence=conf["score"], confidence_breakdown=conf, document_id=doc.id, evidence=ev,
                      entities=_entity_names(sentence), reasoning=reasoning, recommended_action=action, method=method)
        db.add(ins)
        db.flush()
        for e in ev:
            db.add(Citation(insight_id=ins.id, marker="E1", document_id=doc.id, chunk_id=e["chunk_id"], page_number=e["page_number"],
                            section=e["section"], text=e["text"], relevance_score=e["relevance_score"], retrieval_method=method, bbox=e["bbox"]))
        created.append(ins)

    for ch in chunks:
        for sent in split_sentences(ch.text):
            if len(sent) < 20:
                continue
            for hit in scan_sentence(sent):
                key = (hit.rule_id, sent[:160])
                if key in seen:
                    continue
                seen.add(key)
                add("risk", hit.category, hit.title, sent, hit.severity_score, hit.precision, ch, sent, f"rule:{hit.rule_id}", hit.action, hit.reasoning)

    # table integrity: stated totals that do not equal the sum of their rows
    for el in db.query(DocumentElement).filter(DocumentElement.document_id == doc.id, DocumentElement.element_type == "table").all():
        prof = profile_table(el.data or {})
        for chk in prof["total_checks"]:
            if not chk["consistent"]:
                text = f"Table total for '{chk['column']}' states {chk['claimed_total']:,.2f} but the rows sum to {chk['calculated_sum']:,.2f}."
                ch = next((c for c in chunks if c.chunk_type == "table" and c.page_number == el.page_number), None)
                add("financial", "totals_mismatch", f"Table total mismatch in '{chk['column']}'", text, 0.8, 0.9, ch, text, "rule:table_total_check",
                    "Verify the figures with the issuer before payment/approval.", "Computed row sum differs from the stated total.", page=el.page_number)

    # key dates / terms for agreements
    if doc.doc_type in KEY_DATE_TYPES:
        units = [TextUnit(c.id, doc.id, doc.filename, c.page_number, c.text) for c in chunks]
        by_id = {c.id: c for c in chunks}
        for f in extract_facts(units):
            if f.topic in ("Contract expiration", "Effective date", "Notice period", "Term length", "Governing law"):
                ch = by_id.get(f.unit.chunk_id)
                add("key_date" if f.kind == "date" else "obligation", "key_term", f"{f.topic}: {f.display}", f.sentence, 0.2, 0.75, ch, f.sentence,
                    "rule:key_term", "Record in the obligations calendar." if f.kind == "date" else "", f"Extracted {f.topic.lower()} value.")

    created_ids = [i.id for i in created]
    audit_service.log_event(db, action="insights_generated", user=user, entity_type="document", entity_id=doc.id, document_id=doc.id,
                            summary=f"{len(created)} insight(s) generated for {doc.filename}",
                            details={"insight_ids": created_ids, "methods": sorted({i.method for i in created})})
    for ins in created:
        audit_service.log_event(db, action="insight_created", user=user, entity_type="insight", entity_id=ins.id, document_id=doc.id,
                                confidence=ins.confidence, summary=f"{ins.severity.upper()} {ins.title}",
                                details={"method": ins.method, "evidence": ins.evidence, "confidence": ins.confidence_breakdown})
    db.flush()
    for ins in created:
        wf_engine.fire(db, "insight_created", {"insight": wf_engine.insight_ctx(ins), "document": wf_engine.document_ctx(doc, db)},
                       "insight", ins.id, user)
    return created


def scan_contradictions(db: Session, doc: Document, user: User | None = None) -> list[Contradiction]:
    """Compare this document's facts with every other READY document."""
    others = [d.id for d in db.query(Document.id).filter(Document.status.in_(("READY", "INDEXING")), Document.id != doc.id).all()]
    if not others:
        return []
    docs_by_id = {d.id: d for d in db.query(Document).filter(Document.id.in_([doc.id, *others])).all()}
    names = {i: d.filename for i, d in docs_by_id.items()}
    units = [TextUnit(c.id, c.document_id, names[c.document_id], c.page_number, c.text, docs_by_id[c.document_id].doc_type)
             for c in db.query(Chunk).filter(Chunk.document_id.in_([doc.id, *others])).all()]
    conflicts = [c for c in detect_conflicts(units) if doc.id in (c.evidence_a.unit.document_id, c.evidence_b.unit.document_id)]
    ids = persist_conflicts(db, [c.to_dict() for c in conflicts], None)
    rows = db.query(Contradiction).filter(Contradiction.id.in_(ids)).all() if ids else []
    for r in rows:
        audit_service.log_event(db, action="contradiction_detected", user=user, entity_type="contradiction", entity_id=r.id, document_id=doc.id,
                                confidence=r.confidence, summary=f"Conflict on '{r.topic}': {r.value_a} vs {r.value_b}",
                                details={"document_a": r.document_a_id, "document_b": r.document_b_id, "page_a": r.page_a, "page_b": r.page_b,
                                         "evidence_a": r.evidence_a, "evidence_b": r.evidence_b})
        wf_engine.fire(db, "contradiction_detected", {"contradiction": wf_engine.contradiction_ctx(r), "document": wf_engine.document_ctx(doc, db)},
                       "contradiction", r.id, user)
    return rows

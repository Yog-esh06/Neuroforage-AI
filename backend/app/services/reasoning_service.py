"""Question answering pipeline: hybrid retrieval -> grounded generation -> persistence -> audit."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.reasoning.grounded_generation import generate_grounded_answer
from app.ai.retrieval.metadata import MetadataFilter
from app.core.exceptions import ValidationFailed
from app.db.models.reasoning import Answer, Citation, Contradiction
from app.db.models.user import User
from app.knowledge.graph import get_graph
from app.schemas.evidence import Evidence
from app.services import audit_service
from app.services.search_service import hybrid_search


def graph_context_lines(db: Session, evidence: list[Evidence], limit: int = 40) -> list[str]:
    kg = get_graph(db)
    chunk_ids = {e.source_location.chunk_id for e in evidence}
    lines, seen = [], set()
    for u, v, d in kg.g.edges(data=True):
        if d.get("chunk_id") in chunk_ids and d["relation"] != "co_occurs_with":
            line = f"{kg.g.nodes[u]['name']} —{d['relation']}→ {kg.g.nodes[v]['name']} ({d['document']}, p.{d['page']})"
            if line not in seen:
                seen.add(line)
                lines.append(line)
    return lines[:limit]


def persist_conflicts(db: Session, conflicts: list[dict], query_id: int | None) -> list[int]:
    ids = []
    for c in conflicts:
        a, b = c["evidence_a"], c["evidence_b"]
        if a["document_id"] > b["document_id"]:  # canonical order => the same conflict is never stored twice
            a, b = b, a
            c = {**c, "value_a": c["value_b"], "value_b": c["value_a"]}
        existing = db.query(Contradiction).filter(
            Contradiction.topic == c["topic"], Contradiction.document_a_id == a["document_id"], Contradiction.document_b_id == b["document_id"],
            Contradiction.value_a == str(c["value_a"])[:200], Contradiction.value_b == str(c["value_b"])[:200]).first()
        if existing:
            ids.append(existing.id)
            continue
        row = Contradiction(topic=c["topic"], subject=c.get("subject"), kind=c["kind"], document_a_id=a["document_id"],
                            document_b_id=b["document_id"], chunk_a_id=a["chunk_id"], chunk_b_id=b["chunk_id"], page_a=a["page_number"],
                            page_b=b["page_number"], evidence_a=a["text"], evidence_b=b["text"], value_a=str(c["value_a"])[:200],
                            value_b=str(c["value_b"])[:200], confidence=c["confidence"], query_id=query_id)
        db.add(row)
        db.flush()
        ids.append(row.id)
    return ids


def ask(db: Session, question: str, *, user: User | None, filters: MetadataFilter | None = None, k: int = 8,
        weights: dict | None = None) -> dict[str, Any]:
    question = (question or "").strip()
    if len(question) < 3:
        raise ValidationFailed("Question is too short")
    if len(question) > 2000:
        raise ValidationFailed("Question is too long (max 2000 characters)")
    from app.ai.retrieval.query import understand

    if {"risk", "summary", "contradiction"} & set(understand(question).intents):
        k = max(k, 14)  # broad questions need broader evidence coverage
    res = hybrid_search(db, question, filters=filters, k=k, weights=weights, user=user, record=True)
    ans = generate_grounded_answer(question, res.evidence, graph_context=graph_context_lines(db, res.evidence),
                                   intents=res.understanding.intents)
    conf = ans["confidence"]
    row = Answer(query_id=res.query_id, retrieval_run_id=res.run_id, summary=ans["summary"], findings=ans["findings"],
                 refused=ans["refused"], confidence=conf["score"], confidence_level=conf["level"], confidence_breakdown=conf,
                 provider=ans["provider"], model=ans["model"], model_version=ans["model_version"], prompt_version=ans["prompt_version"],
                 validation={**ans["validation"], "refusal_reason": ans["refusal_reason"], "uncertainty_notes": ans["uncertainty_notes"]},
                 latency_ms=ans["latency_ms"])
    db.add(row)
    db.flush()
    for c in ans["citations"]:
        db.add(Citation(answer_id=row.id, marker=c["evidence_id"], document_id=c["document_id"], chunk_id=c["source_location"]["chunk_id"],
                        page_number=c["page_number"], section=c.get("section"), text=c["text"], relevance_score=c["relevance_score"],
                        retrieval_method=c["retrieval_method"], bbox=c["source_location"].get("bbox")))
    conflict_ids = persist_conflicts(db, [*ans["conflicts"], *ans["other_conflicts"]], res.query_id)
    audit_service.log_event(
        db, action="answer_generated", user=user, entity_type="answer", entity_id=row.id, query_text=question, model=ans["model"],
        model_version=ans["model_version"], prompt_version=ans["prompt_version"], confidence=conf["score"],
        summary=("Refused: " + ans["refusal_reason"]) if ans["refused"] else f"Answer with {len(ans['findings'])} finding(s)",
        details={"provider": ans["provider"], "retrieved_evidence": [{"id": e.evidence_id, "document_id": e.document_id, "page": e.page_number,
                                                                      "chunk_id": e.source_location.chunk_id, "score": e.relevance_score}
                                                                     for e in res.evidence],
                 "generated_result": {"summary": ans["summary"], "findings": ans["findings"]}, "validation": ans["validation"],
                 "confidence": conf, "conflict_ids": conflict_ids, "retrieval_run_id": res.run_id})
    db.commit()
    return {"answer_id": row.id, "query_id": res.query_id, "retrieval_run_id": res.run_id, "question": question, **ans,
            "conflict_ids": conflict_ids, "understanding": res.understanding.as_dict(), "strategies": res.strategies,
            "evidence": [e.model_dump() for e in res.evidence], "retrieval_latency_ms": res.latency_ms}

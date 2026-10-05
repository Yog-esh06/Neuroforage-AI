"""Semantic document comparison: clause alignment by embedding similarity, then typed change classification.

Not a raw text diff: sentences are aligned by meaning (greedy one-to-one on cosine similarity with a lexical guard),
matched clauses are compared by parsed values (money/dates/durations/percents), entities and obligation modality.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.ai.embeddings.encoder import get_encoder
from app.ai.extraction import values as V
from app.ai.extraction.entities import extract_entities
from app.ai.reasoning.contradiction import TextUnit, extract_facts
from app.core.exceptions import ValidationFailed
from app.db.models.document import Chunk, Document
from app.db.models.knowledge import Entity, EntityMention
from app.db.models.user import User
from app.services import audit_service
from app.services.document_service import get_document
from app.utils.text import split_sentences, stem_tokens

MATCH_SIM = 0.5
MAX_UNITS = 1500
_MODAL = re.compile(r"\b(shall not|must not|may not|shall|must|will|may|should|can|cannot|is required to|is not required to)\b", re.I)
_NEG = re.compile(r"\b(not|no|never|without|neither)\b", re.I)


def _units(db: Session, doc: Document) -> list[dict[str, Any]]:
    out = []
    for ch in db.query(Chunk).filter(Chunk.document_id == doc.id).order_by(Chunk.chunk_index).all():
        parts = ch.text.split("\n")[1:] if ch.chunk_type == "table" else split_sentences(ch.text)
        for p in parts:
            p = p.strip()
            if len(p) >= 12:
                out.append({"text": p, "page": ch.page_number, "chunk_id": ch.id, "section": ch.section})
    return out[:MAX_UNITS]


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower()).strip(" .;:")


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(stem_tokens(a)), set(stem_tokens(b))
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def _word_diff(a: str, b: str) -> list[dict[str, str]]:
    aw, bw = a.split(), b.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, bw, autojunk=False).get_opcodes():
        out.append({"op": op, "a": " ".join(aw[i1:i2]), "b": " ".join(bw[j1:j2])})
    return out


def _value_changes(a: str, b: str) -> list[dict[str, Any]]:
    va, vb = V.parse_all(a), V.parse_all(b)
    changes = []
    for kind in ("money", "date", "duration", "percent"):
        la, lb = [v for v in va if v.kind == kind], [v for v in vb if v.kind == kind]
        for x, y in zip(la, lb):
            same = (V.money_close(float(x.value), float(y.value)) if kind == "money" else
                    x.value == y.value if kind in ("date", "percent", "duration") else x.value == y.value)
            if not same:
                changes.append({"kind": kind, "from": x.raw, "to": y.raw, **_direction(x, y)})
        for y in lb[len(la):]:
            changes.append({"kind": kind, "from": None, "to": y.raw})
        for x in la[len(lb):]:
            changes.append({"kind": kind, "from": x.raw, "to": None})
    return changes


def _direction(x: V.ParsedValue, y: V.ParsedValue) -> dict[str, Any]:
    try:
        if x.kind in ("money", "percent", "duration"):
            fx, fy = float(x.value), float(y.value)
            return {"direction": "up" if fy > fx else "down", "delta_pct": round((fy - fx) / fx * 100, 1) if fx else None}
        if x.kind == "date":
            return {"direction": "later" if str(y.value) > str(x.value) else "earlier"}
    except (TypeError, ValueError):
        pass
    return {}


def _classify(a: str, b: str) -> tuple[list[str], list[dict]]:
    cats: list[str] = []
    vch = _value_changes(a, b)
    kinds = {c["kind"] for c in vch}
    if kinds & {"money", "percent"}:
        cats.append("changed_value")
    if "date" in kinds:
        cats.append("changed_date")
    if "duration" in kinds:
        cats.append("changed_duration")
    ea = {(e.type, e.canonical) for e in extract_entities(a, use_spacy=False) if e.type in ("ORG", "PERSON", "LOCATION", "PRODUCT", "CONTRACT", "REGULATION")}
    eb = {(e.type, e.canonical) for e in extract_entities(b, use_spacy=False) if e.type in ("ORG", "PERSON", "LOCATION", "PRODUCT", "CONTRACT", "REGULATION")}
    if ea != eb:
        cats.append("changed_entity")
    ma, mb = [m.lower() for m in _MODAL.findall(a)], [m.lower() for m in _MODAL.findall(b)]
    if ma != mb or bool(_NEG.search(a)) != bool(_NEG.search(b)):
        cats.append("changed_obligation")
    if not cats:
        cats.append("changed_clause")
    return cats, vch


def _align(ua: list[dict], ub: list[dict]) -> tuple[list[tuple[int, int, float]], set[int], set[int]]:
    if not ua or not ub:
        return [], set(range(len(ua))), set(range(len(ub)))
    enc = get_encoder()
    ea, eb = enc.encode([u["text"] for u in ua]), enc.encode([u["text"] for u in ub])
    sim = ea @ eb.T
    pairs = sorted(((float(sim[i, j]), i, j) for i in range(len(ua)) for j in range(len(ub)) if sim[i, j] >= MATCH_SIM), reverse=True)
    used_a, used_b, matches = set(), set(), []
    for s, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        if s < 0.8 and _jaccard(ua[i]["text"], ub[j]["text"]) < 0.25:
            continue
        used_a.add(i)
        used_b.add(j)
        matches.append((i, j, s))
    return matches, set(range(len(ua))) - used_a, set(range(len(ub))) - used_b


def _entity_sets(db: Session, doc_id: int) -> dict[str, str]:
    rows = (db.query(Entity.name, Entity.entity_type).join(EntityMention, EntityMention.entity_id == Entity.id)
            .filter(EntityMention.document_id == doc_id, Entity.entity_type.in_(("ORG", "PERSON", "LOCATION", "PRODUCT", "CONTRACT", "REGULATION", "TECHNOLOGY"))).distinct().all())
    return {f"{t}:{n}": n for n, t in rows}


def _key_facts(db: Session, a: Document, b: Document) -> list[dict[str, Any]]:
    def facts(doc: Document):
        units = [TextUnit(c.id, doc.id, doc.filename, c.page_number, c.text) for c in db.query(Chunk).filter(Chunk.document_id == doc.id).all()]
        out: dict[str, list] = {}
        for f in extract_facts(units):
            out.setdefault(f.topic, []).append(f)
        return out

    fa, fb = facts(a), facts(b)
    rows = []
    for topic in sorted(set(fa) | set(fb)):
        la, lb = fa.get(topic, []), fb.get(topic, [])
        va, vb = {str(f.value) for f in la}, {str(f.value) for f in lb}
        if la and lb:
            status = "unchanged" if va & vb else "changed"
        else:
            status = "added" if lb else "removed"
        pa, pb = (la[0] if la else None), (lb[0] if lb else None)
        row: dict[str, Any] = {"topic": topic, "status": status}
        for key, f in (("a", pa), ("b", pb)):
            row[key] = {"value": f.display, "page": f.unit.page, "text": f.sentence, "chunk_id": f.unit.chunk_id} if f else None
        if status == "changed" and pa and pb and pa.kind in ("money", "duration", "percent", "number"):
            try:
                row["direction"] = "up" if float(pb.value) > float(pa.value) else "down"
            except (TypeError, ValueError):
                pass
        elif status == "changed" and pa and pb and pa.kind == "date":
            row["direction"] = "later" if str(pb.value) > str(pa.value) else "earlier"
        rows.append(row)
    return rows


def compare_pair(db: Session, a: Document, b: Document) -> dict[str, Any]:
    ua, ub = _units(db, a), _units(db, b)
    matches, only_a, only_b = _align(ua, ub)
    changes: list[dict[str, Any]] = []
    unchanged = 0
    for i, j, s in matches:
        if _norm(ua[i]["text"]) == _norm(ub[j]["text"]):
            unchanged += 1
            continue
        cats, vch = _classify(ua[i]["text"], ub[j]["text"])
        changes.append({"type": "changed", "categories": cats, "similarity": round(s, 3), "value_changes": vch,
                        "a": {k: ua[i][k] for k in ("text", "page", "chunk_id", "section")}, "b": {k: ub[j][k] for k in ("text", "page", "chunk_id", "section")},
                        "diff": _word_diff(ua[i]["text"], ub[j]["text"])})
    for i in sorted(only_a):
        changes.append({"type": "removed", "categories": ["removed"], "similarity": 0.0, "value_changes": [], "a": {k: ua[i][k] for k in ("text", "page", "chunk_id", "section")}, "b": None, "diff": []})
    for j in sorted(only_b):
        changes.append({"type": "added", "categories": ["added"], "similarity": 0.0, "value_changes": [], "a": None, "b": {k: ub[j][k] for k in ("text", "page", "chunk_id", "section")}, "diff": []})
    ea, eb = _entity_sets(db, a.id), _entity_sets(db, b.id)
    cat_counts: dict[str, int] = {}
    for c in changes:
        for cat in c["categories"]:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
    order = {"changed_value": 0, "changed_date": 1, "changed_duration": 2, "changed_obligation": 3, "changed_entity": 4, "changed_clause": 5, "removed": 6, "added": 7}
    changes.sort(key=lambda c: min(order.get(x, 9) for x in c["categories"]))
    return {
        "document_a": {"id": a.id, "name": a.filename, "type": a.doc_type, "units": len(ua)},
        "document_b": {"id": b.id, "name": b.filename, "type": b.doc_type, "units": len(ub)},
        "summary": {"unchanged": unchanged, "changed": sum(1 for c in changes if c["type"] == "changed"),
                    "added": len(only_b), "removed": len(only_a), "by_category": cat_counts,
                    "similarity": round(unchanged / max(len(ua), len(ub), 1), 3)},
        "key_facts": _key_facts(db, a, b), "changes": changes,
        "entities": {"added": sorted(v for k, v in eb.items() if k not in ea), "removed": sorted(v for k, v in ea.items() if k not in eb),
                     "shared": len(set(ea) & set(eb))},
    }


def compare_documents(db: Session, doc_ids: list[int], user: User | None) -> dict[str, Any]:
    ids = list(dict.fromkeys(doc_ids))
    if len(ids) < 2:
        raise ValidationFailed("Select at least two distinct documents")
    if len(ids) > 5:
        raise ValidationFailed("At most 5 documents can be compared at once")
    docs = [get_document(db, i) for i in ids]
    for d in docs:
        if d.status != "READY":
            raise ValidationFailed(f"Document '{d.filename}' is not READY (status {d.status})")
    base, comps = docs[0], []
    for other in docs[1:]:
        comps.append(compare_pair(db, base, other))
    audit_service.log_event(db, action="documents_compared", user=user, entity_type="comparison", document_id=base.id,
                            summary=f"Compared {', '.join(d.filename for d in docs)}",
                            details={"document_ids": ids, "summaries": [c["summary"] for c in comps]})
    db.commit()
    return {"base_id": base.id, "comparisons": comps}

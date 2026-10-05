"""Chunk metadata cache + metadata filtering.

The cache holds one lightweight record per chunk of every READY document so that filtering, lexical indexing and
reranking features never touch the database on the hot path. It is invalidated on ingest/delete.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.document import Chunk, Document
from app.knowledge.graph import KnowledgeGraph


@dataclass
class ChunkRecord:
    id: int
    document_id: int
    filename: str
    doc_type: str
    page: int
    page_end: int | None
    section: str | None
    text: str
    chunk_type: str
    bbox: list[float] | None
    doc_created: datetime | None
    quality: float


@dataclass
class MetadataFilter:
    document_ids: list[int] | None = None
    document_types: list[str] | None = None
    page_min: int | None = None
    page_max: int | None = None
    content_date_from: str | None = None  # ISO date; matches chunks that mention a DATE within range
    content_date_to: str | None = None
    uploaded_from: str | None = None
    uploaded_to: str | None = None
    entities: list[str] = field(default_factory=list)  # entity names (canonicalised) — chunk must mention ALL
    section_contains: str | None = None
    chunk_types: list[str] | None = None

    def is_empty(self) -> bool:
        return not any([self.document_ids, self.document_types, self.page_min, self.page_max, self.content_date_from,
                        self.content_date_to, self.uploaded_from, self.uploaded_to, self.entities, self.section_contains,
                        self.chunk_types])


def source_quality(doc: Document) -> float:
    """Source reliability heuristic in [0,1]: native text > OCR; confident classification helps slightly."""
    text_q = 1.0 if not doc.ocr_used else min(1.0, max(0.3, (doc.ocr_confidence or 0.6)))
    return round(max(0.0, min(1.0, 0.55 + 0.25 * text_q + 0.2 * (doc.doc_type_confidence or 0.0))), 4)


class ChunkStore:
    def __init__(self):
        self._lock = threading.RLock()
        self.records: dict[int, ChunkRecord] = {}
        self.version = 0
        self._stale = True

    def invalidate(self) -> None:
        with self._lock:
            self._stale = True

    def ensure(self, db: Session) -> "ChunkStore":
        with self._lock:
            if not self._stale:
                return self
            docs = {d.id: d for d in db.query(Document).filter(Document.status.in_(["INDEXING", "READY"])).all()}
            recs: dict[int, ChunkRecord] = {}
            if docs:
                for c in db.query(Chunk).filter(Chunk.document_id.in_(list(docs))).all():
                    d = docs[c.document_id]
                    recs[c.id] = ChunkRecord(c.id, d.id, d.filename, d.doc_type, c.page_number, c.page_end, c.section, c.text,
                                             c.chunk_type, c.bbox, d.created_at, source_quality(d))
            self.records = recs
            self.version += 1
            self._stale = False
            return self


_store = ChunkStore()


def get_store(db: Session) -> ChunkStore:
    return _store.ensure(db)


def invalidate_store() -> None:
    _store.invalidate()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def apply_filter(store: ChunkStore, f: MetadataFilter | None, kg: KnowledgeGraph | None) -> set[int] | None:
    """Return the allowed chunk-id set, or None when no filtering is requested."""
    if f is None or f.is_empty():
        return None
    from app.utils.text import canonical_key

    up_from, up_to = _parse_dt(f.uploaded_from), _parse_dt(f.uploaded_to)
    want_ents = [canonical_key(e) for e in f.entities if e.strip()]
    ent_ids: list[set[int]] = []
    if want_ents and kg is not None:
        for w in want_ents:
            ids = set(kg.name_index.get(w, []))
            ent_ids.append(ids)

    allowed: set[int] = set()
    for cid, r in store.records.items():
        if f.document_ids and r.document_id not in f.document_ids:
            continue
        if f.document_types and r.doc_type not in f.document_types:
            continue
        if f.page_min and r.page < f.page_min:
            continue
        if f.page_max and r.page > f.page_max:
            continue
        if f.chunk_types and r.chunk_type not in f.chunk_types:
            continue
        if f.section_contains and f.section_contains.lower() not in (r.section or "").lower():
            continue
        if up_from and (r.doc_created is None or r.doc_created.replace(tzinfo=None) < up_from.replace(tzinfo=None)):
            continue
        if up_to and (r.doc_created is None or r.doc_created.replace(tzinfo=None) > up_to.replace(tzinfo=None)):
            continue
        if want_ents:
            ents_here = kg.chunk_entities.get(cid, set()) if kg else set()
            if not all(ids & ents_here for ids in ent_ids):
                continue
        if (f.content_date_from or f.content_date_to) and kg is not None:
            dates = [kg.g.nodes[e]["attributes"].get("iso") for e in kg.chunk_entities.get(cid, ()) if kg.g.nodes[e]["type"] == "DATE"]
            dates = [d for d in dates if d]
            lo, hi = (f.content_date_from or "0000")[:10], (f.content_date_to or "9999")[:10]
            if not any(lo <= d[: len(lo)] <= hi or lo <= d <= hi for d in dates):
                continue
        allowed.add(cid)
    return allowed

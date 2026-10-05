"""Constructs graph entities and relationships (persisted) from extraction output, with evidence on every edge."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.extraction.entities import EntityMention as Mention
from app.ai.extraction.entities import extract_entities, find_default_contract
from app.ai.extraction.relationships import extract_relationships
from app.db.models.document import Chunk
from app.db.models.knowledge import Entity, EntityMention, EntityRelationship
from app.knowledge.graph import invalidate_graph
from app.utils.text import canonical_key

log = logging.getLogger(__name__)

# Relationship types that carry real meaning; weak co-occurrence edges are kept but tagged low confidence.
MIN_STORE_CONFIDENCE = 0.3


@dataclass
class BuildStats:
    entities_created: int = 0
    mentions: int = 0
    relationships: int = 0


def clear_document_knowledge(db: Session, document_id: int) -> None:
    """Remove mentions/relationships contributed by a document and garbage-collect orphan entities."""
    db.query(EntityRelationship).filter(EntityRelationship.document_id == document_id).delete(synchronize_session=False)
    db.query(EntityMention).filter(EntityMention.document_id == document_id).delete(synchronize_session=False)
    db.flush()
    refresh_mention_counts(db)
    orphan_ids = [e.id for e in db.query(Entity.id).outerjoin(EntityMention, EntityMention.entity_id == Entity.id)
                  .group_by(Entity.id).having(func.count(EntityMention.id) == 0).all()]
    if orphan_ids:
        db.query(EntityRelationship).filter((EntityRelationship.source_id.in_(orphan_ids)) |
                                            (EntityRelationship.target_id.in_(orphan_ids))).delete(synchronize_session=False)
        db.query(Entity).filter(Entity.id.in_(orphan_ids)).delete(synchronize_session=False)
    invalidate_graph()


def refresh_mention_counts(db: Session) -> None:
    counts = dict(db.query(EntityMention.entity_id, func.count(EntityMention.id)).group_by(EntityMention.entity_id).all())
    for e in db.query(Entity).all():
        e.mention_count = counts.get(e.id, 0)


def _get_or_create_entity(db: Session, cache: dict, m: Mention) -> tuple[Entity, bool]:
    key = (m.canonical, m.type)
    if key in cache:
        ent = cache[key]
        if m.text != ent.name and m.text not in (ent.aliases or []) and len(ent.aliases or []) < 12:
            ent.aliases = [*(ent.aliases or []), m.text]
        return ent, False
    ent = db.query(Entity).filter(Entity.canonical_name == m.canonical, Entity.entity_type == m.type).first()
    created = False
    if ent is None:
        attrs = {k: v for k, v in m.normalized.items() if v is not None}
        ent = Entity(name=m.text, canonical_name=m.canonical, entity_type=m.type, aliases=[], attributes=attrs, mention_count=0)
        db.add(ent)
        db.flush()
        created = True
    elif m.text != ent.name and m.text not in (ent.aliases or []) and len(ent.aliases or []) < 12:
        ent.aliases = [*(ent.aliases or []), m.text]
    cache[key] = ent
    return ent, created


def build_for_chunks(db: Session, document_id: int, chunks: list[Chunk], *, use_spacy: bool = True) -> BuildStats:
    """Extract entities + relationships per chunk and persist them with chunk/page evidence."""
    stats = BuildStats()
    cache: dict[tuple[str, str], Entity] = {}
    clear_document_knowledge(db, document_id)
    default_contract = find_default_contract("\n".join(c.text for c in chunks))
    for ch in chunks:
        mentions = extract_entities(ch.text, use_spacy=use_spacy, default_contract=default_contract)
        if not mentions:
            continue
        ents: dict[int, Entity] = {}
        for i, m in enumerate(mentions):
            ent, created = _get_or_create_entity(db, cache, m)
            stats.entities_created += int(created)
            ents[i] = ent
            db.add(EntityMention(entity_id=ent.id, document_id=document_id, chunk_id=ch.id, page_number=ch.page_number,
                                 surface=m.text[:500], start=m.start, end=m.end, method=m.method, confidence=m.confidence))
            stats.mentions += 1
        idx = {id(m): i for i, m in enumerate(mentions)}
        for rel in extract_relationships(ch.text, mentions):
            if rel.confidence < MIN_STORE_CONFIDENCE:
                continue
            s_ent, t_ent = ents[idx[id(rel.source)]], ents[idx[id(rel.target)]]
            if s_ent.id == t_ent.id:
                continue
            db.add(EntityRelationship(source_id=s_ent.id, target_id=t_ent.id, relation=rel.relation, document_id=document_id,
                                      chunk_id=ch.id, page_number=ch.page_number, evidence_text=rel.evidence[:1200],
                                      confidence=rel.confidence, method=rel.method))
            stats.relationships += 1
    db.flush()
    refresh_mention_counts(db)
    invalidate_graph()
    return stats

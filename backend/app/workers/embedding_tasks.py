"""Re-embedding task: regenerate vectors for all chunks (e.g. after switching EMBEDDING_BACKEND/MODEL)."""
from __future__ import annotations

import numpy as np

from app.ai.embeddings.encoder import get_encoder
from app.db.models.document import Chunk, Embedding
from app.db.session import session_scope
from app.services.index_registry import invalidate_all
from app.workers.celery_app import celery_app


def reembed_all() -> dict:
    enc = get_encoder()
    n = 0
    with session_scope() as db:
        db.query(Embedding).delete(synchronize_session=False)
        chunks = db.query(Chunk).order_by(Chunk.id).all()
        for i in range(0, len(chunks), 64):
            batch = chunks[i:i + 64]
            vecs = enc.encode([f"{c.section or ''}\n{c.text}".strip() for c in batch])
            for c, v in zip(batch, vecs):
                db.add(Embedding(chunk_id=c.id, document_id=c.document_id, model=enc.name, dim=int(v.shape[0]), vector=np.asarray(v, dtype=np.float32).tobytes()))
                n += 1
    invalidate_all()
    return {"model": enc.name, "chunks": n}


@celery_app.task(name="app.workers.embedding_tasks.reembed_all_task")
def reembed_all_task() -> dict:
    return reembed_all()

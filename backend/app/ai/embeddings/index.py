"""In-memory exact (brute-force cosine) vector index, rebuilt lazily from the `embeddings` table.

Exact search is appropriate up to ~10^5-10^6 chunks on a single node; the interface (`search`) is what a FAISS/pgvector
index would implement, so swapping is local to this file.
"""
from __future__ import annotations

import threading

import numpy as np
from sqlalchemy.orm import Session

from app.db.models.document import Embedding


class VectorIndex:
    def __init__(self):
        self._lock = threading.RLock()
        self._matrix: np.ndarray | None = None
        self._chunk_ids: np.ndarray = np.zeros(0, dtype=np.int64)
        self._model: str | None = None
        self._stale = True

    def invalidate(self) -> None:
        with self._lock:
            self._stale = True

    def _ensure(self, db: Session, model: str) -> None:
        with self._lock:
            if not self._stale and self._model == model and self._matrix is not None:
                return
            rows = db.query(Embedding.chunk_id, Embedding.vector, Embedding.dim).filter(Embedding.model == model).all()
            if rows:
                dim = rows[0][2]
                self._matrix = np.vstack([np.frombuffer(r[1], dtype=np.float32, count=dim) for r in rows]).astype(np.float32)
                self._chunk_ids = np.array([r[0] for r in rows], dtype=np.int64)
            else:
                self._matrix = np.zeros((0, 1), dtype=np.float32)
                self._chunk_ids = np.zeros(0, dtype=np.int64)
            self._model = model
            self._stale = False

    def size(self, db: Session, model: str) -> int:
        self._ensure(db, model)
        return int(len(self._chunk_ids))

    def search(self, db: Session, model: str, query_vec: np.ndarray, k: int = 50,
               allowed_chunk_ids: set[int] | None = None) -> list[tuple[int, float]]:
        """Return [(chunk_id, cosine)] best-first, optionally restricted to `allowed_chunk_ids`."""
        self._ensure(db, model)
        with self._lock:
            m, ids = self._matrix, self._chunk_ids
        if m is None or len(ids) == 0 or m.shape[1] != query_vec.shape[0]:
            return []
        if allowed_chunk_ids is not None:
            mask = np.fromiter((int(i) in allowed_chunk_ids for i in ids), dtype=bool, count=len(ids))
            if not mask.any():
                return []
            sub_m, sub_ids = m[mask], ids[mask]
        else:
            sub_m, sub_ids = m, ids
        sims = sub_m @ query_vec.astype(np.float32)
        k = min(k, len(sims))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(int(sub_ids[i]), float(sims[i])) for i in top]

    def vector_for(self, db: Session, model: str, chunk_id: int) -> np.ndarray | None:
        self._ensure(db, model)
        with self._lock:
            hit = np.where(self._chunk_ids == chunk_id)[0]
            return None if len(hit) == 0 or self._matrix is None else self._matrix[hit[0]]


_index = VectorIndex()


def get_index() -> VectorIndex:
    return _index

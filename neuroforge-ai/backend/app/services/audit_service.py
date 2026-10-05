"""Append-only, hash-chained audit trail.

Each record's hash covers its content and the previous record's hash, so any later edit/deletion of a row breaks the chain
and is detectable with `verify_chain`. Records capture who did what, with which model/prompt version, which evidence was
retrieved, what was generated, the confidence and the human decision — enough to reconstruct how a conclusion was reached.
"""
from __future__ import annotations

import json
import threading
from datetime import timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import redact
from app.db.base import utcnow
from app.db.models.audit import AuditLog
from app.db.models.user import User
from app.utils.hashing import sha256_json, stable_json

_lock = threading.Lock()


def _naive_iso(ts) -> str:
    """UTC wall-clock ISO string. DB drivers differ: SQLite returns naive UTC, PostgreSQL returns aware datetimes in the
    session time zone — normalise to UTC first so the hash is identical wherever the row is read."""
    if ts is None:
        return ""
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc)
    return ts.replace(tzinfo=None).isoformat()


def _body(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: rec[k] for k in ("timestamp", "user_email", "action", "entity_type", "entity_id", "document_id", "query_text",
                                "model", "model_version", "prompt_version", "confidence", "summary", "details", "prev_hash")}


def log_event(db: Session, *, action: str, user: User | None = None, entity_type: str = "", entity_id: int | None = None,
              document_id: int | None = None, query_text: str | None = None, model: str | None = None,
              model_version: str | None = None, prompt_version: str | None = None, confidence: float | None = None,
              summary: str = "", details: dict[str, Any] | None = None) -> AuditLog:
    details = json.loads(stable_json(details or {}))  # normalise to JSON-safe types before hashing/storing
    with _lock:
        prev = db.query(AuditLog.hash).order_by(AuditLog.id.desc()).first()
        ts = utcnow()
        rec = {
            "timestamp": _naive_iso(ts), "user_email": user.email if user else "system", "action": action,
            "entity_type": entity_type, "entity_id": entity_id, "document_id": document_id,
            "query_text": redact(query_text) if query_text else None, "model": model, "model_version": model_version,
            "prompt_version": prompt_version, "confidence": round(confidence, 6) if confidence is not None else None,
            "summary": redact(summary), "details": details, "prev_hash": prev[0] if prev else "",
        }
        row = AuditLog(timestamp=ts, user_id=user.id if user and user.id else None, user_email=rec["user_email"], action=action,
                       entity_type=entity_type, entity_id=entity_id, document_id=document_id, query_text=rec["query_text"],
                       model=model, model_version=model_version, prompt_version=prompt_version, confidence=rec["confidence"],
                       summary=rec["summary"], details=details, prev_hash=rec["prev_hash"], hash=sha256_json(_body(rec)))
        db.add(row)
        db.flush()
        return row


def verify_chain(db: Session) -> dict[str, Any]:
    prev_hash = ""
    checked = 0
    for row in db.query(AuditLog).order_by(AuditLog.id.asc()).yield_per(500):
        rec = {"timestamp": _naive_iso(row.timestamp), "user_email": row.user_email, "action": row.action,
               "entity_type": row.entity_type, "entity_id": row.entity_id, "document_id": row.document_id,
               "query_text": row.query_text, "model": row.model, "model_version": row.model_version,
               "prompt_version": row.prompt_version, "confidence": row.confidence, "summary": row.summary,
               "details": json.loads(stable_json(row.details or {})), "prev_hash": row.prev_hash}
        if row.prev_hash != prev_hash or sha256_json(_body(rec)) != row.hash:
            return {"valid": False, "checked": checked, "first_broken_id": row.id}
        prev_hash = row.hash
        checked += 1
    return {"valid": True, "checked": checked, "first_broken_id": None}


def list_events(db: Session, *, action: str | None = None, document_id: int | None = None, user_email: str | None = None,
                entity_type: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0):
    qry = db.query(AuditLog)
    if action:
        qry = qry.filter(AuditLog.action == action)
    if document_id:
        qry = qry.filter(AuditLog.document_id == document_id)
    if user_email:
        qry = qry.filter(AuditLog.user_email == user_email)
    if entity_type:
        qry = qry.filter(AuditLog.entity_type == entity_type)
    if q:
        like = f"%{q}%"
        qry = qry.filter((AuditLog.summary.ilike(like)) | (AuditLog.query_text.ilike(like)))
    total = qry.count()
    rows = qry.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()
    return total, rows

"""Ingestion tasks + dispatcher. `enqueue_processing` is the only entry point the API uses."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings
from app.services.document_service import process_document
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)
_pool: ThreadPoolExecutor | None = None


@celery_app.task(name="app.workers.ingestion_tasks.process_document_task", bind=True, max_retries=2, default_retry_delay=15)
def process_document_task(self, document_id: int) -> None:
    process_document(document_id)  # records FAILED state itself; never raises


def enqueue_processing(document_id: int) -> str:
    """Returns the backend used: celery | inline | sync."""
    backend = get_settings().job_backend.lower()
    if backend == "celery":
        process_document_task.delay(document_id)
        return "celery"
    if backend == "sync":
        process_document(document_id)
        return "sync"
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest")
    _pool.submit(process_document, document_id)
    return "inline"

"""Celery application (used when JOB_BACKEND=celery). Start a worker with:

    celery -A app.workers.celery_app.celery_app worker -l info -Q ingestion,analysis -c 2
"""
from __future__ import annotations

from celery import Celery

from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging

s = get_settings()
setup_logging(s.log_level)

celery_app = Celery("neuroforge", broker=s.redis_url, backend=s.redis_url,
                    include=["app.workers.ingestion_tasks", "app.workers.embedding_tasks", "app.workers.analysis_tasks"])
if s.redis_url.startswith("filesystem://"):
    # Redis-free broker for local development / CI (kombu filesystem transport). Use `--pool=solo` on Windows.
    import os

    folder = os.environ.get("CELERY_FS_DIR", str(REPO_ROOT / "storage" / "celery"))
    os.makedirs(folder, exist_ok=True)
    celery_app.conf.broker_transport_options = {"data_folder_in": folder, "data_folder_out": folder, "control_folder": os.path.join(folder, "control")}
    celery_app.conf.result_backend = "cache+memory://"

celery_app.conf.update(
    task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True, task_time_limit=60 * 30,
    task_routes={"app.workers.ingestion_tasks.*": {"queue": "ingestion"}, "app.workers.embedding_tasks.*": {"queue": "ingestion"},
                 "app.workers.analysis_tasks.*": {"queue": "analysis"}},
    broker_connection_retry_on_startup=True,
)

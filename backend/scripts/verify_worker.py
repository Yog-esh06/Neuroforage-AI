"""End-to-end proof that the background-worker path works: API enqueues -> a real Celery worker process consumes -> READY.

Uses the filesystem broker so no Redis is required (REDIS_URL=filesystem://). With Redis available, run the same flow by
setting JOB_BACKEND=celery and REDIS_URL=redis://… and starting `make worker`.

    python backend/scripts/verify_worker.py        -> prints PASS/FAIL
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="neuroforge-worker-"))
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp / 'w.db').as_posix()}", "STORAGE_DIR": str(tmp / "docs"), "JOB_BACKEND": "celery",
           "REDIS_URL": "filesystem://", "CELERY_FS_DIR": str(tmp / "broker"), "AUTH_ENABLED": "false", "LOG_LEVEL": "INFO", "PYTHONPATH": str(REPO / "backend")}
    os.environ.update(env)
    sys.path.insert(0, str(REPO / "backend"))

    from fastapi.testclient import TestClient

    from app.main import create_app

    log = open(tmp / "worker.log", "w")
    worker = subprocess.Popen([sys.executable, "-m", "celery", "-A", "app.workers.celery_app.celery_app", "worker", "-l", "INFO", "--pool=solo",
                               "-Q", "ingestion,analysis"], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=str(REPO / "backend"))
    ok = False
    try:
        with TestClient(create_app()) as c:
            sample = REPO / "data" / "sample" / "invoice_inv2041.pdf"
            r = c.post("/api/v1/documents", files={"file": (sample.name, sample.read_bytes())})
            doc = r.json()["document"]
            print("API accepted upload; queue backend =", r.json().get("queue"), "| status =", doc["status"])
            deadline = time.time() + 120
            seen = []
            while time.time() < deadline:
                d = c.get(f"/api/v1/documents/{doc['id']}").json()
                tag = f"{d['status']}/{(d.get('job') or {}).get('stage')}"
                if not seen or seen[-1] != tag:
                    seen.append(tag)
                if d["status"] in ("READY", "FAILED"):
                    break
                time.sleep(0.5)
            print("observed:", " -> ".join(seen))
            ok = d["status"] == "READY" and r.json().get("queue") == "celery" and d["document_type"] == "Invoice"
            print("document_type:", d["document_type"], "| counts:", d["counts"])
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
        log.close()
    wl = (tmp / "worker.log").read_text(errors="ignore")
    consumed = "process_document_task" in wl and "succeeded" in wl
    print("worker consumed task:", consumed)
    print("WORKER PIPELINE:", "PASS" if ok and consumed else "FAIL")
    return 0 if ok and consumed else 1


if __name__ == "__main__":
    sys.exit(main())

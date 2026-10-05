"""Test harness: isolated SQLite DB + storage, synchronous job backend, real sample corpus."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="neuroforge-test-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}", "STORAGE_DIR": str(_TMP / "docs"), "ARTIFACTS_DIR": str(_TMP / "art"),
    "JOB_BACKEND": "sync", "AUTH_ENABLED": "true", "JWT_SECRET": "test-secret-not-for-production-use-0123456789",
    "SEED_ADMIN_EMAIL": "admin@test.local", "SEED_ADMIN_PASSWORD": "test-admin-password", "LLM_PROVIDER": "extractive",
    "EMBEDDING_BACKEND": "hashing", "APP_ENV": "development", "LOG_LEVEL": "WARNING", "MAX_UPLOAD_MB": "5",
})
if os.environ.get("NEUROFORGE_TEST_DATABASE_URL"):  # run the same suite against another database (scripts/verify_postgres.py)
    os.environ["DATABASE_URL"] = os.environ["NEUROFORGE_TEST_DATABASE_URL"]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "data" / "sample"


@pytest.fixture(scope="session", autouse=True)
def _sample_data():
    if not (SAMPLE / "master_services_agreement_acme_globex.pdf").exists():
        import subprocess

        subprocess.run([sys.executable, str(REPO / "backend" / "scripts" / "generate_sample_data.py")], check=True)


@pytest.fixture(scope="session")
def client():
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def admin(client):
    r = client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "test-admin-password"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(client, headers, path: Path):
    r = client.post("/api/v1/documents", headers=headers, files={"file": (path.name, path.read_bytes())})
    assert r.status_code in (200, 202), r.text
    return r.json()["document"]


@pytest.fixture(scope="session")
def corpus(client, admin):
    """Upload the whole sample corpus once (jobs run synchronously) and return {filename: document json}."""
    docs = {}
    for p in sorted(SAMPLE.iterdir()):
        if p.suffix == ".png":
            continue
        docs[p.name] = _upload(client, admin, p)
    out = {}
    for name, d in docs.items():
        r = client.get(f"/api/v1/documents/{d['id']}", headers=admin)
        out[name] = r.json()
    return out


@pytest.fixture()
def db():
    from app.db.session import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

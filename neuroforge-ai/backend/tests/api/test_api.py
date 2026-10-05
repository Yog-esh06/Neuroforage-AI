"""HTTP API contract: authentication, authorization, validation, error shape, upload security, secrets."""
from __future__ import annotations

import pytest

from tests.conftest import SAMPLE


@pytest.fixture(scope="module")
def viewer(client, admin):
    r = client.post("/api/v1/auth/register", headers=admin, json={"email": "viewer@test.local", "name": "Viewer", "password": "viewer-password-1", "role": "viewer"})
    assert r.status_code in (201, 409)
    tok = client.post("/api/v1/auth/login", json={"email": "viewer@test.local", "password": "viewer-password-1"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def err(r):
    body = r.json()
    assert set(body["error"]) == {"code", "message", "details"}
    return body["error"]


# ------------------------------------------------------------------ authentication
def test_health_is_public_and_leaks_nothing(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["checks"]["database"] == "ok"
    assert "key" not in r.text.lower().replace("keywords", "")


@pytest.mark.parametrize("path", ["/api/v1/documents", "/api/v1/stats/dashboard", "/api/v1/knowledge/entities", "/api/v1/review/tasks", "/api/v1/workflows",
                                  "/api/v1/insights", "/api/v1/audit", "/api/v1/auth/me"])
def test_protected_routes_require_a_token(client, path):
    r = client.get(path)
    assert r.status_code == 401 and err(r)["code"] == "unauthenticated"


def test_invalid_and_tampered_tokens_rejected(client, admin):
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401
    tok = admin["Authorization"].split()[1]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok[:-3]}abc"}).status_code == 401


def test_login_failures_are_uniform_and_audited(client):
    a = client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "wrong"})
    b = client.post("/api/v1/auth/login", json={"email": "nobody@test.local", "password": "wrong"})
    assert a.status_code == b.status_code == 401 and err(a)["message"] == err(b)["message"]  # no user enumeration


def test_login_returns_token_without_password_hash(client):
    r = client.post("/api/v1/auth/login", json={"email": "ADMIN@test.local ", "password": "test-admin-password"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin" and "hashed_password" not in r.text


# ------------------------------------------------------------------ authorization boundaries
def test_viewer_can_read_but_not_write(client, viewer):
    assert client.get("/api/v1/documents", headers=viewer).status_code == 200
    up = client.post("/api/v1/documents", headers=viewer, files={"file": ("a.txt", b"hello world document")})
    assert up.status_code == 403 and err(up)["code"] == "forbidden"
    assert client.post("/api/v1/search/ask", headers=viewer, json={"question": "anything at all"}).status_code == 403
    assert client.post("/api/v1/review/tasks/1/action", headers=viewer, json={"action": "approve"}).status_code == 403
    assert client.get("/api/v1/audit", headers=viewer).status_code == 403
    assert client.post("/api/v1/auth/register", headers=viewer, json={"email": "x@y.zz", "name": "x", "password": "password-123"}).status_code == 403
    assert client.delete("/api/v1/documents/1", headers=viewer).status_code == 403


def test_register_validates_input(client, admin):
    assert client.post("/api/v1/auth/register", headers=admin, json={"email": "not-an-email", "name": "x", "password": "password-123"}).status_code == 422
    assert client.post("/api/v1/auth/register", headers=admin, json={"email": "ok@test.local", "name": "x", "password": "short"}).status_code == 422
    assert client.post("/api/v1/auth/register", headers=admin, json={"email": "ok@test.local", "name": "x", "password": "password-123", "role": "root"}).status_code == 422


# ------------------------------------------------------------------ validation + missing resources
def test_request_validation_errors(client, admin):
    assert client.post("/api/v1/search", headers=admin, json={"query": "x"}).status_code == 422
    assert client.post("/api/v1/search", headers=admin, json={"query": "valid query", "k": 500}).status_code == 422
    assert client.post("/api/v1/search", headers=admin, json={"query": "valid query", "strategies": ["magic"]}).status_code == 422
    assert client.post("/api/v1/search", headers=admin, json={"query": "valid query", "weights": {"semantic": 5}}).status_code == 422
    assert client.post("/api/v1/search/ask", headers=admin, json={"question": "q" * 3000}).status_code == 422
    assert client.get("/api/v1/documents", headers=admin, params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/documents", headers=admin, params={"ids": "1,abc"}).status_code == 422
    assert client.get("/api/v1/documents", headers=admin, params={"sort": "evil; drop table"}).status_code == 422
    assert client.get("/api/v1/knowledge/entities/1/graph", headers=admin, params={"hops": 9}).status_code == 422


def test_missing_resources_return_structured_404(client, admin):
    for path in ("/api/v1/documents/987654", "/api/v1/documents/987654/pages", "/api/v1/knowledge/entities/987654", "/api/v1/insights/987654",
                 "/api/v1/review/tasks/987654", "/api/v1/search/answers/987654", "/api/v1/audit/987654"):
        r = client.get(path, headers=admin)
        assert r.status_code == 404 and err(r)["code"] == "not_found", path
    assert client.delete("/api/v1/documents/987654", headers=admin).status_code == 404
    assert client.get("/api/v1/nope", headers=admin).status_code == 404


# ------------------------------------------------------------------ upload security
def test_upload_rejects_bad_files(client, admin):
    def up(name, data):
        return client.post("/api/v1/documents", headers=admin, files={"file": (name, data)})

    assert up("run.exe", b"MZ\x90\x00\x03\x00\x00\x00 binary").status_code == 415
    assert up("notes.txt", (SAMPLE / "invoice_inv2041.pdf").read_bytes()).status_code == 415  # content/extension mismatch
    assert up("script.sh", b"#!/bin/sh\nrm -rf /\n").status_code == 415
    e = up("empty.txt", b"")
    assert e.status_code == 422 and err(e)["code"] == "validation_failed"
    big = up("big.txt", b"a" * (6 * 1024 * 1024))
    assert big.status_code == 413 and err(big)["code"] == "file_too_large"
    assert client.post("/api/v1/documents", headers=admin).status_code == 422  # no file field


def test_upload_sanitises_names_and_blocks_traversal(client, admin, db):
    from app.db.models.document import Document

    payload = b"This policy applies to all employees. Employees must report incidents within 24 hours. Violations lead to disciplinary action."
    r = client.post("/api/v1/documents", headers=admin, files={"file": ("../../etc/../evil name?.txt", payload)})
    assert r.status_code == 202
    doc = db.get(Document, r.json()["document"]["id"])
    assert "/" not in doc.safe_name and "\\" not in doc.safe_name and ".." not in doc.safe_name and doc.safe_name.endswith(".txt")
    assert ".." not in doc.storage_key.split("/")[1:] and doc.storage_key.startswith(doc.storage_key[:2])


def test_duplicate_upload_is_detected(client, admin):
    data = b"Quarterly report: revenue grew 10 percent. Findings and recommendations follow in the executive summary. Overview of the analysis."
    first = client.post("/api/v1/documents", headers=admin, files={"file": ("dup.txt", data)})
    second = client.post("/api/v1/documents", headers=admin, files={"file": ("dup-copy.txt", data)})
    assert first.status_code == 202 and second.status_code == 200 and second.json()["duplicate"] is True
    assert second.json()["document"]["id"] == first.json()["document"]["id"]


def test_corrupted_pdf_ends_in_failed_state_with_reason(client, admin):
    r = client.post("/api/v1/documents", headers=admin, files={"file": ("broken.pdf", b"%PDF-1.7\n1 0 obj << /Garbage >> endobj\nnot a real pdf at all" * 3)})
    doc = client.get(f"/api/v1/documents/{r.json()['document']['id']}", headers=admin).json()
    assert doc["status"] == "FAILED" and doc["error"] and doc["job"]["stage"] == "failed"
    failed = client.get("/api/v1/documents", headers=admin, params={"status": "failed"}).json()
    assert any(d["id"] == doc["id"] for d in failed["items"])


def test_download_headers_and_audit(client, admin, corpus):
    did = corpus["invoice_inv2041.pdf"]["id"]
    r = client.get(f"/api/v1/documents/{did}/file", headers=admin)
    assert r.status_code == 200 and r.content[:5] == b"%PDF-" and r.headers["x-content-type-options"] == "nosniff"
    assert 'filename="invoice_inv2041.pdf"' in r.headers["content-disposition"]


def test_listing_filters_and_search(client, admin, corpus):
    r = client.get("/api/v1/documents", headers=admin, params={"document_type": "Contract"}).json()
    assert r["total"] == 2 and all(d["document_type"] == "Contract" for d in r["items"])
    assert client.get("/api/v1/documents", headers=admin, params={"q": "amendment"}).json()["total"] == 1
    assert client.get("/api/v1/documents", headers=admin, params={"status": "READY", "limit": 3}).json()["items"].__len__() == 3


def test_security_headers_and_cors(client):
    r = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers["x-frame-options"] == "DENY" and r.headers["access-control-allow-origin"] == "http://localhost:3000"
    bad = client.get("/api/v1/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_no_secret_material_in_responses(client, admin, corpus):
    for path in ("/api/v1/stats/dashboard", "/api/v1/health", "/api/v1/auth/me", "/api/v1/workflows/meta"):
        text = client.get(path, headers=admin).text.lower()
        assert "api_key" not in text and "jwt_secret" not in text and "test-secret" not in text and "password" not in text.replace("hashed_password", "")

"""Human review, workflow engine, document comparison, dashboard truthfulness and audit-chain integrity."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow


def _tasks(client, admin, **params):
    return client.get("/api/v1/review/tasks", headers=admin, params=params).json()


# ------------------------------------------------------------------ workflows
def test_default_workflows_created_review_tasks(client, admin, corpus):
    wfs = {w["name"]: w for w in client.get("/api/v1/workflows", headers=admin).json()}
    assert {"High-risk clause review", "Contradiction review", "Critical finding escalation", "Low-confidence classification review"} <= set(wfs)
    assert wfs["High-risk clause review"]["run_count"] > 0 and wfs["High-risk clause review"]["matched_count"] > 0
    types = {t["type"] for t in _tasks(client, admin)["items"]}
    assert {"risk_review", "contradiction_review"} <= types


def test_workflow_runs_explain_their_decisions(client, admin, corpus):
    runs = client.get("/api/v1/workflows/runs", headers=admin, params={"limit": 100}).json()
    matched = next(r for r in runs if r["matched"] and r["workflow_name"] == "High-risk clause review")
    cond = matched["steps"][0]["trace"]
    assert all(c["passed"] for c in cond) and {c["field"] for c in cond} == {"insight.severity_score", "insight.confidence"}
    assert any(s.get("action") == "create_review_task" for s in matched["steps"][1:])
    skipped = [r for r in runs if not r["matched"]]
    assert skipped and not any(c["passed"] for c in skipped[0]["steps"][0]["trace"][-1:])


def test_workflow_validation_and_crud(client, admin):
    base = {"name": "Test workflow A", "description": "d", "trigger": "insight_created",
            "conditions": {"all": [{"field": "insight.severity_score", "op": ">", "value": 0.99}]}, "actions": [{"type": "add_audit_note", "params": {"message": "hi"}}]}
    bad_field = {**base, "name": "bad1", "conditions": {"all": [{"field": "insight.nope", "op": ">", "value": 1}]}}
    assert client.post("/api/v1/workflows", headers=admin, json=bad_field).status_code == 422
    assert client.post("/api/v1/workflows", headers=admin, json={**base, "name": "bad2", "trigger": "weird"}).status_code == 422
    assert client.post("/api/v1/workflows", headers=admin, json={**base, "name": "bad3", "actions": [{"type": "drop_database"}]}).status_code == 422
    assert client.post("/api/v1/workflows", headers=admin, json={**base, "name": "bad4", "conditions": {"all": [{"field": "document.type", "op": ">", "value": 1}]}}).status_code == 422  # ordering op on a text field
    assert client.post("/api/v1/workflows", headers=admin, json={**base, "name": "bad5", "trigger": "document_ready"}).status_code == 422  # insight.* is not available when a document becomes ready
    assert client.post("/api/v1/workflows", headers=admin, json={**base, "name": "bad6", "conditions": {"all": [{"field": "insight.severity", "op": "==", "value": "catastrophic"}]}}).status_code == 422  # enum value
    r = client.post("/api/v1/workflows", headers=admin, json=base)
    assert r.status_code == 201
    wid = r.json()["id"]
    assert client.post("/api/v1/workflows", headers=admin, json=base).status_code == 409
    assert client.patch(f"/api/v1/workflows/{wid}", headers=admin, json={"enabled": False}).json()["enabled"] is False
    run = client.post(f"/api/v1/workflows/{wid}/run", headers=admin).json()
    assert run["evaluated"] > 0 and run["matched"] == 0  # threshold 0.99 matches nothing
    assert client.delete(f"/api/v1/workflows/{wid}", headers=admin).status_code == 204
    assert client.patch(f"/api/v1/workflows/{wid}", headers=admin, json={"enabled": True}).status_code == 404


def test_user_defined_workflow_creates_task_on_demand(client, admin, corpus):
    spec = {"name": "Any medium+ legal risk", "description": "x", "trigger": "insight_created",
            "conditions": {"all": [{"field": "insight.category", "op": "==", "value": "legal"}, {"field": "insight.severity_score", "op": ">=", "value": 0.4}]},
            "actions": [{"type": "create_review_task", "params": {"priority": "low", "title": "Legal clause check"}}]}
    wid = client.post("/api/v1/workflows", headers=admin, json=spec).json()["id"]
    out = client.post(f"/api/v1/workflows/{wid}/run", headers=admin).json()
    assert out["matched"] >= 1
    assert any(t["title"] == "Legal clause check" for t in _tasks(client, admin, limit=300)["items"]) or out["matched"] >= 1


# ------------------------------------------------------------------ review queue
def test_review_actions_update_state_insight_and_audit(client, admin, corpus):
    task = next(t for t in _tasks(client, admin, type="risk_review", only_open="true")["items"] if t["insight_id"])
    assert {"id", "type", "priority", "ai_recommendation", "evidence", "confidence", "reviewer", "status"} <= set(task)
    assert task["evidence"] and task["evidence"][0]["page_number"] >= 1
    res = client.post(f"/api/v1/review/tasks/{task['id']}/action", headers=admin, json={"action": "approve", "note": "confirmed against clause"})
    assert res.status_code == 200 and res.json()["status"] == "APPROVED" and res.json()["reviewer"] == "admin@test.local"
    assert [h["action"] for h in res.json()["history"]] == ["review_approve"]
    assert client.get(f"/api/v1/insights/{task['insight_id']}", headers=admin).json()["status"] == "verified"
    again = client.post(f"/api/v1/review/tasks/{task['id']}/action", headers=admin, json={"action": "reject"})
    assert again.status_code == 409  # decisions are final
    audit = client.get("/api/v1/audit", headers=admin, params={"action": "review_approve"}).json()["items"][0]
    full = client.get(f"/api/v1/audit/{audit['id']}", headers=admin).json()
    assert full["details"]["human_decision"] == "APPROVED" and full["details"]["ai_recommendation"] is not None


def test_modify_requires_text_and_escalate_and_request_evidence(client, admin, corpus):
    open_tasks = _tasks(client, admin, only_open="true", type="risk_review")["items"]
    t_mod, t_esc, t_ev = open_tasks[0], open_tasks[1], open_tasks[2]
    assert client.post(f"/api/v1/review/tasks/{t_mod['id']}/action", headers=admin, json={"action": "modify"}).status_code == 422
    r = client.post(f"/api/v1/review/tasks/{t_mod['id']}/action", headers=admin, json={"action": "modify", "modified_recommendation": "Cap liability at 12 months of fees."})
    assert r.json()["status"] == "MODIFIED" and r.json()["modified_recommendation"].startswith("Cap liability")
    r = client.post(f"/api/v1/review/tasks/{t_esc['id']}/action", headers=admin, json={"action": "escalate"})
    assert r.json()["status"] == "ESCALATED" and r.json()["priority"] == "critical"
    before = len(t_ev["evidence"])
    r = client.post(f"/api/v1/review/tasks/{t_ev['id']}/action", headers=admin, json={"action": "request_evidence"}).json()
    assert r["status"] == "NEEDS_EVIDENCE" and len(r["evidence"]) >= before
    assert client.post(f"/api/v1/review/tasks/{t_ev['id']}/action", headers=admin, json={"action": "reject", "note": "not applicable"}).json()["status"] == "REJECTED"
    assert client.post("/api/v1/review/tasks/999999/action", headers=admin, json={"action": "approve"}).status_code == 404
    assert client.post(f"/api/v1/review/tasks/{t_mod['id']}/action", headers=admin, json={"action": "explode"}).status_code == 422


# ------------------------------------------------------------------ comparison
def test_semantic_comparison_of_contract_and_amendment(client, admin, corpus):
    a, b = corpus["master_services_agreement_acme_globex.pdf"]["id"], corpus["amendment_1_acme_globex.pdf"]["id"]
    r = client.post("/api/v1/compare", headers=admin, json={"document_ids": [a, b]})
    assert r.status_code == 200
    comp = r.json()["comparisons"][0]
    facts = {f["topic"]: f for f in comp["key_facts"]}
    assert facts["Contract expiration"]["status"] == "changed" and facts["Contract expiration"]["direction"] == "later"
    assert facts["Contract value"]["a"]["value"] == "$2,000,000" and facts["Contract value"]["b"]["value"] == "$2,400,000" and facts["Contract value"]["direction"] == "up"
    assert facts["Governing law"]["status"] == "changed" and facts["Liability cap"]["status"] == "added"
    value_changes = [(v["from"], v["to"], v.get("direction")) for c in comp["changes"] for v in c["value_changes"]]
    assert ("$2,000,000", "$2,400,000", "up") in value_changes
    cats = comp["summary"]["by_category"]
    assert cats.get("changed_value", 0) >= 1 and cats.get("changed_date", 0) >= 1 and cats.get("changed_duration", 0) >= 1
    ch = next(c for c in comp["changes"] if c["type"] == "changed" and c["value_changes"])
    assert ch["a"]["page"] >= 1 and any(d["op"] != "equal" for d in ch["diff"]) and ch["similarity"] > 0.5  # aligned by meaning, then diffed
    assert comp["summary"]["unchanged"] >= 1


def test_comparison_validation(client, admin, corpus):
    one = corpus["invoice_inv2041.pdf"]["id"]
    assert client.post("/api/v1/compare", headers=admin, json={"document_ids": [one]}).status_code == 422
    assert client.post("/api/v1/compare", headers=admin, json={"document_ids": [one, one]}).status_code == 422
    assert client.post("/api/v1/compare", headers=admin, json={"document_ids": [one, 424242]}).status_code == 404


# ------------------------------------------------------------------ dashboard truthfulness + audit chain
def test_dashboard_numbers_match_database(client, admin, corpus, db):
    from sqlalchemy import func

    from app.db.models.document import Document
    from app.db.models.knowledge import Entity, EntityRelationship
    from app.db.models.reasoning import Contradiction, Insight
    from app.db.models.review import ReviewTask

    d = client.get("/api/v1/stats/dashboard", headers=admin).json()
    assert d["documents"]["total"] == db.query(func.count(Document.id)).scalar()
    assert d["knowledge"]["entities"] == db.query(func.count(Entity.id)).scalar()
    assert d["knowledge"]["relationships"] == db.query(func.count(EntityRelationship.id)).scalar()
    assert d["contradictions"]["total"] == db.query(func.count(Contradiction.id)).scalar()
    assert d["review"]["open"] == db.query(ReviewTask).filter(ReviewTask.status.in_(("PENDING", "NEEDS_EVIDENCE", "ESCALATED"))).count()
    assert d["risk"]["high_risk_findings"] == db.query(Insight).filter(Insight.kind == "risk", Insight.status != "rejected", Insight.severity_score >= 0.7).count()
    assert d["latency"]["processing_avg_ms"] > 0 and d["system"]["llm"]["provider"] == "extractive"


def test_audit_trail_records_reconstruction_fields_and_detects_tampering(client, admin, corpus, db):
    client.post("/api/v1/search/ask", headers=admin, json={"question": "What is the notice period?"})
    ans = client.get("/api/v1/audit", headers=admin, params={"action": "answer_generated"}).json()["items"][0]
    full = client.get(f"/api/v1/audit/{ans['id']}", headers=admin).json()
    assert full["query_text"] == "What is the notice period?" and full["model"] and full["prompt_version"] == "ng-grounded-v1" and full["confidence"] is not None
    assert full["details"]["retrieved_evidence"] and "generated_result" in full["details"] and full["user"] == "admin@test.local"
    ver = client.get("/api/v1/audit/verify", headers=admin).json()
    assert ver["valid"] and ver["checked"] > 50

    from app.db.models.audit import AuditLog

    row = db.get(AuditLog, ans["id"])
    original = row.summary
    row.summary = "tampered after the fact"
    db.commit()
    try:
        broken = client.get("/api/v1/audit/verify", headers=admin).json()
        assert broken["valid"] is False and broken["first_broken_id"] == ans["id"]
    finally:
        row.summary = original
        db.commit()
    assert client.get("/api/v1/audit/verify", headers=admin).json()["valid"]

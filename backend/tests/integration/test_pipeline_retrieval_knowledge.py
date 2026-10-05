"""End-to-end over the real sample corpus: ingestion results, retrieval strategies, graph, insights, contradictions."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow

EXPECTED_TYPES = {
    "master_services_agreement_acme_globex.pdf": "Contract", "amendment_1_acme_globex.pdf": "Contract", "invoice_inv2041.pdf": "Invoice",
    "invoice_inv2042_total_error.pdf": "Invoice", "scanned_invoice_inv3307.pdf": "Invoice", "research_paper_hybrid_retrieval.pdf": "Research Paper",
    "annual_report_fy2025.pdf": "Financial Report", "information_security_policy.txt": "Policy", "resume_jane_doe.docx": "Resume",
}


def _search(client, admin, query, **kw):
    r = client.post("/api/v1/search", headers=admin, json={"query": query, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _id(corpus, name):
    return corpus[name]["id"]


# ------------------------------------------------------------------ ingestion results
def test_every_document_reaches_ready_with_expected_type(corpus):
    for name, d in corpus.items():
        assert d["status"] == "READY", (name, d["error"])
        if name in EXPECTED_TYPES:
            assert d["document_type"] == EXPECTED_TYPES[name], name
            assert d["classification_method"].startswith("lexicon+structure")
            assert d["classification_confidence"] > 0.5


def test_scanned_document_used_ocr_and_native_did_not(corpus):
    assert corpus["scanned_invoice_inv3307.pdf"]["ocr_used"] is True
    assert corpus["invoice_inv2041.pdf"]["ocr_used"] is False


def test_page_endpoints_expose_layout_entities_tables_and_image(client, admin, corpus):
    did = _id(corpus, "master_services_agreement_acme_globex.pdf")
    page = client.get(f"/api/v1/documents/{did}/pages/1", headers=admin).json()
    types = {e["type"] for e in page["elements"]}
    assert {"heading", "paragraph", "table", "footer"} <= types
    assert any(e["bbox"] for e in page["elements"])  # bounding boxes retained for citations
    table = next(e for e in page["elements"] if e["type"] == "table")["table"]
    assert table["headers"] == ["Milestone", "Due Date", "Amount"] and table["profile"]["columns"][2]["type"] == "money"
    assert {"Acme Corp", "Globex Industries Ltd"} <= {e["name"] for e in page["entities"]}
    img = client.get(f"/api/v1/documents/{did}/pages/1/image", headers=admin)
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/v1/documents/{did}/pages/99", headers=admin).status_code == 404


def test_table_total_mismatch_detected_only_on_the_wrong_invoice(client, admin, corpus):
    bad = client.get(f"/api/v1/documents/{_id(corpus, 'invoice_inv2042_total_error.pdf')}/insights", headers=admin).json()["insights"]
    good = client.get(f"/api/v1/documents/{_id(corpus, 'invoice_inv2041.pdf')}/insights", headers=admin).json()["insights"]
    mism = [i for i in bad if i["category"] == "totals_mismatch"]
    assert mism and "19,500.00" in mism[0]["description"] and "18,000.00" in mism[0]["description"]
    assert mism[0]["evidence"][0]["page_number"] == 1
    assert not [i for i in good if i["category"] == "totals_mismatch"]


# ------------------------------------------------------------------ retrieval strategies
def test_semantic_retrieval_finds_expiry_clause(client, admin, corpus):
    res = _search(client, admin, "when does the agreement terminate", strategies=["semantic"], k=5)
    assert res["results"][0]["document_type"] == "Contract"
    assert all(r["retrieval_method"] == "semantic" for r in res["results"])


def test_lexical_retrieval_exact_identifiers(client, admin, corpus):
    res = _search(client, admin, "INV-2041", strategies=["lexical"], k=3)
    assert res["results"][0]["document_name"] == "invoice_inv2041.pdf"
    res = _search(client, admin, "liquidated damages", strategies=["lexical"], k=5)
    assert {r["document_name"] for r in res["results"]} >= {"master_services_agreement_acme_globex.pdf"}


def test_hybrid_retrieval_combines_strategies_and_reports_features(client, admin, corpus):
    res = _search(client, admin, "late payment interest rate", k=6)
    assert res["strategies"]["semantic"]["candidates"] > 0 and res["strategies"]["lexical"]["candidates"] > 0
    top = res["results"][0]
    assert "lexical" in top["retrieval_method"] and "semantic" in top["retrieval_method"]
    assert set(top["features"]) == {"semantic", "lexical", "metadata", "entity", "graph", "recency", "quality"}
    scores = [r["relevance_score"] for r in res["results"]]
    assert scores == sorted(scores, reverse=True) and all(0 <= s <= 1 for s in scores)
    assert top["source_location"]["chunk_id"] and top["page_number"] >= 1 and top["document_name"]


def test_graph_retrieval_links_query_entities(client, admin, corpus):
    res = _search(client, admin, "What did Globex Industries Ltd agree to?", k=6)
    assert any(e["name"] == "Globex Industries Ltd" for e in res["linked_entities"])
    assert res["strategies"]["graph"]["candidates"] > 0
    assert any("graph" in r["retrieval_method"] for r in res["results"])


def test_metadata_filters(client, admin, corpus):
    inv = _search(client, admin, "total amount due", filters={"document_types": ["Invoice"]}, k=10)
    assert inv["results"] and {r["document_type"] for r in inv["results"]} == {"Invoice"}
    one = _id(corpus, "annual_report_fy2025.pdf")
    only = _search(client, admin, "revenue", filters={"document_ids": [one]}, k=10)
    assert {r["document_id"] for r in only["results"]} == {one}
    ent = _search(client, admin, "payment", filters={"entities": ["Acme Corp"]}, k=10)
    assert ent["results"] and all("Acme" in r["text"] or any(e["name"] == "Acme Corp" for e in r["entities"]) for r in ent["results"])
    assert _search(client, admin, "payment", filters={"page_min": 50}, k=5)["results"] == []
    tbl = _search(client, admin, "milestone amount", filters={"chunk_types": ["table"]}, k=5)
    assert tbl["results"] and all("columns:" in r["text"] for r in tbl["results"])


def test_reranking_differs_from_raw_embedding_order(client, admin, corpus):
    only_sem = _search(client, admin, "governing law", strategies=["semantic"], k=8)
    hybrid = _search(client, admin, "governing law", k=8)
    assert hybrid["results"][0]["section"] and "Governing Law" in hybrid["results"][0]["section"]
    assert only_sem["results"] and hybrid["results"]


# ------------------------------------------------------------------ knowledge graph
def test_entity_relationships_carry_evidence(client, admin, corpus, db):
    from app.db.models.knowledge import Entity, EntityRelationship

    acme = db.query(Entity).filter(Entity.canonical_name == "acme", Entity.entity_type == "ORG").one()
    assert acme.mention_count >= 4
    rels = db.query(EntityRelationship).all()
    assert rels and all(r.evidence_text.strip() and r.document_id and r.page_number >= 1 for r in rels)
    detail = client.get(f"/api/v1/knowledge/entities/{acme.id}", headers=admin).json()
    relations = {(r["relation"], r["other"]["name"]) for r in detail["relationships"]}
    assert ("party_to", "Master Services Agreement") in relations
    assert {d["document"] for d in detail["documents"]} >= {"master_services_agreement_acme_globex.pdf", "amendment_1_acme_globex.pdf"}
    assert detail["evidence"] and all(e["text"] for e in detail["evidence"])


def test_multi_hop_traversal_and_paths(client, admin, corpus):
    ents = client.get("/api/v1/knowledge/entities", headers=admin, params={"q": "Acme"}).json()
    acme = next(e for e in ents if e["name"] == "Acme Corp")
    g1 = client.get(f"/api/v1/knowledge/entities/{acme['id']}/graph", headers=admin, params={"hops": 1}).json()
    g2 = client.get(f"/api/v1/knowledge/entities/{acme['id']}/graph", headers=admin, params={"hops": 2}).json()
    assert len(g2["nodes"]) >= len(g1["nodes"]) > 1 and g1["edges"]
    assert any(n["is_center"] and n["name"] == "Acme Corp" for n in g1["nodes"])
    sing = client.get("/api/v1/knowledge/entities", headers=admin, params={"q": "Singapore"}).json()[0]
    paths = client.get("/api/v1/knowledge/paths", headers=admin, params={"source": acme["id"], "target": sing["id"]}).json()
    assert paths and paths[0]["hops"] >= 2 and all(s["evidence"] for s in paths[0]["steps"])  # Acme -> Globex -> Singapore
    assert client.get("/api/v1/knowledge/entities/999999", headers=admin).status_code == 404


# ------------------------------------------------------------------ contradictions & insights
def test_contradictions_between_contract_and_amendment(client, admin, corpus):
    items = client.get("/api/v1/insights/contradictions", headers=admin).json()["items"]
    by_topic = {c["topic"]: c for c in items}
    exp = by_topic["Contract expiration"]
    assert {exp["evidence_a"]["value"], exp["evidence_b"]["value"]} == {"June 30, 2027", "September 30, 2027"}
    assert {exp["evidence_a"]["document_name"], exp["evidence_b"]["document_name"]} == {"master_services_agreement_acme_globex.pdf", "amendment_1_acme_globex.pdf"}
    assert "Contract value" in by_topic and "Governing law" in by_topic and 0.5 < exp["confidence"] <= 0.97
    inv = {corpus["invoice_inv2041.pdf"]["id"], corpus["invoice_inv2042_total_error.pdf"]["id"]}
    assert not [c for c in items if {c["evidence_a"]["document_id"], c["evidence_b"]["document_id"]} == inv]
    assert len([c for c in items if c["topic"] == "Contract expiration"]) == 1  # stored once, not per direction


def test_risk_insights_have_evidence_and_respect_negation(client, admin, corpus):
    ins = client.get("/api/v1/insights", headers=admin, params={"kind": "risk", "limit": 200}).json()["items"]
    assert ins and all(i["evidence"] and i["evidence"][0]["page_number"] >= 1 and i["method"].startswith("rule:") for i in ins)
    assert all("no substantial doubt" not in i["description"] for i in ins)  # negated 'going concern' must not be flagged
    titles = {i["title"] for i in ins}
    assert {"Penalty or liquidated damages", "Automatic renewal clause"} <= titles
    assert any(i["severity"] == "critical" for i in ins)


# ------------------------------------------------------------------ grounded answers
def test_grounded_answer_cites_real_evidence(client, admin, corpus):
    r = client.post("/api/v1/search/ask", headers=admin, json={"question": "What are the major financial risks mentioned across these documents?"})
    assert r.status_code == 200
    a = r.json()
    assert not a["refused"] and a["findings"] and a["validation"]["citation_coverage"] == 1.0
    ev_ids = {e["evidence_id"] for e in a["evidence"]}
    for f in a["findings"]:
        assert f["confidence"]["level"] in ("HIGH", "MEDIUM", "LOW") and "calibrated" in f["confidence"]["disclaimer"]
        for s in f["statements"]:
            assert set(s["evidence"]) <= ev_ids
    for c in a["citations"]:
        assert c["marker"].startswith("[") and "Page" in c["marker"] and c["page_number"] >= 1
    saved = client.get(f"/api/v1/search/answers/{a['answer_id']}", headers=admin).json()
    assert saved["citations"] and saved["prompt_version"] and saved["provider"] == "extractive"


def test_unanswerable_question_is_refused_not_invented(client, admin, corpus):
    a = client.post("/api/v1/search/ask", headers=admin, json={"question": "zxqv plorbnax wibble frumious quuxbar"}).json()
    assert a["refused"] and not a["findings"] and a["confidence"]["level"] == "LOW"


def test_conflicting_sources_surface_in_answer(client, admin, corpus):
    a = client.post("/api/v1/search/ask", headers=admin, json={"question": "When does the contract expire?"}).json()
    topics = {c["topic"] for c in a["conflicts"]}
    assert "Contract expiration" in topics
    vals = " ".join(s["text"] for f in a["findings"] for s in f["statements"])
    assert "June 30, 2027" in vals and "September 30, 2027" in vals  # both sides reported, none silently chosen

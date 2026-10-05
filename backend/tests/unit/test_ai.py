"""AI layer: grounded generation, unsupported claims, contradictions, confidence, classification, reranking, extraction."""
from __future__ import annotations

import json

import pytest

from app.ai.extraction import values as V
from app.ai.extraction.classifier import classify
from app.ai.extraction.entities import extract_entities
from app.ai.extraction.relationships import extract_relationships
from app.ai.providers.base import GenerationRequest, LLMProvider, LLMResult
from app.ai.reasoning.confidence import ConfidenceInput, compute_confidence
from app.ai.reasoning.contradiction import TextUnit, detect_conflicts
from app.ai.reasoning.grounded_generation import generate_grounded_answer
from app.ai.reasoning.risk_rules import scan_sentence
from app.ai.retrieval.metadata import ChunkRecord
from app.ai.retrieval.query import understand
from app.ai.retrieval.reranker import Candidate, rerank
from app.schemas.evidence import Evidence, SourceLocation


def ev(i: int, text: str, doc: int = 1, page: int = 1, score: float = 0.7, name: str = "Doc A.pdf") -> Evidence:
    return Evidence(document_id=doc, document_name=name, page_number=page, text=text, relevance_score=score, retrieval_method="semantic",
                    source_location=SourceLocation(chunk_id=i), features={"quality": 0.9})


class FakeLLM(LLMProvider):
    name, model = "fake", "fake-1"

    def __init__(self, payload: dict | str):
        self.payload = payload

    def generate(self, req: GenerationRequest) -> LLMResult:
        return LLMResult(self.payload if isinstance(self.payload, str) else json.dumps(self.payload), self.name, self.model, "v1")


# ------------------------------------------------------------------ grounded generation
def test_fabricated_citations_and_unsupported_claims_are_removed():
    evidence = [ev(1, "The agreement expires on June 30, 2027 unless renewed.")]
    llm = FakeLLM({"summary": "The agreement expires on June 30, 2027. The CEO resigned in 2025.", "refused": False, "findings": [{
        "title": "Expiry", "severity": "low", "statements": [
            {"text": "The agreement expires on June 30, 2027.", "type": "fact", "evidence": ["E1"]},
            {"text": "The agreement expires on September 1, 2030.", "type": "fact", "evidence": ["E1"]},      # wrong value
            {"text": "The CEO resigned in 2025.", "type": "fact", "evidence": ["E9"]},                          # fabricated citation id
            {"text": "Penalties of $5,000,000 apply.", "type": "fact", "evidence": []}]}]})            # no citation
    out = generate_grounded_answer("When does it expire?", evidence, provider=llm, intents=["date"])
    texts = [s["text"] for f in out["findings"] for s in f["statements"]]
    assert texts == ["The agreement expires on June 30, 2027."]
    reasons = " | ".join(c["reason"] for c in out["validation"]["unsupported_claims"])
    assert "values not in cited evidence" in reasons and "no valid citation" in reasons
    assert out["validation"]["stripped_citations"][0]["invalid_ids"] == ["E9"]
    assert "CEO" not in out["summary"]
    assert [c["evidence_id"] for c in out["citations"]] == ["E1"]  # citations only come from real evidence
    assert out["validation"]["citation_coverage"] == pytest.approx(0.25, abs=0.01)


def test_everything_unsupported_leads_to_refusal():
    out = generate_grounded_answer("q", [ev(1, "Totally unrelated text about gardening.")], provider=FakeLLM({
        "summary": "x", "findings": [{"title": "t", "statements": [{"text": "Revenue was $9 billion.", "type": "fact", "evidence": ["E1"]}]}]}))
    assert out["refused"] and not out["findings"] and "verified" in out["refusal_reason"]


def test_no_evidence_refuses_without_calling_for_guesses():
    out = generate_grounded_answer("What is the penalty?", [])
    assert out["refused"] and out["confidence"]["level"] == "LOW"


def test_invalid_llm_json_falls_back_to_extractive():
    evidence = [ev(1, "Late payments accrue interest at 2% per month.")]
    out = generate_grounded_answer("What is the late payment interest?", evidence, provider=FakeLLM("not json at all"), intents=[])
    assert out["validation"]["fallback"] and out["provider"] == "extractive"
    assert out["findings"] and "2%" in out["findings"][0]["statements"][0]["text"]


def test_extractive_composer_only_emits_verbatim_evidence_sentences():
    evidence = [ev(1, "Revenue was $48.2 million. The office dog is called Rex. Net income was $3.1 million.")]
    out = generate_grounded_answer("What was the revenue?", evidence)
    for f in out["findings"]:
        for s in f["statements"]:
            assert s["text"] in evidence[0].text and s["support"] >= 0.99


def test_conflicting_evidence_is_reported_not_resolved():
    evidence = [ev(1, "The contract expires on June 30, 2027.", doc=1, name="A.pdf"), ev(2, "The contract expires on September 30, 2027.", doc=2, name="B.pdf")]
    out = generate_grounded_answer("When does the contract expire?", evidence, intents=["date"])
    assert out["conflicts"] and {out["conflicts"][0]["value_a"], out["conflicts"][0]["value_b"]} == {"June 30, 2027", "September 30, 2027"}
    assert all(f["contradictory_evidence"] for f in out["findings"])
    assert out["confidence"]["penalties"]["contradiction"] > 0


def test_only_conflicts_that_touch_the_answer_are_headline_conflicts():
    evidence = [ev(1, "The contract expires on June 30, 2027. The total contract value is $2,000,000.", doc=1, name="A.pdf"),
                ev(2, "The contract expires on September 30, 2027. The total contract value is $2,400,000.", doc=2, name="B.pdf")]
    llm = FakeLLM({"summary": "", "refused": False, "findings": [{"title": "Expiry", "severity": "info", "statements": [
        {"text": "The contract expires on June 30, 2027.", "type": "fact", "evidence": ["E1"]},
        {"text": "The contract expires on September 30, 2027.", "type": "fact", "evidence": ["E2"]}]}]})
    out = generate_grounded_answer("When does the contract expire?", evidence, provider=llm)
    assert {c["topic"] for c in out["conflicts"]} == {"Contract expiration"}
    assert {c["topic"] for c in out["other_conflicts"]} == {"Contract value"}  # reported, but not allowed to drive this answer's confidence


# ------------------------------------------------------------------ contradictions
def _u(i, doc, text, name=None, doc_type=""):
    return TextUnit(i, doc, name or f"D{doc}.pdf", 1, text, doc_type)


def test_contradiction_detects_changed_date_and_amount():
    cs = detect_conflicts([_u(1, 1, "The contract expires on June 2027."), _u(2, 2, "The contract expires on September 2027."),
                           _u(3, 1, "The total contract value is $2,000,000."), _u(4, 2, "The total contract value is $2,400,000.")])
    topics = {c.topic for c in cs}
    assert {"Contract expiration", "Contract value"} <= topics
    assert all(0.55 <= c.confidence <= 0.97 for c in cs)


def test_no_conflict_when_values_agree_or_quantities_differ():
    assert not detect_conflicts([_u(1, 1, "The contract expires on June 30, 2027."), _u(2, 2, "The contract expires on 30 June 2027.")])
    assert not detect_conflicts([_u(1, 1, "The annual fee is $120,000."), _u(2, 2, "The monthly fee is $10,000.")])  # different quantities


def test_effective_date_not_confused_with_expiry():
    cs = detect_conflicts([_u(1, 1, "The term commences on the Effective Date and expires on June 30, 2027."),
                           _u(2, 2, "The term commences on the Effective Date and expires on September 30, 2027.")])
    assert [c.topic for c in cs] == ["Contract expiration"]


def test_separate_invoices_are_not_contradictions():
    assert not detect_conflicts([_u(1, 1, "Total due is $500.00.", doc_type="Invoice"), _u(2, 2, "Total due is $900.00.", doc_type="Invoice")])


def test_governing_law_and_auto_renewal_conflicts():
    cs = detect_conflicts([_u(1, 1, "This Agreement is governed by the laws of Delaware."), _u(2, 2, "This Agreement is governed by the laws of New York."),
                           _u(3, 1, "This Agreement renews automatically each year."), _u(4, 2, "This Agreement does not renew automatically each year.")])
    assert {"Governing law", "Automatic renewal"} <= {c.topic for c in cs}


# ------------------------------------------------------------------ confidence
def _inp(**kw):
    base = dict(relevance_scores=[0.7, 0.65, 0.6], cited_doc_ids=[1, 2, 3], source_qualities=[0.9, 0.9, 0.9], statement_support=[2, 2],
                statement_docs=[2, 2], groundedness=1.0)
    base.update(kw)
    return ConfidenceInput(**base)


def test_confidence_levels_and_monotonicity():
    strong = compute_confidence(_inp())
    weak = compute_confidence(_inp(relevance_scores=[0.2], cited_doc_ids=[1], source_qualities=[0.5], statement_support=[1], statement_docs=[1], groundedness=0.5))
    assert strong.level == "HIGH" and weak.level == "LOW" and strong.score > weak.score
    assert compute_confidence(_inp(conflict_confidences=[0.9])).score < strong.score
    assert compute_confidence(_inp(uncertainty_notes=3)).score < strong.score
    assert compute_confidence(_inp(source_qualities=[0.3, 0.3, 0.3])).score < strong.score
    assert "not a calibrated probability" in strong.disclaimer
    assert 0 <= weak.score <= strong.score <= 1


def test_confidence_with_no_evidence_is_zero():
    assert compute_confidence(ConfidenceInput([], [], [])).score == 0.0


# ------------------------------------------------------------------ classification / extraction / risk rules
def test_classification_uses_content_not_filename():
    c = classify("INVOICE\nInvoice No: 12\nBill To: X\nSubtotal $10\nTax $1\nTotal Due $11\nPayment terms Net 30\nDue date: May 1, 2026", n_tables=1, kind="pdf")
    assert c.document_type == "Invoice" and c.method.startswith("lexicon+structure") and 0 < c.confidence <= 0.99
    assert classify("lorem ipsum dolor sit amet", kind="text").document_type == "Unknown"


def test_money_date_duration_parsing():
    assert V.parse_money("fees of $2.4M and €1,500")[0].value == pytest.approx(2.4e6)
    assert V.parse_dates("expires September 30, 2027 or 2026-03-05")[0].value == "2027-09-30"
    assert V.parse_durations("within thirty (30) days")[0].value == 30


def test_entities_and_relationships_with_evidence_sentence():
    text = "Acme Corp signed the Master Services Agreement with Globex Industries Ltd, headquartered in Singapore. Acme Corp shall pay $4.2M."
    ms = extract_entities(text, use_spacy=False)
    kinds = {(m.type, m.text) for m in ms}
    assert ("ORG", "Acme Corp") in kinds and ("ORG", "Globex Industries Ltd") in kinds and ("MONEY", "$4.2M") in kinds
    rels = {(r.source.text, r.relation, r.target.text) for r in extract_relationships(text, ms)}
    assert ("Acme Corp", "signed", "Master Services Agreement") in rels
    assert ("Globex Industries Ltd", "operates_in", "Singapore") in rels
    assert ("Acme Corp", "paid", "$4.2M") in rels
    assert all(r.evidence for r in extract_relationships(text, ms))


def test_risk_rules_flag_and_respect_negation():
    assert any(h.rule_id == "unlimited_liability" and h.severity == "critical" for h in scan_sentence("The Supplier's liability shall be unlimited."))
    assert not scan_sentence("Management concluded there is no substantial doubt about our ability to continue as a going concern.")
    assert any(h.rule_id == "auto_renewal" for h in scan_sentence("This Agreement renews automatically for 12 months."))


# ------------------------------------------------------------------ reranking
def _rec(i, text, section=None, doc_type="Contract", q=0.9):
    return ChunkRecord(i, 1, "a.pdf", doc_type, 1, None, section, text, "text", None, None, q)


def test_reranker_combines_signals_not_just_embedding_score():
    recs = {1: _rec(1, "Termination clause: the contract expires in 2027.", "Term and Termination"), 2: _rec(2, "General office information about parking.", "Facilities")}
    cands = {1: Candidate(1, sem=0.30, lex=2.0, graph=0.0, methods={"semantic", "lexical"}), 2: Candidate(2, sem=0.32, lex=0.0, graph=0.9, methods={"semantic", "graph"})}
    qu = understand("When does the contract expire? termination")
    ranked = rerank(cands, recs, qu, {1: set(), 2: set()}, set(), k=5)
    assert ranked[0].record.id == 1  # lexical + metadata (section match) outweigh the slightly higher embedding score
    assert set(ranked[0].features) == {"semantic", "lexical", "metadata", "entity", "graph", "recency", "quality"}
    assert ranked[0].methods == ["lexical", "semantic"]


def test_reranker_entity_overlap_and_weight_override():
    recs = {1: _rec(1, "Acme Corp pays the fee."), 2: _rec(2, "Another company pays the fee.")}
    cands = {1: Candidate(1, sem=0.3, lex=1.0, methods={"semantic"}), 2: Candidate(2, sem=0.3, lex=1.0, methods={"semantic"})}
    qu = understand("What does Acme Corp pay?")
    ranked = rerank(cands, recs, qu, {1: {"acme"}, 2: set()}, {"acme"}, k=2)
    assert ranked[0].record.id == 1 and ranked[0].features["entity"] == 1.0 and ranked[1].features["entity"] == 0.0
    only_quality = rerank({1: Candidate(1, sem=0.9, methods={"semantic"}), 2: Candidate(2, sem=0.1, methods={"semantic"})},
                          {1: _rec(1, "x y", q=0.1), 2: _rec(2, "x y", q=1.0)}, understand("x"), {}, set(),
                          weights={"semantic": 0, "lexical": 0, "metadata": 0, "entity": 0, "graph": 0, "recency": 0, "quality": 1.0})
    assert only_quality[0].record.id == 2

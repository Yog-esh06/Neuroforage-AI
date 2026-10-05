export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type DocStatus = "QUEUED" | "PROCESSING" | "INDEXING" | "READY" | "FAILED";
export type TaskStatus = "PENDING" | "APPROVED" | "REJECTED" | "MODIFIED" | "ESCALATED" | "NEEDS_EVIDENCE";
export type Role = "admin" | "reviewer" | "analyst" | "viewer";

export interface User { id: number; email: string; name: string; role: Role; is_active: boolean; auth_enabled?: boolean }

export interface DocJob { stage: string; progress: number; attempts: number; error: string | null; timings_ms: Record<string, number> }
export interface DocumentItem {
  id: number; filename: string; file_kind: string; mime_type: string; size_bytes: number; status: DocStatus; error: string | null;
  document_type: string; classification_confidence: number; classification_method: string; page_count: number; ocr_used: boolean;
  ocr_confidence: number | null; title: string | null; version: number; created_at: string; processed_at: string | null;
  processing_ms: number | null; flags: string[]; job?: DocJob;
}
export interface DocumentDetail extends DocumentItem {
  classification_detail: { scores: Record<string, number>; signals: string[] };
  meta: Record<string, unknown>; sha256: string;
  counts: { chunks: number; entities: number; insights: number; tables: number; contradictions: number };
  versions: { version: number; sha256: string; size_bytes: number; created_at: string }[];
}

export interface BBox extends Array<number> {}
export interface PageElement {
  id: number; type: string; text: string; bbox: BBox | null; section: string | null; level: number | null; confidence: number | null;
  table?: { headers: string[]; rows: string[][]; profile: TableProfile; cells: { row: string; column: string; value: string }[] };
}
export interface TableProfile {
  columns: { index: number; header: string; type: string; sum?: number }[];
  total_row_index: number | null;
  total_checks: { column: string; claimed_total: number; calculated_sum: number; consistent: boolean }[];
}
export interface PageDetail {
  page_number: number; width: number | null; height: number | null; text: string; ocr_used: boolean; ocr_confidence: number | null; method: string;
  elements: PageElement[]; entities: { id: number; name: string; type: string; mentions: number }[]; insights: Insight[];
}
export interface PageSummary { page_number: number; width: number | null; height: number | null; ocr_used: boolean; method: string; chars: number }

export interface EvidenceItem {
  evidence_id: string; document_id: number; document_name: string; document_type: string; page_number: number; section: string | null;
  text: string; relevance_score: number; retrieval_method: string; features: Record<string, number>;
  source_location: { chunk_id: number; bbox: BBox | null; page_end: number | null };
  entities: { name: string; type: string; id: number }[]; marker?: string;
}
export interface SearchResponse {
  query: string; query_id: number; understanding: { keywords: string[]; entities: { text: string; type: string }[]; intents: string[]; doc_type_hints: string[]; notes: string[] };
  strategies: { semantic: { candidates: number }; lexical: { candidates: number }; graph: { candidates: number; linked_entities: number }; pool: number; indexed_chunks: number; filtered_to: number | null };
  weights: Record<string, number>; linked_entities: { id: number; name: string; type: string; score: number }[]; latency_ms: number; results: EvidenceItem[];
}

export interface Confidence { score: number; level: "HIGH" | "MEDIUM" | "LOW"; breakdown: Record<string, number>; penalties: Record<string, number>; explanation: string; disclaimer: string }
export interface Statement { text: string; type: "fact" | "inference"; evidence: string[]; support: number }
export interface Finding {
  title: string; severity: Severity; statements: Statement[]; entities: string[]; reasoning: string; contradictory_evidence: string[];
  recommended_action: string; evidence_ids: string[]; confidence: Confidence;
}
export interface ConflictEvidence { document_id: number; document_name: string; page_number: number; chunk_id: number; text: string; value: string }
export interface Conflict { topic: string; subject: string | null; kind: string; value_a: string; value_b: string; evidence_a: ConflictEvidence; evidence_b: ConflictEvidence; confidence: number; explanation: string }
export interface AskResponse {
  answer_id: number; question: string; summary: string; refused: boolean; refusal_reason: string; findings: Finding[]; citations: EvidenceItem[];
  conflicts: Conflict[]; other_conflicts: Conflict[]; confidence: Confidence; validation: { unsupported_claims: { statement: string; reason: string }[]; stripped_citations: unknown[]; fallback: string | null; citation_coverage: number; total_statements: number; supported_statements: number; provider_is_llm: boolean };
  uncertainty_notes: string[]; provider: string; model: string; prompt_version: string; latency_ms: number; evidence: EvidenceItem[];
  understanding: SearchResponse["understanding"]; strategies: SearchResponse["strategies"]; retrieval_latency_ms: number;
}

export interface Insight {
  id: number; kind: string; category: string; title: string; description: string; severity: Severity; severity_score: number; confidence: number;
  confidence_breakdown: Confidence | Record<string, never>; status: string; document_id: number | null; document_name: string | null;
  evidence: { document_id: number; document_name: string; page_number: number; section: string | null; chunk_id: number | null; text: string; relevance_score: number; retrieval_method: string; bbox: BBox | null }[];
  entities: { name: string; type: string }[]; reasoning: string; recommended_action: string; method: string; created_at: string;
}
export interface ContradictionItem {
  id: number; topic: string; subject: string | null; kind: string; confidence: number; status: string; resolution_note: string | null; created_at: string;
  evidence_a: ConflictEvidence; evidence_b: ConflictEvidence;
}

export interface ReviewTask {
  id: number; type: string; priority: Severity; title: string; ai_recommendation: string; modified_recommendation: string | null; evidence: Insight["evidence"];
  confidence: number; status: TaskStatus; reviewer: string | null; document_id: number | null; document_name: string | null; insight_id: number | null;
  contradiction_id: number | null; decision_note: string | null; created_at: string; updated_at: string; decided_at: string | null;
  history?: { id: number; timestamp: string; user: string; action: string; summary: string; details: Record<string, unknown> }[];
}

export interface EntityNode { id: number; name: string; type: string; mentions: number; degree: number; aliases?: string[]; attributes?: Record<string, unknown>; hop?: number; is_center?: boolean; match_score?: number }
export interface GraphEdge { id: number; source: number; target: number; relation: string; confidence: number; evidence: string; document_id: number; document: string; page: number; chunk_id: number | null }
export interface GraphView { nodes: EntityNode[]; edges: GraphEdge[] }
export interface EntityDetail {
  entity: EntityNode;
  relationships: { id: number; relation: string; direction: "in" | "out"; confidence: number; other: { id: number; name: string; type: string }; evidence: string; document_id: number; document: string; page: number; chunk_id: number | null }[];
  documents: { document_id: number; document: string; pages: number[]; mentions: number }[];
  evidence: { document_id: number; page: number; chunk_id: number; surface: string; method: string; text: string }[];
}

export interface Workflow {
  id: number; name: string; description: string; trigger: string; conditions: ConditionNode; actions: { type: string; params?: Record<string, unknown> }[];
  enabled: boolean; created_at: string; run_count: number; matched_count: number;
}
export type ConditionLeaf = { field: string; op: string; value?: unknown };
export type ConditionNode = { all?: (ConditionNode | ConditionLeaf)[]; any?: (ConditionNode | ConditionLeaf)[] } | ConditionLeaf | Record<string, never>;
export interface WorkflowMeta { triggers: string[]; fields: Record<string, { type: string; values?: string[] }>; operators: string[]; actions: Record<string, string>; trigger_fields: Record<string, string[]> }
export interface WorkflowRun { id: number; workflow_id: number; workflow_name: string; trigger: string; subject_type: string; subject_id: number | null; matched: boolean; status: string; steps: Record<string, unknown>[]; error: string | null; created_at: string }

export interface AuditItem {
  id: number; timestamp: string; user: string; action: string; entity_type: string; entity_id: number | null; document_id: number | null; query_text: string | null;
  model: string | null; model_version: string | null; prompt_version: string | null; confidence: number | null; summary: string; hash: string; prev_hash: string;
  details?: Record<string, unknown>;
}

export interface ValueChange { kind: string; from: string | null; to: string | null; direction?: string; delta_pct?: number | null }
export interface ChangeItem {
  type: "changed" | "added" | "removed"; categories: string[]; similarity: number; value_changes: ValueChange[];
  a: { text: string; page: number; chunk_id: number; section: string | null } | null; b: { text: string; page: number; chunk_id: number; section: string | null } | null;
  diff: { op: string; a: string; b: string }[];
}
export interface KeyFact { topic: string; status: "changed" | "unchanged" | "added" | "removed"; direction?: string; a: { value: string; page: number; text: string; chunk_id: number } | null; b: { value: string; page: number; text: string; chunk_id: number } | null }
export interface Comparison {
  document_a: { id: number; name: string; type: string; units: number }; document_b: { id: number; name: string; type: string; units: number };
  summary: { unchanged: number; changed: number; added: number; removed: number; by_category: Record<string, number>; similarity: number };
  key_facts: KeyFact[]; changes: ChangeItem[]; entities: { added: string[]; removed: string[]; shared: number };
}

export interface Dashboard {
  documents: { total: number; ready: number; by_status: Record<string, number>; by_type: Record<string, number>; processing: number; failed: number; chunks: number; ocr_documents: number };
  knowledge: { entities: number; relationships: number; entities_by_type: Record<string, number> };
  review: { open: number; by_status: Record<string, number>; open_by_priority: Record<string, number> };
  risk: { high_risk_findings: number; by_severity: Record<string, number>; by_category: Record<string, number>; total_insights: number };
  contradictions: { total: number; open: number };
  confidence: { average: number | null; insights_average: number | null; answers_average: number | null; samples: number; histogram: { bucket: string; count: number }[] };
  latency: { processing_avg_ms: number | null; processing_p95_ms: number | null; search_avg_ms: number | null; answer_avg_ms: number | null; stage_avg_ms: Record<string, number> };
  uploads_per_day: { date: string; documents: number }[];
  recent_activity: { id: number; timestamp: string; action: string; user: string; summary: string }[];
  system: { llm: { provider: string; model: string; is_llm: boolean; configured: string }; ocr: { available: boolean; engine: string | null; error: string | null }; spacy_ner: boolean };
}

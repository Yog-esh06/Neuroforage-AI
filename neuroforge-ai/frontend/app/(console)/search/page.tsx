"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Filter, Search as SearchIcon, Sparkles } from "lucide-react";
import { api, ApiError, type SearchFilters } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { cn, fmtMs, titleCase } from "@/lib/utils";
import type { AskResponse, EvidenceItem, SearchResponse } from "@/lib/types";
import { AnswerView } from "@/components/search/answer-view";
import { Badge, Button, EmptyState, ErrorNote, Input, Panel, PanelHeader, Select, Spinner } from "@/components/ui/primitives";
import { CitationLink, EntityChip, highlightText, PageHeader } from "@/components/ui/shared";

const TYPES = ["Contract", "Invoice", "Research Paper", "Financial Report", "Technical Documentation", "Policy", "Resume", "Legal Document", "General Report"];
const METHOD_TONE: Record<string, string> = { semantic: "text-violet", lexical: "text-cyan", graph: "text-emerald" };
const FEATURES = [["semantic", "bg-violet"], ["lexical", "bg-cyan"], ["graph", "bg-emerald"], ["entity", "bg-amber"], ["metadata", "bg-magenta"], ["quality", "bg-paper-mute"], ["recency", "bg-ink-300"]] as const;
const EXAMPLES = ["What are the major financial risks mentioned across these documents?", "When does the contract expire?", "What is the governing law?", "Which obligations carry penalties?"];

export default function Page() { return <Suspense fallback={<Spinner />}><SearchPage /></Suspense>; }

function SearchPage() {
  const sp = useSearchParams();
  const { can } = useAuth();
  const [query, setQuery] = useState(sp.get("q") || "");
  const [mode, setMode] = useState<"retrieve" | "ask">(can("analyst") ? "ask" : "retrieve");
  const [strategies, setStrategies] = useState<string[]>(["semantic", "lexical", "graph"]);
  const [docType, setDocType] = useState("");
  const [docId, setDocId] = useState(sp.get("doc") || "");
  const [entity, setEntity] = useState("");
  const [pageMax, setPageMax] = useState("");
  const [showFilters, setShowFilters] = useState(!!sp.get("doc"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [ans, setAns] = useState<AskResponse | null>(null);
  const docs = useApi(() => api.documents({ status: "READY", limit: 200 }), []);

  useEffect(() => { if (!can("analyst") && mode === "ask") setMode("retrieve"); }, [can, mode]);
  // Deep links (?q=…&run=1) execute immediately, e.g. the 'Ask: major financial risks' button on /insights
  useEffect(() => { if (sp.get("run") === "1" && sp.get("q")) run(sp.get("q") as string); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const filters = (): SearchFilters | undefined => {
    const f: SearchFilters = {};
    if (docType) f.document_types = [docType];
    if (docId) f.document_ids = [Number(docId)];
    if (entity.trim()) f.entities = [entity.trim()];
    if (pageMax) f.page_max = Number(pageMax);
    return Object.keys(f).length ? f : undefined;
  };

  async function run(q = query) {
    if (q.trim().length < 3) { setError("Enter at least 3 characters."); return; }
    setBusy(true); setError(null);
    try {
      if (mode === "ask") { setAns(await api.ask({ question: q, filters: filters() })); setRes(null); }
      else { setRes(await api.search({ query: q, k: 12, filters: filters(), strategies })); setAns(null); }
    } catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const toggle = (s: string) => setStrategies((v) => (v.includes(s) ? (v.length > 1 ? v.filter((x) => x !== s) : v) : [...v, s]));

  return (
    <>
      <PageHeader eyebrow="Corpus" title="Hybrid search & grounded answers" subtitle="Semantic + BM25 + knowledge-graph retrieval, metadata filtering and feature-based reranking. Ask mode generates answers only from retrieved evidence." />
      <Panel className="mb-5">
        <div className="space-y-3 p-3.5">
          <form onSubmit={(e) => { e.preventDefault(); run(); }} className="flex flex-wrap gap-2">
            <div className="flex rounded border border-ink-400 p-0.5">
              {(["ask", "retrieve"] as const).map((m) => <button type="button" key={m} disabled={m === "ask" && !can("analyst")} onClick={() => setMode(m)} className={cn("rounded-sm px-3 py-1 font-mono text-2xs uppercase disabled:opacity-30", mode === m ? "bg-violet text-ink" : "text-paper-mute hover:text-paper")}>{m === "ask" ? "Ask" : "Retrieve"}</button>)}
            </div>
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={mode === "ask" ? "Ask a question about your documents…" : "Search passages…"} className="h-9 min-w-[280px] flex-1" aria-label="Query" />
            <Button type="submit" variant="primary" className="h-9" loading={busy}>{mode === "ask" ? <Sparkles className="h-3.5 w-3.5" /> : <SearchIcon className="h-3.5 w-3.5" />}{mode === "ask" ? "Ask" : "Search"}</Button>
            <Button type="button" variant="ghost" className="h-9" onClick={() => setShowFilters((v) => !v)}><Filter className="h-3.5 w-3.5" />Filters</Button>
          </form>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {mode === "retrieve" && <div className="flex items-center gap-1.5"><span className="label-micro">Strategies</span>{["semantic", "lexical", "graph"].map((s) => <button key={s} onClick={() => toggle(s)} className={cn("rounded-sm border px-2 py-0.5 font-mono text-2xs uppercase", strategies.includes(s) ? "border-ink-300 bg-ink-600 " + METHOD_TONE[s] : "border-ink-500 text-paper-faint")}>{s}</button>)}</div>}
            <div className="flex flex-wrap items-center gap-1.5"><span className="label-micro">Try</span>{EXAMPLES.map((x) => <button key={x} onClick={() => { setQuery(x); run(x); }} className="rounded-sm border border-ink-500 px-2 py-0.5 text-2xs text-paper-mute hover:border-ink-300 hover:text-paper">{x}</button>)}</div>
          </div>
          {showFilters && (
            <div className="grid gap-2 border-t border-ink-500/70 pt-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="space-y-1"><span className="label-micro">Document</span><Select value={docId} onChange={(e) => setDocId(e.target.value)} className="w-full"><option value="">All documents</option>{(docs.data?.items ?? []).map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}</Select></label>
              <label className="space-y-1"><span className="label-micro">Document type</span><Select value={docType} onChange={(e) => setDocType(e.target.value)} className="w-full"><option value="">Any</option>{TYPES.map((t) => <option key={t}>{t}</option>)}</Select></label>
              <label className="space-y-1"><span className="label-micro">Must mention entity</span><Input value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="e.g. Acme Corp" /></label>
              <label className="space-y-1"><span className="label-micro">Pages up to</span><Input type="number" min={1} value={pageMax} onChange={(e) => setPageMax(e.target.value)} placeholder="any" /></label>
            </div>
          )}
        </div>
      </Panel>

      <ErrorNote message={error} />
      {busy && <div className="grid h-40 place-items-center"><Spinner className="h-5 w-5" /></div>}
      {!busy && ans && <AnswerPane a={ans} />}
      {!busy && res && <RetrievalPane r={res} query={query} />}
      {!busy && !ans && !res && !error && <Panel><EmptyState icon={<SearchIcon className="h-8 w-8" />} title="Ask your documents anything" hint="Answers cite the exact page of the source document. If the evidence does not support an answer, the platform refuses instead of guessing." /></Panel>}
    </>
  );
}

function AnswerPane({ a }: { a: AskResponse }) {
  return (
    <div className="space-y-4">
      <UnderstandingBar u={a.understanding} s={a.strategies} latency={a.retrieval_latency_ms} />
      <AnswerView a={a} />
    </div>
  );
}

function UnderstandingBar({ u, s, latency }: { u: SearchResponse["understanding"]; s: SearchResponse["strategies"]; latency: number }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded border border-ink-500/70 bg-ink-800/60 px-3.5 py-2 text-2xs text-paper-mute">
      <span className="label-micro">Query understanding</span>
      <span>intent: {u.intents.map((i) => <Badge key={i} tone="violet" className="ml-1">{i}</Badge>)}</span>
      {u.entities.length > 0 && <span className="flex items-center gap-1">entities: {u.entities.map((e) => <EntityChip key={e.text} name={e.text} type={e.type} />)}</span>}
      <span className="num">semantic {s.semantic.candidates} · lexical {s.lexical.candidates} · graph {s.graph.candidates} → pool {s.pool} of {s.indexed_chunks} chunks · {fmtMs(latency)}</span>
      {u.notes.map((n) => <span key={n} className="text-amber">{n}</span>)}
    </div>
  );
}

function RetrievalPane({ r, query }: { r: SearchResponse; query: string }) {
  const terms = query.split(/\s+/).filter((t) => t.length > 3);
  return (
    <div className="space-y-4">
      <UnderstandingBar u={r.understanding} s={r.strategies} latency={r.latency_ms} />
      {r.linked_entities.length > 0 && <div className="flex flex-wrap items-center gap-1.5 text-xs"><span className="label-micro">Graph-linked entities</span>{r.linked_entities.map((e) => <EntityChip key={e.id} name={e.name} type={e.type} />)}</div>}
      {r.results.length === 0 ? <Panel><EmptyState title="No passages matched" hint="Loosen the filters or try different keywords." /></Panel> : (
        <div className="space-y-2.5">{r.results.map((e, i) => <ResultCard key={e.source_location.chunk_id} e={e} rank={i + 1} terms={terms} />)}</div>
      )}
      <Panel><PanelHeader title="Reranker weights" tone="violet" /><div className="flex flex-wrap gap-x-5 gap-y-1 px-3.5 py-2.5 text-2xs text-paper-mute">{Object.entries(r.weights).map(([k, v]) => <span key={k}>{titleCase(k)} <span className="num text-paper-dim">{v}</span></span>)}<span className="text-paper-faint">(normalised at runtime)</span></div></Panel>
    </div>
  );
}

function ResultCard({ e, rank, terms }: { e: EvidenceItem; rank: number; terms: string[] }) {
  return (
    <Panel>
      <div className="grid gap-3 p-3.5 md:grid-cols-[1fr_230px]">
        <div className="min-w-0">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <span className="num grid h-5 w-5 place-items-center rounded-sm bg-ink-600 text-2xs text-paper-dim">{rank}</span>
            <CitationLink docId={e.document_id} page={e.page_number} name={e.document_name} bbox={e.source_location.bbox} />
            <Badge>{e.document_type}</Badge>
            {e.retrieval_method.split("+").map((m) => <Badge key={m} tone={m === "semantic" ? "violet" : m === "lexical" ? "cyan" : "emerald"}>{m}</Badge>)}
          </div>
          {e.section && <p className="mb-1 truncate text-2xs text-paper-faint">{e.section}</p>}
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-paper-dim">{highlightText(e.text.length > 700 ? e.text.slice(0, 700) + "…" : e.text, terms)}</p>
          {e.entities.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{e.entities.slice(0, 6).map((x) => <EntityChip key={x.id} name={x.name} type={x.type} />)}</div>}
        </div>
        <div className="space-y-1.5 rounded border border-ink-500/70 bg-ink-700/40 p-2.5">
          <div className="flex items-center justify-between"><span className="label-micro">Relevance</span><span className="num text-sm text-paper">{e.relevance_score.toFixed(3)}</span></div>
          {FEATURES.map(([k, c]) => (
            <div key={k} className="grid grid-cols-[62px_1fr_28px] items-center gap-1.5 text-2xs"><span className="text-paper-mute">{k}</span><div className="h-1 overflow-hidden rounded-full bg-ink-500"><div className={cn("h-full", c)} style={{ width: `${(e.features[k] ?? 0) * 100}%` }} /></div><span className="num text-right text-paper-faint">{(e.features[k] ?? 0).toFixed(2)}</span></div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

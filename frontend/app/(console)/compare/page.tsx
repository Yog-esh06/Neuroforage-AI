"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowDown, ArrowUp, ArrowRight, GitCompareArrows, Minus, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, titleCase } from "@/lib/utils";
import type { ChangeItem, Comparison, KeyFact } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorNote, Panel, PanelHeader, Spinner } from "@/components/ui/primitives";
import { CitationLink, PageHeader, Stat } from "@/components/ui/shared";

const CAT_TONE: Record<string, "amber" | "cyan" | "violet" | "magenta" | "emerald" | "danger" | "neutral"> = {
  changed_value: "amber", changed_date: "cyan", changed_duration: "cyan", changed_obligation: "magenta", changed_entity: "violet", changed_clause: "neutral", added: "emerald", removed: "danger",
};

export default function Page() {
  return <Suspense fallback={<Spinner />}><ComparePage /></Suspense>;
}

function ComparePage() {
  const sp = useSearchParams();
  const docs = useApi(() => api.documents({ status: "READY", limit: 200 }), []);
  const [sel, setSel] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [out, setOut] = useState<Comparison[] | null>(null);
  const [filter, setFilter] = useState<string>("all");

  // Deep link: /compare?docs=1,2 preselects and runs the comparison
  useEffect(() => {
    const ids = (sp.get("docs") || "").split(",").map(Number).filter((n) => n > 0);
    if (ids.length >= 2) { setSel(ids.slice(0, 5)); setBusy(true); api.compare(ids.slice(0, 5)).then((r) => setOut(r.comparisons)).catch((e) => setError(e instanceof ApiError ? e.message : String(e))).finally(() => setBusy(false)); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id: number) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length < 5 ? [...s, id] : s));
  async function run() {
    setBusy(true); setError(null); setOut(null);
    try { setOut((await api.compare(sel)).comparisons); } catch (e) { setError(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  const items = docs.data?.items ?? [];

  return (
    <>
      <PageHeader eyebrow="Analysis" title="Semantic document comparison" subtitle="Clauses are aligned by meaning, not by line position, then compared by value, date, duration, entity and obligation. The first selected document is the baseline." />
      <Panel className="mb-5">
        <PanelHeader title={`Select 2–5 documents · ${sel.length} chosen`} tone="violet" right={<Button variant="primary" onClick={run} disabled={sel.length < 2} loading={busy}><GitCompareArrows className="h-3.5 w-3.5" />Compare</Button>} />
        {docs.loading && !docs.data ? <div className="grid h-24 place-items-center"><Spinner /></div> : items.length === 0 ? <EmptyState title="No READY documents" hint="Upload at least two documents and wait for processing to finish." /> : (
          <div className="grid gap-1.5 p-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((d) => {
              const idx = sel.indexOf(d.id);
              return (
                <button key={d.id} onClick={() => toggle(d.id)} className={cn("flex items-center justify-between gap-2 rounded border px-3 py-2 text-left text-xs transition-colors", idx >= 0 ? "border-violet bg-violet-soft" : "border-ink-500 bg-ink-700/40 hover:border-ink-300")}>
                  <span className="min-w-0"><span className="block truncate text-paper-dim">{d.filename}</span><span className="text-2xs text-paper-faint">{d.document_type}</span></span>
                  {idx >= 0 && <span className="num grid h-5 w-5 shrink-0 place-items-center rounded-full bg-violet text-2xs text-ink">{idx === 0 ? "A" : idx + 1}</span>}
                </button>
              );
            })}
          </div>
        )}
      </Panel>
      <ErrorNote message={error} />
      {busy && <div className="grid h-40 place-items-center"><Spinner className="h-5 w-5" /></div>}
      {out?.map((c, i) => <ComparisonView key={i} c={c} filter={filter} setFilter={setFilter} />)}
    </>
  );
}

function Dir({ d }: { d?: string }) {
  if (d === "up" || d === "later") return <ArrowUp className="h-3.5 w-3.5 text-amber" />;
  if (d === "down" || d === "earlier") return <ArrowDown className="h-3.5 w-3.5 text-cyan" />;
  return <ArrowRight className="h-3.5 w-3.5 text-paper-mute" />;
}

function ComparisonView({ c, filter, setFilter }: { c: Comparison; filter: string; setFilter: (s: string) => void }) {
  const cats = Object.keys(c.summary.by_category);
  const changes = c.changes.filter((x) => filter === "all" || x.categories.includes(filter));
  return (
    <div className="mb-8 space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Unchanged" value={c.summary.unchanged} tone="emerald" /><Stat label="Changed" value={c.summary.changed} tone="amber" />
        <Stat label="Added in B" value={c.summary.added} tone="cyan" /><Stat label="Removed from A" value={c.summary.removed} tone="danger" />
        <Stat label="Overlap" value={`${Math.round(c.summary.similarity * 100)}%`} tone="violet" hint="unchanged share of clauses" />
      </div>

      <Panel>
        <PanelHeader title="Key terms side by side" tone="amber" />
        <div className="grid grid-cols-[170px_1fr_44px_1fr] border-b border-ink-500/70 px-3.5 py-2 text-2xs"><span className="label-micro">Term</span>
          <span className="truncate font-medium text-paper-dim">A · {c.document_a.name}</span><span /><span className="truncate font-medium text-paper-dim">B · {c.document_b.name}</span></div>
        {c.key_facts.length === 0 && <EmptyState title="No comparable key terms were detected" hint="Key-term extraction targets dates, amounts, durations, rates, governing law and renewal terms." />}
        {c.key_facts.map((f) => <FactRow key={f.topic} f={f} a={c.document_a.id} b={c.document_b.id} />)}
      </Panel>

      <Panel>
        <PanelHeader title={`Clause-level changes · ${changes.length}`} tone="violet" right={
          <div className="flex flex-wrap gap-1">{["all", ...cats].map((k) => <button key={k} onClick={() => setFilter(k)} className={cn("rounded-sm border px-1.5 py-0.5 font-mono text-2xs uppercase", filter === k ? "border-violet bg-violet-soft text-violet" : "border-ink-500 text-paper-mute hover:text-paper")}>{k === "all" ? "all" : titleCase(k)}{k !== "all" && ` ${c.summary.by_category[k]}`}</button>)}</div>} />
        <div className="divide-y divide-ink-500/60">{changes.slice(0, 80).map((ch, i) => <ChangeRow key={i} ch={ch} a={c.document_a.id} b={c.document_b.id} />)}</div>
        {changes.length === 0 && <EmptyState title="No changes in this category" />}
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel><PanelHeader title={`Entities only in B · ${c.entities.added.length}`} tone="emerald" /><div className="flex flex-wrap gap-1 p-3">{c.entities.added.map((e) => <Badge key={e} tone="emerald"><Plus className="h-3 w-3" />{e}</Badge>)}{c.entities.added.length === 0 && <span className="text-xs text-paper-mute">None</span>}</div></Panel>
        <Panel><PanelHeader title={`Entities only in A · ${c.entities.removed.length}`} tone="danger" /><div className="flex flex-wrap gap-1 p-3">{c.entities.removed.map((e) => <Badge key={e} tone="danger"><Minus className="h-3 w-3" />{e}</Badge>)}{c.entities.removed.length === 0 && <span className="text-xs text-paper-mute">None</span>}</div></Panel>
      </div>
    </div>
  );
}

function FactRow({ f, a, b }: { f: KeyFact; a: number; b: number }) {
  const changed = f.status !== "unchanged";
  return (
    <div className={cn("grid grid-cols-[170px_1fr_44px_1fr] items-center gap-0 border-b border-ink-500/50 px-3.5 py-2.5 text-xs last:border-0", changed && "bg-amber/5")}>
      <div><p className="text-paper-dim">{f.topic}</p><Badge tone={f.status === "changed" ? "amber" : f.status === "added" ? "cyan" : f.status === "removed" ? "danger" : "emerald"} className="mt-1">{f.status === "changed" ? "↑ changed" : f.status}</Badge></div>
      <div>{f.a ? <><p className={cn("num text-sm", changed ? "text-paper" : "text-paper-dim")}>{f.a.value}</p><CitationLink docId={a} page={f.a.page} name="A" label={`p.${f.a.page}`} /></> : <span className="text-paper-faint">—</span>}</div>
      <div className="flex justify-center"><Dir d={f.direction} /></div>
      <div>{f.b ? <><p className={cn("num text-sm", changed ? "text-paper" : "text-paper-dim")}>{f.b.value}</p><CitationLink docId={b} page={f.b.page} name="B" label={`p.${f.b.page}`} /></> : <span className="text-paper-faint">—</span>}</div>
    </div>
  );
}

function ChangeRow({ ch, a, b }: { ch: ChangeItem; a: number; b: number }) {
  return (
    <div className="p-3.5">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">{ch.categories.map((c) => <Badge key={c} tone={CAT_TONE[c] || "neutral"}>{titleCase(c)}</Badge>)}
        {ch.type === "changed" && <span className="num text-2xs text-paper-faint">similarity {ch.similarity.toFixed(2)}</span>}
        {ch.value_changes.map((v, i) => <span key={i} className="num flex items-center gap-1 rounded-sm bg-ink-600 px-1.5 text-2xs text-paper-dim">{v.from ?? "∅"} <ArrowRight className="h-3 w-3" /> {v.to ?? "∅"}{v.delta_pct != null && <span className={v.delta_pct > 0 ? "text-amber" : "text-cyan"}>{v.delta_pct > 0 ? "+" : ""}{v.delta_pct}%</span>}</span>)}</div>
      {ch.type === "changed" ? (
        <div className="grid gap-2 md:grid-cols-2">
          <div className="rounded border border-ink-500/70 bg-ink-700/40 p-2.5"><p className="mb-1 flex items-center justify-between"><span className="label-micro">A</span>{ch.a && <CitationLink docId={a} page={ch.a.page} name="A" label={`p.${ch.a.page}`} />}</p>
            <p className="text-xs leading-relaxed text-paper-dim">{ch.diff.map((d, i) => d.op === "equal" ? <span key={i}>{d.a} </span> : d.a ? <mark key={i} className="hl-del">{d.a} </mark> : null)}</p></div>
          <div className="rounded border border-ink-500/70 bg-ink-700/40 p-2.5"><p className="mb-1 flex items-center justify-between"><span className="label-micro">B</span>{ch.b && <CitationLink docId={b} page={ch.b.page} name="B" label={`p.${ch.b.page}`} />}</p>
            <p className="text-xs leading-relaxed text-paper-dim">{ch.diff.map((d, i) => d.op === "equal" ? <span key={i}>{d.b} </span> : d.b ? <mark key={i} className="hl-add">{d.b} </mark> : null)}</p></div>
        </div>
      ) : (
        <div className={cn("rounded border p-2.5 text-xs", ch.type === "added" ? "border-emerald-line bg-emerald-soft" : "border-danger-line bg-danger-soft")}>
          <p className="mb-1 flex items-center justify-between"><span className="label-micro">{ch.type === "added" ? "Only in B" : "Only in A"}</span>{ch.type === "added" ? ch.b && <CitationLink docId={b} page={ch.b.page} name="B" label={`p.${ch.b.page}`} /> : ch.a && <CitationLink docId={a} page={ch.a.page} name="A" label={`p.${ch.a.page}`} />}</p>
          <p className="text-paper-dim">{(ch.type === "added" ? ch.b : ch.a)?.text}</p></div>
      )}
    </div>
  );
}

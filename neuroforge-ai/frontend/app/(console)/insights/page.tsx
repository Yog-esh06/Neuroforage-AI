"use client";
import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, Check, Lightbulb, Swords, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { cn, titleCase } from "@/lib/utils";
import type { Insight } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorNote, Panel, PanelHeader, Select, Spinner, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { CitationLink, ConfidenceMeter, EntityChip, EvidenceCard, PageHeader, SeverityBadge, StatusBadge } from "@/components/ui/shared";

export default function InsightsPage() {
  const { can } = useAuth();
  const [kind, setKind] = useState("");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ins = useApi(() => api.insights({ kind, severity, category, status, limit: 200 }), [kind, severity, category, status]);
  const con = useApi(() => api.contradictions(), []);

  async function setInsight(i: Insight, s: string) {
    setErr(null);
    try { await api.setInsightStatus(i.id, s); await ins.reload(); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }
  async function setCon(id: number, s: string) {
    setErr(null);
    try { await api.setContradictionStatus(id, s); await con.reload(); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }

  return (
    <>
      <PageHeader eyebrow="Analysis" title="AI-generated insights" subtitle="Risks, key terms and integrity checks detected by deterministic rules and cross-document analysis. Each insight links to the exact evidence and records how it was produced."
        actions={<Button asChild variant="primary"><Link href="/search?run=1&q=What%20are%20the%20major%20financial%20risks%20mentioned%20across%20these%20documents%3F">Ask: major financial risks</Link></Button>} />
      <ErrorNote message={err} />
      <Tabs defaultValue="insights">
        <TabsList className="mb-4"><TabsTrigger value="insights">Insights {ins.data ? `· ${ins.data.total}` : ""}</TabsTrigger><TabsTrigger value="contradictions">Contradictions {con.data ? `· ${con.data.total}` : ""}</TabsTrigger></TabsList>

        <TabsContent value="insights">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind"><option value="">All kinds</option>{["risk", "financial", "key_date", "obligation"].map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}</Select>
            <Select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Severity"><option value="">All severities</option>{["critical", "high", "medium", "low"].map((k) => <option key={k}>{k}</option>)}</Select>
            <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category"><option value="">All categories</option>{["legal", "financial", "compliance", "operational", "security", "totals_mismatch", "key_term"].map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}</Select>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">Any status</option>{["open", "verified", "rejected", "needs_review"].map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}</Select>
          </div>
          {ins.loading && !ins.data ? <div className="grid h-40 place-items-center"><Spinner /></div> : ins.error ? <ErrorNote message={ins.error} /> : (ins.data?.items.length ?? 0) === 0 ? (
            <Panel><EmptyState icon={<Lightbulb className="h-8 w-8" />} title="No insights match" hint="Insights are generated automatically when a document finishes processing." /></Panel>
          ) : (
            <div className="space-y-2">{ins.data!.items.map((i) => (
              <Panel key={i.id} className={cn(open === i.id && "border-ink-300")}>
                <button className="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left" onClick={() => setOpen(open === i.id ? null : i.id)}>
                  <div className="flex min-w-0 items-center gap-3"><SeverityBadge severity={i.severity} /><div className="min-w-0"><p className="truncate text-sm text-paper">{i.title}</p><p className="truncate text-2xs text-paper-faint">{i.document_name} · {titleCase(i.category)} · {i.method}</p></div></div>
                  <div className="flex shrink-0 items-center gap-3"><ConfidenceMeter compact confidence={{ score: i.confidence, level: i.confidence >= 0.75 ? "HIGH" : i.confidence >= 0.5 ? "MEDIUM" : "LOW" }} /><StatusBadge status={i.status} /></div>
                </button>
                {open === i.id && (
                  <div className="space-y-3 border-t border-ink-500/70 p-3.5">
                    <p className="text-xs text-paper-mute"><span className="text-violet">Why flagged · </span>{i.reasoning}</p>
                    <div className="grid gap-2 lg:grid-cols-2">{i.evidence.map((e, j) => <EvidenceCard key={j} e={e} />)}</div>
                    {i.entities.length > 0 && <div className="flex flex-wrap gap-1">{i.entities.map((e, j) => <EntityChip key={j} name={e.name} type={e.type} />)}</div>}
                    {i.recommended_action && <p className="text-xs text-paper-dim"><span className="text-amber">Recommended action · </span>{i.recommended_action}</p>}
                    {can("reviewer") && (<div className="flex gap-2 border-t border-ink-500/60 pt-3">
                      <Button variant="verify" size="sm" onClick={() => setInsight(i, "verified")} disabled={i.status === "verified"}><Check className="h-3.5 w-3.5" />Verify</Button>
                      <Button variant="danger" size="sm" onClick={() => setInsight(i, "rejected")} disabled={i.status === "rejected"}><X className="h-3.5 w-3.5" />Reject (false positive)</Button>
                      <Button variant="review" size="sm" onClick={() => setInsight(i, "needs_review")} disabled={i.status === "needs_review"}><AlertTriangle className="h-3.5 w-3.5" />Needs review</Button></div>)}
                  </div>
                )}
              </Panel>))}</div>
          )}
        </TabsContent>

        <TabsContent value="contradictions">
          {con.loading && !con.data ? <Spinner /> : (con.data?.items.length ?? 0) === 0 ? (
            <Panel><EmptyState icon={<Swords className="h-8 w-8" />} title="No contradictions detected" hint="When two documents state different values for the same term (dates, amounts, notice periods, governing law …) they appear here — the platform never silently picks one." /></Panel>
          ) : (
            <div className="space-y-3">{con.data!.items.map((c) => (
              <Panel key={c.id} className="border-magenta-line/70">
                <PanelHeader title={`Conflict detected · ${c.topic}`} tone="magenta" right={<div className="flex items-center gap-2"><span className="num text-2xs text-paper-mute">conflict confidence {c.confidence.toFixed(2)}</span><StatusBadge status={c.status} /></div>} />
                <div className="grid gap-3 p-3.5 md:grid-cols-2">{[c.evidence_a, c.evidence_b].map((e, j) => (
                  <div key={j} className="rounded border border-magenta-line/50 bg-magenta-soft p-3"><div className="mb-1.5 flex items-center justify-between"><span className="label-micro">Evidence {j === 0 ? "A" : "B"}</span><CitationLink docId={e.document_id} page={e.page_number} name={e.document_name} /></div>
                    <p className="num text-base font-medium text-paper">{e.value}</p><p className="mt-1 text-xs italic text-paper-mute">“{e.text}”</p></div>))}</div>
                {c.resolution_note && <p className="border-t border-ink-500/60 px-3.5 py-2 text-xs text-paper-mute">Resolution note: {c.resolution_note}</p>}
                {can("reviewer") && c.status === "open" && (<div className="flex gap-2 border-t border-ink-500/60 px-3.5 py-2.5">
                  <Button size="sm" variant="verify" onClick={() => setCon(c.id, "resolved")}>Mark resolved</Button><Button size="sm" variant="ghost" onClick={() => setCon(c.id, "dismissed")}>Dismiss</Button></div>)}
              </Panel>))}</div>
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}

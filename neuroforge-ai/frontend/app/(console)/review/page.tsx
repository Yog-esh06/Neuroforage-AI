"use client";
import { useEffect, useState } from "react";
import { ArrowUpCircle, Check, ClipboardCheck, FilePlus2, Pencil, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { cn, fmtDate, titleCase } from "@/lib/utils";
import type { ReviewTask } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorNote, Panel, PanelHeader, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { ConfidenceMeter, EvidenceCard, KeyVal, PageHeader, SeverityBadge, StatusBadge } from "@/components/ui/shared";

const OPEN = ["PENDING", "NEEDS_EVIDENCE", "ESCALATED"];

export default function ReviewPage() {
  const { can } = useAuth();
  const [view, setView] = useState<"open" | "all" | "decided">("open");
  const [priority, setPriority] = useState("");
  const [type, setType] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const list = useApi(() => api.reviewTasks({ only_open: view === "open" ? true : undefined, priority, type, limit: 300 }), [view, priority, type], { pollMs: 8000 });
  const items = (list.data?.items ?? []).filter((t) => (view === "decided" ? !OPEN.includes(t.status) : true));
  useEffect(() => { if (items.length && (sel === null || !items.some((t) => t.id === sel))) setSel(items[0].id); if (!items.length) setSel(null); }, [list.data, view]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <PageHeader eyebrow="Governance" title="Human review queue" subtitle="The AI recommends; a person decides. Every decision is final, attributed and written to the audit trail." />
      <div className="grid gap-4 lg:grid-cols-[400px_minmax(0,1fr)]">
        <Panel className="max-h-[80vh] overflow-hidden">
          <PanelHeader title={`Tasks · ${list.data?.total ?? 0}`} tone="amber" right={<div className="flex rounded border border-ink-400 p-0.5">{(["open", "all", "decided"] as const).map((v) => <button key={v} onClick={() => setView(v)} className={cn("rounded-sm px-2 py-0.5 font-mono text-2xs uppercase", view === v ? "bg-ink-500 text-paper" : "text-paper-mute")}>{v}</button>)}</div>} />
          <div className="flex gap-2 border-b border-ink-500/70 p-2.5">
            <Select value={priority} onChange={(e) => setPriority(e.target.value)} className="flex-1" aria-label="Priority"><option value="">Any priority</option>{["critical", "high", "medium", "low"].map((p) => <option key={p}>{p}</option>)}</Select>
            <Select value={type} onChange={(e) => setType(e.target.value)} className="flex-1" aria-label="Type"><option value="">Any type</option>{["risk_review", "contradiction_review", "classification_review"].map((p) => <option key={p} value={p}>{titleCase(p)}</option>)}</Select>
          </div>
          <ul className="max-h-[62vh] overflow-y-auto">
            {list.loading && !list.data ? <div className="grid h-32 place-items-center"><Spinner /></div> : items.length === 0 ? <EmptyState icon={<ClipboardCheck className="h-8 w-8" />} title={view === "open" ? "Queue is clear" : "Nothing here"} hint="Tasks are created by workflows when findings cross your thresholds." /> : items.map((t) => (
              <li key={t.id}><button onClick={() => setSel(t.id)} className={cn("block w-full border-b border-ink-500/50 px-3.5 py-2.5 text-left transition-colors hover:bg-ink-700/60", sel === t.id && "bg-ink-600")}>
                <div className="flex items-center justify-between gap-2"><SeverityBadge severity={t.priority} /><StatusBadge status={t.status} /></div>
                <p className="mt-1.5 truncate text-sm text-paper">{t.title}</p>
                <p className="mt-0.5 flex items-center justify-between text-2xs text-paper-faint"><span className="truncate">{titleCase(t.type)} · {t.document_name}</span><span className="num">conf {t.confidence.toFixed(2)}</span></p></button></li>))}
          </ul>
        </Panel>
        {sel ? <TaskDetail id={sel} canAct={can("reviewer")} onChanged={list.reload} /> : <Panel><EmptyState title="Select a task" /></Panel>}
      </div>
    </>
  );
}

function TaskDetail({ id, canAct, onChanged }: { id: number; canAct: boolean; onChanged: () => Promise<void> }) {
  const t = useApi(() => api.reviewTask(id), [id]);
  const [note, setNote] = useState("");
  const [modified, setModified] = useState("");
  const [mode, setMode] = useState<"" | "modify">("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setNote(""); setModified(""); setMode(""); setErr(null); }, [id]);

  async function act(action: string) {
    setBusy(action); setErr(null);
    try { const r: ReviewTask = await api.reviewAction(id, action, note || undefined, action === "modify" ? modified : undefined); t.setData(r); await onChanged(); setNote(""); setMode(""); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  }
  if (t.loading && !t.data) return <Panel><div className="grid h-64 place-items-center"><Spinner /></div></Panel>;
  if (!t.data) return <Panel><div className="p-4"><ErrorNote message={t.error} /></div></Panel>;
  const k = t.data;
  const open = OPEN.includes(k.status);
  return (
    <Panel>
      <PanelHeader title={`Task #${k.id} · ${titleCase(k.type)}`} tone="amber" right={<div className="flex items-center gap-2"><SeverityBadge severity={k.priority} /><StatusBadge status={k.status} /></div>} />
      <div className="space-y-5 p-4">
        <div><h2 className="text-lg font-semibold">{k.title}</h2><p className="mt-1 text-xs text-paper-mute">{k.document_name} · created {fmtDate(k.created_at)}{k.reviewer && <> · reviewer <span className="text-paper-dim">{k.reviewer}</span></>}</p></div>
        <div className="grid gap-4 md:grid-cols-[1fr_240px]">
          <div className="rounded border border-violet-line bg-violet-soft p-3"><p className="label-micro mb-1 !text-violet">AI recommendation</p><p className="text-sm text-paper">{k.ai_recommendation || "—"}</p>
            {k.modified_recommendation && <div className="mt-2 border-t border-violet-line pt-2"><p className="label-micro mb-1 !text-emerald">Reviewer-modified recommendation</p><p className="text-sm text-paper">{k.modified_recommendation}</p></div>}</div>
          <div className="rounded border border-ink-500 bg-ink-700/40 p-3"><p className="label-micro mb-1.5">Confidence (engineering index)</p><ConfidenceMeter confidence={{ score: k.confidence, level: k.confidence >= 0.75 ? "HIGH" : k.confidence >= 0.5 ? "MEDIUM" : "LOW" }} /><p className="mt-2 text-2xs text-paper-faint">Not a calibrated probability. Treat as a triage signal.</p></div>
        </div>
        <div><p className="label-micro mb-2">Evidence · {k.evidence.length}</p><div className="grid gap-2 lg:grid-cols-2">{k.evidence.map((e, i) => <EvidenceCard key={i} e={e} id={`E${i + 1}`} />)}</div>
          {k.evidence.length === 0 && <p className="text-xs text-paper-mute">No evidence attached — consider requesting more evidence.</p>}</div>

        {open && canAct && (
          <div className="space-y-3 rounded border border-ink-400 bg-ink-700/30 p-3.5">
            <p className="label-micro">Decision</p>
            <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reviewer note (recorded in the audit trail)…" aria-label="Reviewer note" />
            {mode === "modify" && <Textarea rows={3} value={modified} onChange={(e) => setModified(e.target.value)} placeholder="Your modified recommendation…" aria-label="Modified recommendation" />}
            <ErrorNote message={err} />
            <div className="flex flex-wrap gap-2">
              <Button variant="verify" onClick={() => act("approve")} loading={busy === "approve"} disabled={!!busy}><Check className="h-3.5 w-3.5" />Approve</Button>
              <Button variant="danger" onClick={() => act("reject")} loading={busy === "reject"} disabled={!!busy}><X className="h-3.5 w-3.5" />Reject</Button>
              {mode === "modify" ? <Button variant="primary" onClick={() => act("modify")} loading={busy === "modify"} disabled={!!busy || !modified.trim()}><Pencil className="h-3.5 w-3.5" />Submit modification</Button>
                : <Button onClick={() => setMode("modify")} disabled={!!busy}><Pencil className="h-3.5 w-3.5" />Modify</Button>}
              <Button variant="review" onClick={() => act("escalate")} loading={busy === "escalate"} disabled={!!busy}><ArrowUpCircle className="h-3.5 w-3.5" />Escalate</Button>
              <Button variant="data" onClick={() => act("request_evidence")} loading={busy === "request_evidence"} disabled={!!busy}><FilePlus2 className="h-3.5 w-3.5" />Request more evidence</Button>
            </div>
          </div>
        )}
        {open && !canAct && <p className="rounded border border-ink-500 bg-ink-700/40 px-3 py-2 text-xs text-paper-mute">Deciding on tasks requires the reviewer role.</p>}
        {!open && k.decision_note && <KeyVal k="Decision note" v={k.decision_note} />}

        <div><p className="label-micro mb-2">Audit history</p>
          {(k.history ?? []).length === 0 ? <p className="text-xs text-paper-mute">No human actions yet.</p> : (
            <ol className="space-y-2 border-l border-ink-400 pl-4">{k.history!.map((h) => (
              <li key={h.id} className="relative text-xs"><span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-violet" /><p className="text-paper-dim">{h.summary}</p><p className="font-mono text-2xs text-paper-faint">{h.action} · {fmtDate(h.timestamp)}</p></li>))}</ol>)}</div>
      </div>
    </Panel>
  );
}

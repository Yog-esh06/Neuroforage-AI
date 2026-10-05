"use client";
import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, ScrollText, ShieldAlert } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi, useDebounced } from "@/lib/hooks";
import { cn, fmtDate } from "@/lib/utils";
import type { AuditItem } from "@/lib/types";
import { Badge, Button, Dialog, DialogContent, EmptyState, ErrorNote, Input, Panel, PanelHeader, Select, Spinner } from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/shared";

const ACTION_TONE = (a: string) => a.startsWith("review_") ? "amber" : a.includes("answer") || a.includes("search") ? "violet" : a.includes("contradiction") ? "magenta" : a.includes("fail") || a.includes("deleted") ? "danger" : a.includes("workflow") ? "cyan" : "neutral";

export default function AuditPage() {
  const { can } = useAuth();
  const [action, setAction] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const [verify, setVerify] = useState<{ valid: boolean; checked: number; first_broken_id: number | null } | null>(null);
  const [vErr, setVErr] = useState<string | null>(null);
  const [vBusy, setVBusy] = useState(false);
  const allowed = can("reviewer");
  const actions = useApi(() => api.auditActions(), [], { enabled: allowed });
  const list = useApi(() => api.audit({ action, q: dq, limit: 50, offset }), [action, dq, offset], { enabled: allowed, pollMs: 10000 });

  if (!allowed) return <Panel><EmptyState icon={<ShieldAlert className="h-8 w-8" />} title="Reviewer role required" hint="The audit trail contains retrieved evidence and generated results, so it is restricted to reviewers and admins." /></Panel>;

  async function runVerify() {
    setVBusy(true); setVErr(null);
    try { setVerify(await api.auditVerify()); } catch (e) { setVErr(e instanceof ApiError ? e.message : String(e)); } finally { setVBusy(false); }
  }
  const total = list.data?.total ?? 0;

  return (
    <>
      <PageHeader eyebrow="Governance" title="AI audit trail" subtitle="An append-only, hash-chained record of who did what, with which model and prompt version, over which evidence, producing which result and human decision."
        actions={<Button variant={verify ? (verify.valid ? "verify" : "danger") : "outline"} onClick={runVerify} loading={vBusy}><CheckCircle2 className="h-3.5 w-3.5" />Verify chain integrity</Button>} />
      {verify && (
        <div className={cn("mb-4 rounded border px-3.5 py-2.5 text-xs", verify.valid ? "border-emerald-line bg-emerald-soft text-emerald" : "border-danger-line bg-danger-soft text-danger")}>
          {verify.valid ? `Chain intact — ${verify.checked} records verified; no record has been altered or removed.` : `Chain BROKEN at record #${verify.first_broken_id} after ${verify.checked} valid records. The log has been tampered with.`}
        </div>
      )}
      <ErrorNote message={vErr} />
      <Panel>
        <PanelHeader title={`Events · ${total}`} tone="violet" right={<div className="flex items-center gap-2"><Input value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="Search summaries / queries…" className="h-7 w-56" aria-label="Search audit" />
          <Select value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }} className="h-7" aria-label="Action"><option value="">All actions</option>{(actions.data ?? []).map((a) => <option key={a}>{a}</option>)}</Select></div>} />
        {list.loading && !list.data ? <div className="grid h-40 place-items-center"><Spinner /></div> : (list.data?.items.length ?? 0) === 0 ? <EmptyState icon={<ScrollText className="h-8 w-8" />} title="No events match" /> : (
          <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b border-ink-500/80">{["#", "Time", "User", "Action", "Summary", "Model / prompt", "Conf.", "Hash"].map((h) => <th key={h} className="label-micro px-3 py-2 font-normal">{h}</th>)}</tr></thead>
            <tbody>{list.data!.items.map((a) => (
              <tr key={a.id} onClick={() => setOpen(a.id)} className="cursor-pointer border-b border-ink-500/50 hover:bg-ink-700/60">
                <td className="num px-3 py-2 text-paper-faint">{a.id}</td><td className="whitespace-nowrap px-3 py-2 text-paper-mute">{fmtDate(a.timestamp)}</td><td className="px-3 py-2 text-paper-dim">{a.user}</td>
                <td className="px-3 py-2"><Badge tone={ACTION_TONE(a.action) as any}>{a.action.replace(/_/g, " ")}</Badge></td>
                <td className="max-w-[420px] truncate px-3 py-2 text-paper-dim" title={a.query_text || a.summary}>{a.query_text ? <span className="text-violet">“{a.query_text}” </span> : null}{a.summary}</td>
                <td className="px-3 py-2 font-mono text-2xs text-paper-faint">{a.model ? `${a.model} · ${a.prompt_version}` : "—"}</td>
                <td className="num px-3 py-2 text-paper-dim">{a.confidence != null ? a.confidence.toFixed(2) : "—"}</td>
                <td className="px-3 py-2 font-mono text-2xs text-paper-faint">{a.hash.slice(0, 8)}</td></tr>))}</tbody></table></div>)}
        <div className="flex items-center justify-between border-t border-ink-500/70 px-3.5 py-2 text-xs text-paper-mute"><span className="num">{total ? `${offset + 1}–${Math.min(offset + 50, total)} of ${total}` : "0"}</span>
          <div className="flex gap-1.5"><Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Newer</Button><Button size="sm" variant="ghost" disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>Older</Button></div></div>
      </Panel>
      {open !== null && <Detail id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function Detail({ id, onClose }: { id: number; onClose: () => void }) {
  const d = useApi<AuditItem>(() => api.auditItem(id), [id]);
  const a = d.data;
  const det = (a?.details ?? {}) as Record<string, any>;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`Audit record #${id}`} description={a?.summary} className="w-[min(94vw,880px)]">
        {!a ? <Spinner /> : (
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 md:grid-cols-3">{([["User", a.user], ["Timestamp", a.timestamp], ["Action", a.action], ["Entity", `${a.entity_type} #${a.entity_id ?? "—"}`], ["Document", a.document_id ? <Link className="text-cyan hover:underline" href={`/documents/${a.document_id}`}>#{a.document_id}</Link> : "—"], ["Model", a.model || "—"], ["Model version", a.model_version || "—"], ["Prompt version", a.prompt_version || "—"], ["Confidence", a.confidence != null ? a.confidence.toFixed(3) : "—"]] as [string, React.ReactNode][]).map(([k, v]) => <div key={k}><p className="label-micro">{k}</p><p className="text-paper-dim">{v}</p></div>)}</div>
            {a.query_text && <div><p className="label-micro mb-1">Query</p><p className="rounded border border-violet-line bg-violet-soft p-2.5 text-sm text-paper">{a.query_text}</p></div>}
            {Array.isArray(det.retrieved_evidence) && <div><p className="label-micro mb-1">Retrieved evidence ({det.retrieved_evidence.length})</p><div className="flex flex-wrap gap-1.5">{det.retrieved_evidence.map((e: any) => <Link key={e.id} href={`/documents/${e.document_id}?page=${e.page}`} className="rounded-sm border border-cyan-line bg-cyan-soft px-1.5 py-0.5 font-mono text-2xs text-cyan">{e.id} · doc {e.document_id} p.{e.page} · {Number(e.score).toFixed(2)}</Link>)}</div></div>}
            {det.generated_result && <div><p className="label-micro mb-1">Generated result</p><p className="mb-1.5 text-paper-dim">{det.generated_result.summary}</p>{(det.generated_result.findings || []).map((f: any, i: number) => <p key={i} className="text-paper-mute">• <span className="text-paper-dim">{f.title}</span> ({f.severity})</p>)}</div>}
            {det.human_decision && <div className="rounded border border-amber-line bg-amber-soft p-2.5"><p className="label-micro !text-amber">Human decision</p><p className="mt-1 text-sm text-paper">{det.human_decision}</p>{det.note && <p className="mt-1 text-paper-mute">“{det.note}”</p>}{det.ai_recommendation && <p className="mt-1 text-paper-mute">AI recommended: {det.ai_recommendation}</p>}</div>}
            <div><p className="label-micro mb-1">Raw details (JSON)</p><pre className="max-h-64 overflow-auto rounded border border-ink-500 bg-ink-900 p-2.5 font-mono text-2xs text-paper-mute">{JSON.stringify(a.details, null, 2)}</pre></div>
            <div className="grid gap-1 font-mono text-2xs text-paper-faint"><p>hash      {a.hash}</p><p>prev_hash {a.prev_hash || "(genesis)"}</p></div>
          </div>)}
      </DialogContent>
    </Dialog>
  );
}

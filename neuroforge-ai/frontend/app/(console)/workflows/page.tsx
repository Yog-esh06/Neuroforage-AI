"use client";
import { useMemo, useState } from "react";
import { ChevronRight, Play, Plus, Trash2, Workflow as WorkflowIcon, Zap } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { cn, fmtDate, titleCase } from "@/lib/utils";
import type { ConditionLeaf, Workflow, WorkflowMeta } from "@/lib/types";
import { Badge, Button, Dialog, DialogContent, EmptyState, ErrorNote, Input, Panel, PanelHeader, Select, Spinner, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/shared";

const TRIGGER_LABEL: Record<string, string> = { document_ready: "Document ready", insight_created: "Insight created", contradiction_detected: "Contradiction detected", manual: "Manual / on demand" };

function leaves(c: Workflow["conditions"]): { mode: "all" | "any"; rows: ConditionLeaf[] } {
  const anyC = c as { all?: ConditionLeaf[]; any?: ConditionLeaf[] };
  if (anyC.all) return { mode: "all", rows: anyC.all as ConditionLeaf[] };
  if (anyC.any) return { mode: "any", rows: anyC.any as ConditionLeaf[] };
  return { mode: "all", rows: [] };
}

export default function WorkflowsPage() {
  const { can } = useAuth();
  const wfs = useApi(() => api.workflows(), []);
  const meta = useApi(() => api.workflowMeta(), []);
  const [runsFor, setRunsFor] = useState<number | undefined>(undefined);
  const runs = useApi(() => api.workflowRuns(runsFor), [runsFor], { pollMs: 6000 });
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [create, setCreate] = useState(false);

  async function wrap(fn: () => Promise<unknown>) { setErr(null); setNote(null); try { await fn(); await wfs.reload(); await runs.reload(); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } }

  return (
    <>
      <PageHeader eyebrow="Governance" title="Decision automation" subtitle="Define IF / THEN rules over documents, risks and contradictions. When a rule matches, actions run automatically — and every evaluation is logged with its reasoning."
        actions={can("reviewer") && meta.data ? <Button variant="primary" onClick={() => setCreate(true)}><Plus className="h-3.5 w-3.5" />New workflow</Button> : undefined} />
      <ErrorNote message={err} />
      {note && <div className="mb-3 rounded border border-emerald-line bg-emerald-soft px-3 py-2 text-xs text-emerald">{note}</div>}
      <Tabs defaultValue="rules">
        <TabsList className="mb-4"><TabsTrigger value="rules">Rules</TabsTrigger><TabsTrigger value="runs">Run log</TabsTrigger></TabsList>
        <TabsContent value="rules">
          {wfs.loading && !wfs.data ? <Spinner /> : (wfs.data ?? []).length === 0 ? <Panel><EmptyState icon={<WorkflowIcon className="h-8 w-8" />} title="No workflows yet" /></Panel> : (
            <div className="grid gap-3 lg:grid-cols-2">{wfs.data!.map((w) => (
              <Panel key={w.id} className={cn(!w.enabled && "opacity-60")}>
                <PanelHeader title={TRIGGER_LABEL[w.trigger] || w.trigger} tone="amber" icon={<Zap className="h-3.5 w-3.5" />} right={can("reviewer") ? <Switch checked={w.enabled} onCheckedChange={(v) => wrap(() => api.updateWorkflow(w.id, { enabled: v }))} aria-label={`Enable ${w.name}`} /> : <Badge>{w.enabled ? "on" : "off"}</Badge>} />
                <div className="space-y-3 p-3.5">
                  <div><h3 className="text-sm font-semibold">{w.name}</h3><p className="mt-0.5 text-xs text-paper-mute">{w.description}</p></div>
                  <RuleSentence w={w} />
                  <div className="flex items-center justify-between border-t border-ink-500/60 pt-2.5 text-xs">
                    <span className="num text-paper-mute">{w.run_count} evaluations · <span className="text-emerald">{w.matched_count} matched</span></span>
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="ghost" onClick={() => setRunsFor(w.id)}>Runs <ChevronRight className="h-3 w-3" /></Button>
                      {can("reviewer") && <Button size="sm" variant="data" onClick={() => wrap(async () => { const r = await api.runWorkflow(w.id); setNote(`“${w.name}” evaluated ${r.evaluated} new subject(s), ${r.matched} matched.`); })}><Play className="h-3 w-3" />Run on existing data</Button>}
                      {can("reviewer") && <Button size="icon" variant="ghost" aria-label={`Delete ${w.name}`} onClick={() => { if (confirm(`Delete workflow “${w.name}”?`)) wrap(() => api.deleteWorkflow(w.id)); }}><Trash2 className="h-3.5 w-3.5 text-danger" /></Button>}
                    </div>
                  </div>
                </div>
              </Panel>))}</div>
          )}
        </TabsContent>
        <TabsContent value="runs">
          <div className="mb-3 flex items-center gap-2"><Select value={runsFor ?? ""} onChange={(e) => setRunsFor(e.target.value ? Number(e.target.value) : undefined)} aria-label="Workflow filter"><option value="">All workflows</option>{(wfs.data ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></div>
          <Panel>
            {(runs.data ?? []).length === 0 ? <EmptyState title="No runs yet" hint="Runs are recorded when documents are processed or a rule is executed on demand." /> : (
              <ul className="divide-y divide-ink-500/60">{runs.data!.map((r) => (
                <li key={r.id} className="p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><Badge tone={r.matched ? "emerald" : "neutral"}>{r.matched ? "matched" : "no match"}</Badge><span className="text-sm text-paper-dim">{r.workflow_name}</span><span className="font-mono text-2xs text-paper-faint">{r.subject_type} #{r.subject_id}</span></div><span className="font-mono text-2xs text-paper-faint">{fmtDate(r.created_at)}</span></div>
                  <div className="mt-2 space-y-1">{r.steps.map((s: any, i) => s.step === "conditions" ? (
                    <div key={i} className="flex flex-wrap gap-1.5">{(s.trace || []).map((c: any, j: number) => c.field ? <span key={j} className={cn("num rounded-sm border px-1.5 py-0.5 text-2xs", c.passed ? "border-emerald-line text-emerald" : "border-ink-400 text-paper-mute")}>{c.field} {c.op} {JSON.stringify(c.expected)} · actual {JSON.stringify(c.actual)} {c.passed ? "✓" : "✗"}</span> : <span key={j} className="text-2xs text-paper-faint">{c.note}</span>)}</div>
                  ) : <p key={i} className="text-xs text-paper-mute">→ <span className="text-amber">{s.action}</span>: {s.status}{s.review_task_id ? ` (task #${s.review_task_id})` : ""}{s.detail ? ` — ${s.detail}` : ""}{s.reason ? ` — ${s.reason}` : ""}</p>)}</div>
                </li>))}</ul>)}
          </Panel>
        </TabsContent>
      </Tabs>
      {create && meta.data && <Builder meta={meta.data} onClose={() => setCreate(false)} onSaved={async () => { setCreate(false); await wfs.reload(); }} />}
    </>
  );
}

function RuleSentence({ w }: { w: Workflow }) {
  const { mode, rows } = leaves(w.conditions);
  return (
    <div className="rounded border border-ink-500/70 bg-ink-700/40 p-2.5 font-mono text-2xs leading-relaxed">
      <p><span className="text-amber">IF</span> {rows.length === 0 ? <span className="text-paper-mute">always</span> : rows.map((r, i) => <span key={i}>{i > 0 && <span className="text-amber"> {mode === "all" ? "AND" : "OR"} </span>}<span className="text-cyan">{r.field}</span> {r.op} <span className="text-paper">{JSON.stringify(r.value)}</span></span>)}</p>
      <p><span className="text-emerald">THEN</span> {w.actions.map((a, i) => <span key={i}>{i > 0 && ", "}<span className="text-violet">{a.type}</span>{a.params && Object.keys(a.params).length > 0 && <span className="text-paper-mute">({Object.entries(a.params).map(([k, v]) => `${k}=${v}`).join(", ")})</span>}</span>)}</p>
    </div>
  );
}

function Builder({ meta, onClose, onSaved }: { meta: WorkflowMeta; onClose: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [trigger, setTrigger] = useState("insight_created");
  const [mode, setMode] = useState<"all" | "any">("all");
  const [rows, setRows] = useState<ConditionLeaf[]>([{ field: "insight.severity_score", op: ">=", value: 0.7 }]);
  const [actions, setActions] = useState<{ type: string; params: Record<string, unknown> }[]>([{ type: "create_review_task", params: {} }]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fields = useMemo(() => Object.keys(meta.fields).filter((f) => (meta.trigger_fields[trigger] || []).some((p) => f.startsWith(p))), [meta, trigger]);

  const setRow = (i: number, patch: Partial<ConditionLeaf>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  function coerce(field: string, op: string, raw: string): unknown {
    const t = meta.fields[field]?.type;
    if (op === "in" || op === "not_in") return raw.split(",").map((s) => s.trim()).filter(Boolean);
    if (t === "number") return raw === "" ? 0 : Number(raw);
    if (t === "bool") return raw === "true";
    return raw;
  }
  async function save() {
    setBusy(true); setErr(null);
    try {
      await api.createWorkflow({ name, description, trigger, conditions: rows.length ? ({ [mode]: rows } as any) : {}, actions, enabled: true });
      await onSaved();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="New workflow" description="IF conditions are met THEN actions run. Validated server-side before saving.">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1"><span className="label-micro">Name</span><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Critical clause review" /></label>
            <label className="space-y-1"><span className="label-micro">Trigger</span><Select value={trigger} onChange={(e) => { setTrigger(e.target.value); setRows([]); }} className="w-full">{meta.triggers.map((t) => <option key={t} value={t}>{TRIGGER_LABEL[t] || t}</option>)}</Select></label></div>
          <label className="block space-y-1"><span className="label-micro">Description</span><Input value={description} onChange={(e) => setDescription(e.target.value)} /></label>

          <div className="space-y-2 rounded border border-ink-500 p-3">
            <div className="flex items-center justify-between"><span className="label-micro !text-amber">IF</span><Select value={mode} onChange={(e) => setMode(e.target.value as "all" | "any")} className="h-7"><option value="all">ALL conditions match</option><option value="any">ANY condition matches</option></Select></div>
            {rows.map((r, i) => {
              const spec = meta.fields[r.field];
              return (
                <div key={i} className="grid grid-cols-[1fr_90px_1fr_28px] gap-1.5">
                  <Select value={r.field} onChange={(e) => setRow(i, { field: e.target.value, value: meta.fields[e.target.value]?.type === "number" ? 0 : "" })}>{fields.map((f) => <option key={f}>{f}</option>)}</Select>
                  <Select value={r.op} onChange={(e) => setRow(i, { op: e.target.value })}>{meta.operators.map((o) => <option key={o}>{o}</option>)}</Select>
                  {spec?.type === "enum" && r.op !== "in" && r.op !== "not_in" ? <Select value={String(r.value ?? "")} onChange={(e) => setRow(i, { value: e.target.value })}><option value="">…</option>{spec.values!.map((v) => <option key={v}>{v}</option>)}</Select>
                    : <Input value={Array.isArray(r.value) ? (r.value as string[]).join(",") : String(r.value ?? "")} onChange={(e) => setRow(i, { value: coerce(r.field, r.op, e.target.value) })} placeholder={spec?.type === "number" ? "number" : "value"} />}
                  <Button size="icon" variant="ghost" aria-label="Remove condition" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}><Trash2 className="h-3.5 w-3.5" /></Button>
                </div>);
            })}
            <Button size="sm" variant="ghost" onClick={() => fields[0] && setRows((rs) => [...rs, { field: fields[0], op: ">=", value: meta.fields[fields[0]].type === "number" ? 0 : "" }])}><Plus className="h-3 w-3" />Add condition</Button>
          </div>

          <div className="space-y-2 rounded border border-ink-500 p-3">
            <span className="label-micro !text-emerald">THEN</span>
            {actions.map((a, i) => (
              <div key={i} className="grid grid-cols-[190px_1fr_28px] gap-1.5">
                <Select value={a.type} onChange={(e) => setActions((as) => as.map((x, j) => (j === i ? { type: e.target.value, params: {} } : x)))}>{Object.keys(meta.actions).map((t) => <option key={t}>{t}</option>)}</Select>
                <div className="flex gap-1.5">
                  {a.type === "create_review_task" && <><Select value={String(a.params.priority ?? "")} onChange={(e) => setActions((as) => as.map((x, j) => (j === i ? { ...x, params: { ...x.params, priority: e.target.value || undefined } } : x)))}><option value="">priority: auto</option>{["low", "medium", "high", "critical"].map((p) => <option key={p}>{p}</option>)}</Select><Input placeholder="task title (optional)" value={String(a.params.title ?? "")} onChange={(e) => setActions((as) => as.map((x, j) => (j === i ? { ...x, params: { ...x.params, title: e.target.value || undefined } } : x)))} /></>}
                  {a.type === "flag_document" && <Input placeholder="reason" value={String(a.params.reason ?? "")} onChange={(e) => setActions((as) => as.map((x, j) => (j === i ? { ...x, params: { reason: e.target.value } } : x)))} />}
                  {a.type === "set_insight_status" && <Select value={String(a.params.status ?? "needs_review")} onChange={(e) => setActions((as) => as.map((x, j) => (j === i ? { ...x, params: { status: e.target.value } } : x)))}><option>needs_review</option><option>open</option></Select>}
                  {a.type === "add_audit_note" && <Input placeholder="message" value={String(a.params.message ?? "")} onChange={(e) => setActions((as) => as.map((x, j) => (j === i ? { ...x, params: { message: e.target.value } } : x)))} />}
                </div>
                <Button size="icon" variant="ghost" aria-label="Remove action" onClick={() => setActions((as) => as.filter((_, j) => j !== i))}><Trash2 className="h-3.5 w-3.5" /></Button>
              </div>))}
            <Button size="sm" variant="ghost" onClick={() => setActions((as) => [...as, { type: "add_audit_note", params: {} }])}><Plus className="h-3 w-3" />Add action</Button>
          </div>
          <ErrorNote message={err} />
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save} loading={busy} disabled={name.trim().length < 3 || actions.length === 0}>Save workflow</Button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

"use client";
import Link from "next/link";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, AlertTriangle, ClipboardCheck, FileCheck2, GitBranch, Network, ShieldAlert, Timer, Gauge, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtMs, timeAgo, titleCase } from "@/lib/utils";
import { Badge, Button, EmptyState, ErrorNote, Panel, PanelHeader, Spinner } from "@/components/ui/primitives";
import { PageHeader, Stat } from "@/components/ui/shared";

const AXIS = { fontSize: 10, fill: "#8a8d96", fontFamily: "ui-monospace, monospace" };
const TIP = { contentStyle: { background: "#111318", border: "1px solid #343944", borderRadius: 4, fontSize: 11 }, labelStyle: { color: "#b9b6ae" }, cursor: { fill: "#ffffff08" } };
const SEV_COLOR: Record<string, string> = { critical: "#f2606b", high: "#f2606b", medium: "#f5b942", low: "#2dd4e6" };

export default function DashboardPage() {
  const d = useApi(() => api.dashboard(), [], { pollMs: 5000 });
  if (d.loading && !d.data) return <div className="grid h-64 place-items-center"><Spinner className="h-5 w-5" /></div>;
  if (d.error && !d.data) return <ErrorNote message={d.error} />;
  const s = d.data!;
  const empty = s.documents.total === 0;

  const sev = ["critical", "high", "medium", "low"].map((k) => ({ name: k, value: s.risk.by_severity[k] || 0 }));
  const types = Object.entries(s.documents.by_type).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  const stages = Object.entries(s.latency.stage_avg_ms).map(([k, v]) => ({ name: k.replace("_ms", ""), ms: v }));

  return (
    <>
      <PageHeader eyebrow="System intelligence" title="Dashboard" subtitle="Live metrics computed from the platform database — nothing here is simulated."
        actions={<Button asChild variant="primary"><Link href="/documents"><Upload className="h-3.5 w-3.5" />Upload documents</Link></Button>} />

      {empty && (
        <Panel className="mb-5"><EmptyState icon={<FileCheck2 className="h-8 w-8" />} title="No documents processed yet" hint="Upload PDFs, scans, spreadsheets or contracts. Metrics, risks and contradictions appear here as soon as processing finishes."
          action={<Button asChild variant="primary"><Link href="/documents">Go to document library</Link></Button>} /></Panel>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Documents processed" value={s.documents.ready} tone="emerald" icon={<FileCheck2 className="h-4 w-4" />} hint={`${s.documents.total} total · ${s.documents.processing} in flight · ${s.documents.failed} failed`} />
        <Stat label="Entities discovered" value={s.knowledge.entities.toLocaleString()} tone="violet" icon={<Network className="h-4 w-4" />} hint={`${s.documents.chunks.toLocaleString()} indexed chunks`} />
        <Stat label="Relationships" value={s.knowledge.relationships.toLocaleString()} tone="cyan" icon={<GitBranch className="h-4 w-4" />} hint="each carries source evidence" />
        <Stat label="Open review tasks" value={s.review.open} tone="amber" icon={<ClipboardCheck className="h-4 w-4" />}
          hint={Object.entries(s.review.open_by_priority).map(([k, v]) => `${v} ${k}`).join(" · ") || "queue is clear"} />
        <Stat label="High-risk findings" value={s.risk.high_risk_findings} tone="danger" icon={<ShieldAlert className="h-4 w-4" />} hint={`${s.risk.total_insights} insights in total`} />
        <Stat label="Contradictions" value={s.contradictions.total} tone="magenta" icon={<AlertTriangle className="h-4 w-4" />} hint={`${s.contradictions.open} unresolved`} />
        <Stat label="Average confidence" value={s.confidence.average === null ? "—" : s.confidence.average.toFixed(2)} tone="violet" icon={<Gauge className="h-4 w-4" />}
          hint={s.confidence.samples ? `engineering index · ${s.confidence.samples} samples` : "no scored outputs yet"} />
        <Stat label="Processing latency" value={fmtMs(s.latency.processing_avg_ms)} tone="cyan" icon={<Timer className="h-4 w-4" />}
          hint={s.latency.processing_p95_ms ? `p95 ${fmtMs(s.latency.processing_p95_ms)} · search ${fmtMs(s.latency.search_avg_ms)}` : "average per document"} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2">
          <PanelHeader title="Uploads · last 14 days" tone="cyan" />
          <div className="h-56 px-2 pb-2 pt-3">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={s.uploads_per_day}>
                <defs><linearGradient id="up" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2dd4e6" stopOpacity={0.35} /><stop offset="100%" stopColor="#2dd4e6" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke="#252932" strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="date" tick={AXIS} tickFormatter={(v: string) => v.slice(5)} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} width={26} />
                <Tooltip {...TIP} />
                <Area type="monotone" dataKey="documents" stroke="#2dd4e6" strokeWidth={1.5} fill="url(#up)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel>
          <PanelHeader title="Risk by severity" tone="danger" />
          <div className="h-56 px-2 pb-2 pt-3">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sev} layout="vertical" margin={{ left: 8 }}>
                <XAxis type="number" allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" tick={AXIS} axisLine={false} tickLine={false} width={54} />
                <Tooltip {...TIP} />
                <Bar dataKey="value" radius={[0, 2, 2, 0]}>{sev.map((e) => <Cell key={e.name} fill={SEV_COLOR[e.name]} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Panel>
          <PanelHeader title="Documents by type" tone="violet" />
          {types.length ? (
            <div className="h-52 px-2 pb-2 pt-3"><ResponsiveContainer width="100%" height="100%"><BarChart data={types} layout="vertical" margin={{ left: 12 }}>
              <XAxis type="number" allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" tick={AXIS} axisLine={false} tickLine={false} width={110} />
              <Tooltip {...TIP} /><Bar dataKey="value" fill="#8b7cf6" radius={[0, 2, 2, 0]} />
            </BarChart></ResponsiveContainer></div>
          ) : <EmptyState title="No classified documents" />}
        </Panel>
        <Panel>
          <PanelHeader title="Confidence distribution" tone="violet" right={<Badge tone="neutral">engineering index</Badge>} />
          <div className="h-52 px-2 pb-2 pt-3"><ResponsiveContainer width="100%" height="100%"><BarChart data={s.confidence.histogram}>
            <XAxis dataKey="bucket" tick={{ ...AXIS, fontSize: 8 }} axisLine={false} tickLine={false} interval={1} />
            <YAxis allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} width={24} />
            <Tooltip {...TIP} /><Bar dataKey="count" fill="#8b7cf6" radius={[2, 2, 0, 0]} />
          </BarChart></ResponsiveContainer></div>
        </Panel>
        <Panel>
          <PanelHeader title="Pipeline stage latency" tone="cyan" right={<span className="num text-2xs text-paper-mute">avg ms / doc</span>} />
          {stages.length ? (
            <div className="h-52 px-2 pb-2 pt-3"><ResponsiveContainer width="100%" height="100%"><BarChart data={stages} layout="vertical" margin={{ left: 12 }}>
              <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" tick={AXIS} axisLine={false} tickLine={false} width={70} />
              <Tooltip {...TIP} /><Bar dataKey="ms" fill="#2dd4e6" radius={[0, 2, 2, 0]} />
            </BarChart></ResponsiveContainer></div>
          ) : <EmptyState title="No timings yet" />}
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2">
          <PanelHeader title="Recent activity" icon={<Activity className="h-3.5 w-3.5" />} right={<Link href="/audit" className="text-2xs text-cyan hover:underline">Full audit trail →</Link>} />
          {s.recent_activity.length ? (
            <ul className="divide-y divide-ink-500/60">
              {s.recent_activity.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 px-3.5 py-2 text-xs">
                  <div className="flex min-w-0 items-center gap-2"><Badge tone="neutral">{a.action.replace(/_/g, " ")}</Badge><span className="truncate text-paper-dim">{a.summary}</span></div>
                  <span className="shrink-0 font-mono text-2xs text-paper-faint">{a.user} · {timeAgo(a.timestamp)}</span>
                </li>
              ))}
            </ul>
          ) : <EmptyState title="No activity yet" />}
        </Panel>
        <Panel>
          <PanelHeader title="Runtime" tone="violet" />
          <dl className="space-y-2 px-3.5 py-3 text-xs">
            <Row k="Reasoning provider" v={<Badge tone={s.system.llm.is_llm ? "violet" : "neutral"}>{s.system.llm.provider}</Badge>} />
            <Row k="Model" v={<span className="font-mono">{s.system.llm.model}</span>} />
            <Row k="OCR engine" v={<Badge tone={s.system.ocr.available ? "emerald" : "danger"}>{s.system.ocr.engine || "unavailable"}</Badge>} />
            <Row k="Statistical NER (spaCy)" v={<Badge tone={s.system.spacy_ner ? "emerald" : "amber"}>{s.system.spacy_ner ? "loaded" : "rules only"}</Badge>} />
            <Row k="OCR documents" v={<span className="num">{s.documents.ocr_documents}</span>} />
            {Object.entries(s.knowledge.entities_by_type).length > 0 && (
              <div className="border-t border-ink-500/60 pt-2"><p className="label-micro mb-1.5">Entity types</p><div className="flex flex-wrap gap-1">
                {Object.entries(s.knowledge.entities_by_type).sort((a, b) => b[1] - a[1]).map(([k, v]) => <Badge key={k}>{titleCase(k)} {v}</Badge>)}
              </div></div>
            )}
          </dl>
        </Panel>
      </div>
    </>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-3"><dt className="text-paper-mute">{k}</dt><dd className="text-paper-dim">{v}</dd></div>;
}

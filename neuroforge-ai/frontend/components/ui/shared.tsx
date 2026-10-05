"use client";
import Link from "next/link";
import { ArrowUpRight, FileText } from "lucide-react";
import { Badge, type Tone } from "./primitives";
import { cn, citationHref, confidenceTone, entityColor, fmtPct, SEVERITY_STYLE, titleCase } from "@/lib/utils";
import type { Confidence, DocStatus, EvidenceItem, Insight, Severity, TaskStatus } from "@/lib/types";

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string; subtitle?: string; actions?: React.ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <p className="label-micro mb-1">{eyebrow}</p>}
        <h1 className="text-xl font-semibold tracking-tight text-paper">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-paper-mute">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function SeverityBadge({ severity }: { severity: Severity | string }) {
  const s = SEVERITY_STYLE[(severity as Severity)] || SEVERITY_STYLE.info;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 font-mono text-2xs uppercase tracking-wider", s.text, s.bg, s.line)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />{severity}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  READY: "emerald", FAILED: "danger", QUEUED: "neutral", PROCESSING: "violet", INDEXING: "cyan",
  PENDING: "amber", NEEDS_EVIDENCE: "amber", ESCALATED: "danger", APPROVED: "emerald", REJECTED: "neutral", MODIFIED: "violet",
  open: "amber", verified: "emerald", rejected: "neutral", needs_review: "amber", resolved: "emerald", dismissed: "neutral",
};
export function StatusBadge({ status, progress }: { status: DocStatus | TaskStatus | string; progress?: number }) {
  const active = status === "PROCESSING" || status === "INDEXING";
  return (
    <Badge tone={STATUS_TONE[status] || "neutral"}>
      {active && <span className="h-1.5 w-1.5 animate-pulseDot rounded-full bg-current" />}
      {status.replace("_", " ")}{active && progress !== undefined ? ` ${Math.round(progress * 100)}%` : ""}
    </Badge>
  );
}

export function ConfidenceMeter({ confidence, compact }: { confidence: Confidence | { score: number; level: string }; compact?: boolean }) {
  const s = confidence.score;
  const color = confidence.level === "HIGH" ? "bg-emerald" : confidence.level === "MEDIUM" ? "bg-amber" : "bg-danger";
  return (
    <div className={cn("flex items-center gap-2", compact ? "w-28" : "w-full")}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-500"><div className={cn("h-full rounded-full", color)} style={{ width: `${Math.round(s * 100)}%` }} /></div>
      <span className={cn("num text-xs", confidenceTone(confidence.level))}>{s.toFixed(2)}</span>
    </div>
  );
}

export function EntityChip({ name, type, onClick }: { name: string; type: string; onClick?: () => void }) {
  const c = entityColor(type);
  const Comp: any = onClick ? "button" : "span";
  return (
    <Comp onClick={onClick} className="inline-flex items-center gap-1.5 rounded-sm border border-ink-400 bg-ink-700 px-1.5 py-0.5 text-xs text-paper-dim hover:border-ink-300">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />{name}<span className="font-mono text-2xs text-paper-faint">{type}</span>
    </Comp>
  );
}

/** A citation chip: clicking opens the source document at the cited page with the passage highlighted. */
export function CitationLink({ docId, page, name, bbox, label }: { docId: number; page: number; name: string; bbox?: number[] | null; label?: string }) {
  return (
    <Link href={citationHref(docId, page, bbox)} className="inline-flex items-center gap-1 rounded-sm border border-cyan-line bg-cyan-soft px-1.5 py-0.5 font-mono text-2xs text-cyan hover:bg-cyan/20" title={`Open ${name}, page ${page}`}>
      <FileText className="h-3 w-3" />{label || `${name} · p.${page}`}<ArrowUpRight className="h-3 w-3 opacity-60" />
    </Link>
  );
}

export function EvidenceCard({ e, id, highlight }: { e: EvidenceItem | Insight["evidence"][number]; id?: string; highlight?: string[] }) {
  const ev = e as any;
  const name = ev.document_name;
  const bbox = ev.source_location?.bbox ?? ev.bbox;
  const score = ev.relevance_score;
  const method = ev.retrieval_method;
  return (
    <div className="rounded border border-ink-500/80 bg-ink-700/60 p-2.5">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {id && <span className="rounded-sm bg-violet-soft px-1 font-mono text-2xs text-violet">{id}</span>}
          <CitationLink docId={ev.document_id} page={ev.page_number} name={name} bbox={bbox} />
          {ev.section && <span className="max-w-[260px] truncate text-2xs text-paper-faint" title={ev.section}>{ev.section}</span>}
        </div>
        <div className="flex items-center gap-1.5">
          {method && <Badge tone="cyan">{method}</Badge>}
          {typeof score === "number" && <span className="num text-2xs text-paper-mute">rel {score.toFixed(2)}</span>}
        </div>
      </div>
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-paper-dim">{highlightText(ev.text, highlight)}</p>
    </div>
  );
}

export function highlightText(text: string, terms?: string[]) {
  if (!terms || !terms.length) return text;
  const esc = terms.filter((t) => t.length > 2).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!esc.length) return text;
  const re = new RegExp(`(${esc.join("|")})`, "gi");
  // split() with one capture group puts the matches at odd indices
  return text.split(re).map((p, i) => (i % 2 === 1 ? <mark key={i} className="hl">{p}</mark> : p));
}

export function Stat({ label, value, hint, tone = "neutral", icon }: { label: string; value: React.ReactNode; hint?: string; tone?: Tone; icon?: React.ReactNode }) {
  const bar: Record<Tone, string> = { neutral: "bg-ink-400", violet: "bg-violet", cyan: "bg-cyan", emerald: "bg-emerald", amber: "bg-amber", danger: "bg-danger", magenta: "bg-magenta" };
  return (
    <div className="relative overflow-hidden rounded-md border border-ink-500/80 bg-ink-800/90 px-3.5 py-3">
      <span className={cn("absolute inset-y-0 left-0 w-[2px]", bar[tone])} />
      <div className="flex items-center justify-between"><p className="label-micro">{label}</p>{icon && <span className="text-paper-faint">{icon}</span>}</div>
      <p className="num mt-1.5 text-2xl font-medium leading-none text-paper">{value}</p>
      {hint && <p className="mt-1.5 text-2xs text-paper-mute">{hint}</p>}
    </div>
  );
}

export function KeyVal({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex items-baseline justify-between gap-3 border-b border-ink-500/50 py-1.5 text-xs last:border-0"><span className="text-paper-mute">{k}</span><span className="text-right text-paper-dim">{v}</span></div>;
}

export function ConfidenceBreakdown({ c }: { c: Confidence }) {
  return (
    <div className="space-y-1.5">
      {Object.entries(c.breakdown).map(([k, v]) => (
        <div key={k} className="grid grid-cols-[130px_1fr_36px] items-center gap-2 text-2xs">
          <span className="text-paper-mute">{titleCase(k)}</span>
          <div className="h-1 overflow-hidden rounded-full bg-ink-500"><div className="h-full bg-violet" style={{ width: `${v * 100}%` }} /></div>
          <span className="num text-right text-paper-dim">{v.toFixed(2)}</span>
        </div>
      ))}
      {c.penalties?.contradiction > 0 && <p className="text-2xs text-magenta">Contradiction penalty −{fmtPct(c.penalties.contradiction)}</p>}
      <p className="pt-1 text-2xs leading-snug text-paper-faint">{c.disclaimer}</p>
    </div>
  );
}

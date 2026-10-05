"use client";
import { AlertOctagon, BrainCircuit, ShieldCheck, ShieldX, Swords } from "lucide-react";
import type { AskResponse, EvidenceItem } from "@/lib/types";
import { cn, confidenceTone, titleCase } from "@/lib/utils";
import { Badge, Panel, PanelHeader } from "@/components/ui/primitives";
import { CitationLink, ConfidenceBreakdown, ConfidenceMeter, EntityChip, EvidenceCard, SeverityBadge } from "@/components/ui/shared";

export function AnswerView({ a }: { a: AskResponse }) {
  const ev = new Map<string, EvidenceItem>(a.evidence.map((e) => [e.evidence_id, e]));
  const cite = (id: string) => {
    const e = ev.get(id);
    return e ? <CitationLink key={id} docId={e.document_id} page={e.page_number} name={e.document_name} bbox={e.source_location.bbox} label={`${id} · ${e.document_name} p.${e.page_number}`} /> : null;
  };

  if (a.refused) {
    return (
      <Panel className="border-amber-line">
        <PanelHeader title="Refused — insufficient evidence" tone="amber" icon={<ShieldX className="h-3.5 w-3.5" />} />
        <div className="space-y-2 p-4 text-sm">
          <p className="text-paper-dim">{a.refusal_reason || "The retrieved evidence does not support an answer."}</p>
          <p className="text-xs text-paper-mute">The platform refuses rather than guessing. Try rephrasing, broadening the filters, or uploading the relevant document.</p>
          {a.validation.unsupported_claims.length > 0 && (<div className="rounded border border-ink-500 p-2.5"><p className="label-micro mb-1">Claims dropped during validation</p>{a.validation.unsupported_claims.map((c, i) => <p key={i} className="text-xs text-paper-mute">✗ {c.statement} <span className="text-danger">({c.reason})</span></p>)}</div>)}
        </div>
      </Panel>
    );
  }

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader title="Grounded answer" tone="violet" icon={<BrainCircuit className="h-3.5 w-3.5" />} right={<div className="flex items-center gap-1.5"><Badge tone="violet">{a.provider}</Badge><Badge>{a.prompt_version}</Badge><span className="num text-2xs text-paper-faint">{a.latency_ms + a.retrieval_latency_ms} ms</span></div>} />
        <div className="grid gap-4 p-4 lg:grid-cols-[1fr_300px]">
          <div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-paper">{a.summary}</p>
            {a.uncertainty_notes.length > 0 && <ul className="mt-3 space-y-1">{a.uncertainty_notes.map((n, i) => <li key={i} className="text-xs text-paper-mute">ⓘ {n}</li>)}</ul>}
          </div>
          <div className="rounded border border-ink-500 bg-ink-700/50 p-3">
            <div className="mb-2 flex items-center justify-between"><span className="label-micro">Confidence</span><span className={cn("font-mono text-xs font-medium", confidenceTone(a.confidence.level))}>{a.confidence.level}</span></div>
            <ConfidenceMeter confidence={a.confidence} />
            <div className="mt-3"><ConfidenceBreakdown c={a.confidence} /></div>
          </div>
        </div>
      </Panel>

      {a.conflicts.length > 0 && (
        <Panel className="border-magenta-line">
          <PanelHeader title={`Conflict detected · ${a.conflicts.length}`} tone="magenta" icon={<Swords className="h-3.5 w-3.5" />} right={<span className="text-2xs text-paper-mute">Not resolved automatically — both sides are shown</span>} />
          <div className="divide-y divide-ink-500/60">
            {a.conflicts.map((c, i) => (
              <div key={i} className="grid gap-3 p-3.5 md:grid-cols-[170px_1fr_1fr]">
                <div><p className="text-sm font-medium text-magenta">{c.topic}</p><p className="num text-2xs text-paper-mute">conflict confidence {c.confidence.toFixed(2)}</p></div>
                {[c.evidence_a, c.evidence_b].map((e, j) => (
                  <div key={j} className="rounded border border-magenta-line/60 bg-magenta-soft p-2.5"><div className="mb-1 flex items-center justify-between"><span className="num text-sm font-medium text-paper">{e.value}</span><CitationLink docId={e.document_id} page={e.page_number} name={e.document_name} /></div><p className="text-xs italic text-paper-mute">“{e.text}”</p></div>
                ))}
              </div>
            ))}
          </div>
        </Panel>
      )}

      {a.other_conflicts.length > 0 && (
        <details className="rounded-md border border-ink-500/80 bg-ink-800/60 px-3.5 py-2 text-xs">
          <summary className="cursor-pointer text-paper-mute">{a.other_conflicts.length} other conflict(s) exist among the retrieved documents but do not affect this answer</summary>
          <ul className="mt-2 space-y-1.5">{a.other_conflicts.map((c, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2 text-paper-dim"><Badge tone="magenta">{c.topic}</Badge><span className="num">{c.value_a}</span><span className="text-paper-faint">vs</span><span className="num">{c.value_b}</span>
              <CitationLink docId={c.evidence_a.document_id} page={c.evidence_a.page_number} name={c.evidence_a.document_name} label="A" /><CitationLink docId={c.evidence_b.document_id} page={c.evidence_b.page_number} name={c.evidence_b.document_name} label="B" /></li>))}</ul>
        </details>
      )}

      <div className="space-y-3">
        {a.findings.map((f, i) => (
          <Panel key={i}>
            <PanelHeader title={`Finding #${i + 1}`} tone={f.severity === "info" ? "cyan" : "danger"} right={<div className="flex items-center gap-2"><SeverityBadge severity={f.severity} /><ConfidenceMeter compact confidence={f.confidence} /></div>} />
            <div className="space-y-3 p-4">
              <h3 className="text-sm font-semibold text-paper">{f.title}</h3>
              <ul className="space-y-2">
                {f.statements.map((s, j) => (
                  <li key={j} className="rounded border border-ink-500/70 bg-ink-700/40 p-2.5">
                    <div className="mb-1 flex items-center gap-1.5"><Badge tone={s.type === "fact" ? "emerald" : "violet"}>{s.type}</Badge><span className="num text-2xs text-paper-faint">support {s.support.toFixed(2)}</span></div>
                    <p className="text-sm text-paper-dim">{s.text}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">{s.evidence.map(cite)}</div>
                  </li>
                ))}
              </ul>
              {f.reasoning && <p className="text-xs text-paper-mute"><span className="text-violet">Reasoning · </span>{f.reasoning}</p>}
              {f.contradictory_evidence.length > 0 && <div className="flex flex-wrap items-center gap-1.5 text-xs text-magenta"><AlertOctagon className="h-3.5 w-3.5" />Contradictory evidence:{f.contradictory_evidence.map(cite)}</div>}
              {f.recommended_action && <p className="text-xs text-paper-dim"><span className="text-amber">Recommended action · </span>{f.recommended_action}</p>}
              {f.entities.length > 0 && <div className="flex flex-wrap gap-1">{f.entities.map((e) => <Badge key={e}>{e}</Badge>)}</div>}
            </div>
          </Panel>
        ))}
      </div>

      <Panel>
        <PanelHeader title="Validation · no fabricated citations" tone="emerald" icon={<ShieldCheck className="h-3.5 w-3.5" />} />
        <div className="grid gap-3 p-4 text-xs md:grid-cols-3">
          <div><p className="label-micro mb-1">Citation coverage</p><p className="num text-lg text-emerald">{(a.validation.citation_coverage * 100).toFixed(0)}%</p><p className="text-paper-mute">{a.validation.supported_statements} of {a.validation.total_statements} generated statements verified against cited evidence</p></div>
          <div className="md:col-span-2">
            <p className="label-micro mb-1">Dropped as unsupported ({a.validation.unsupported_claims.length})</p>
            {a.validation.unsupported_claims.length === 0 ? <p className="text-paper-mute">Nothing had to be removed.</p> : a.validation.unsupported_claims.map((c, i) => <p key={i} className="text-paper-mute">✗ {c.statement} <span className="text-danger">— {c.reason}</span></p>)}
            {a.validation.fallback && <p className="mt-1 text-amber">Fallback used: {a.validation.fallback}</p>}
          </div>
        </div>
      </Panel>

      <Panel>
        <PanelHeader title={`Evidence set · ${a.evidence.length}`} tone="cyan" />
        <div className="grid gap-2 p-3 lg:grid-cols-2">{a.evidence.map((e) => <EvidenceCard key={e.evidence_id} e={e} id={e.evidence_id} />)}</div>
      </Panel>
    </div>
  );
}

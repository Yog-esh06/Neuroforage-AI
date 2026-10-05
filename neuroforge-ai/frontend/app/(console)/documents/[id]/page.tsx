"use client";
import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight, Download, Layers, ScanLine, Sparkles } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { cn, entityColor, fmtBytes, fmtMs, fmtPct, titleCase } from "@/lib/utils";
import type { PageElement } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorNote, Panel, PanelHeader, Spinner, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { ConfidenceMeter, EntityChip, EvidenceCard, KeyVal, SeverityBadge, StatusBadge } from "@/components/ui/shared";

const EL_COLOR: Record<string, string> = { heading: "#8b7cf6", paragraph: "#2dd4e6", list: "#34d399", table: "#f5b942", image: "#e268d8", figure: "#e268d8", header: "#5d6069", footer: "#5d6069" };

export default function Page() {
  return <Suspense fallback={<div className="grid h-64 place-items-center"><Spinner /></div>}><Viewer /></Suspense>;
}

function Viewer() {
  const { id } = useParams<{ id: string }>();
  const docId = Number(id);
  const router = useRouter();
  const sp = useSearchParams();
  const { can } = useAuth();
  const page = Math.max(1, Number(sp.get("page") || 1));
  const hl = useMemo(() => { const v = (sp.get("h") || "").split(",").map(Number); return v.length === 4 && v.every((n) => !Number.isNaN(n)) ? v : null; }, [sp]);

  const doc = useApi(() => api.document(docId), [docId], { pollMs: 2500, pollWhile: (d) => ["QUEUED", "PROCESSING", "INDEXING"].includes(d.status) });
  const pages = useApi(() => api.pages(docId), [docId, doc.data?.status], { enabled: doc.data?.status === "READY" });
  const pg = useApi(() => api.page(docId, page), [docId, page, doc.data?.status], { enabled: doc.data?.status === "READY" });
  const findings = useApi(() => api.docInsights(docId), [docId, doc.data?.status], { enabled: doc.data?.status === "READY" });

  const [img, setImg] = useState<string | null>(null);
  const [imgErr, setImgErr] = useState<string | null>(null);
  const [view, setView] = useState<"visual" | "text">("visual");
  const [showEls, setShowEls] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    let url: string | null = null; let cancelled = false;
    setImg(null); setImgErr(null);
    if (doc.data?.status !== "READY" || !["pdf", "image"].includes(doc.data.file_kind)) { if (doc.data?.status === "READY") { setImgErr("No visual rendering for this file type — showing extracted text."); setView("text"); } return; }
    api.pageImage(docId, page).then((u) => { if (cancelled) URL.revokeObjectURL(u); else { url = u; setImg(u); } }).catch((e) => setImgErr(e instanceof ApiError ? e.message : String(e)));
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [docId, page, doc.data?.status, doc.data?.file_kind]);

  const go = (n: number) => router.replace(`/documents/${docId}?page=${n}`);

  if (doc.loading && !doc.data) return <div className="grid h-64 place-items-center"><Spinner className="h-5 w-5" /></div>;
  if (doc.error && !doc.data) return <ErrorNote message={doc.error} />;
  const d = doc.data!;
  if (d.status !== "READY") {
    return (
      <Panel><EmptyState icon={d.status === "FAILED" ? undefined : <Spinner className="h-6 w-6" />} title={d.status === "FAILED" ? "Processing failed" : `Processing — ${d.job?.stage ?? d.status.toLowerCase()}`}
        hint={d.status === "FAILED" ? d.error ?? undefined : "This page updates automatically when extraction, OCR, indexing and analysis finish."}
        action={<div className="flex items-center gap-2"><StatusBadge status={d.status} progress={d.job?.progress} />{d.status === "FAILED" && can("analyst") && <Button onClick={() => api.reprocess(docId).then(doc.reload)}>Retry</Button>}<Button asChild variant="ghost"><Link href="/documents">Back to library</Link></Button></div>} /></Panel>
    );
  }

  const p = pg.data;
  const elements = p?.elements ?? [];
  const W = p?.width || 595, H = p?.height || 842;
  const box = (b: number[]) => ({ left: `${(b[0] / W) * 100}%`, top: `${(b[1] / H) * 100}%`, width: `${((b[2] - b[0]) / W) * 100}%`, height: `${((b[3] - b[1]) / H) * 100}%` });
  const pageInsights = findings.data?.insights.filter((i) => i.evidence.some((e) => e.page_number === page)) ?? [];

  return (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/documents" className="label-micro hover:text-paper">← Library</Link>
          <h1 className="mt-1 text-xl font-semibold tracking-tight">{d.filename}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-paper-mute">
            <Badge tone="violet">{d.document_type}</Badge><span className="num">confidence {d.classification_confidence.toFixed(2)}</span><span>·</span><span>{d.classification_method}</span>
            {d.ocr_used && <Badge tone="cyan"><ScanLine className="h-3 w-3" />OCR {fmtPct(d.ocr_confidence)}</Badge>}
            <span>·</span><span>{d.page_count} page(s)</span><span>·</span><span>{fmtBytes(d.size_bytes)}</span><span>·</span><span>processed in {fmtMs(d.processing_ms)}</span>
            {d.flags.map((f) => <Badge key={f} tone="danger">{f}</Badge>)}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => api.downloadFile(docId, d.filename)}><Download className="h-3.5 w-3.5" />Original</Button>
          <Button variant="data" asChild><Link href={`/search?doc=${docId}`}><Sparkles className="h-3.5 w-3.5" />Ask this document</Link></Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[150px_minmax(0,1fr)_400px]">
        {/* page rail */}
        <Panel className="hidden max-h-[78vh] overflow-y-auto xl:block">
          <PanelHeader title="Pages" />
          <ul className="p-1.5">
            {(pages.data ?? []).map((pp) => (
              <li key={pp.page_number}><button onClick={() => go(pp.page_number)} className={cn("flex w-full items-center justify-between rounded px-2 py-1.5 text-xs", pp.page_number === page ? "bg-ink-600 text-paper" : "text-paper-mute hover:bg-ink-700")}>
                <span className="num">{pp.page_number}</span><span className="flex items-center gap-1">{pp.ocr_used && <ScanLine className="h-3 w-3 text-cyan" />}<span className="num text-2xs text-paper-faint">{pp.chars}c</span></span></button></li>
            ))}
          </ul>
        </Panel>

        {/* viewer */}
        <Panel className="min-w-0">
          <PanelHeader title="Document" tone="cyan" right={
            <div className="flex items-center gap-1.5">
              <div className="flex rounded border border-ink-400 p-0.5">{(["visual", "text"] as const).map((v) => <button key={v} onClick={() => setView(v)} disabled={v === "visual" && !img && !!imgErr} className={cn("rounded-sm px-2 py-0.5 font-mono text-2xs uppercase disabled:opacity-30", view === v ? "bg-ink-500 text-paper" : "text-paper-mute")}>{v === "visual" ? "Original" : "Extracted"}</button>)}</div>
              <Button size="sm" variant={showEls ? "data" : "ghost"} onClick={() => setShowEls((v) => !v)} title="Overlay detected layout elements"><Layers className="h-3.5 w-3.5" />Layout</Button>
              <Button size="icon" variant="ghost" disabled={page <= 1} onClick={() => go(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
              <span className="num text-xs text-paper-dim">{page} / {d.page_count}</span>
              <Button size="icon" variant="ghost" disabled={page >= d.page_count} onClick={() => go(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
            </div>} />
          <div className="max-h-[78vh] overflow-auto bg-ink-900/60 p-3">
            {view === "visual" && img ? (
              <div className="relative mx-auto w-full max-w-[760px] select-none">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={img} alt={`Page ${page} of ${d.filename}`} className="block w-full rounded-sm border border-ink-400 bg-white" />
                {showEls && elements.filter((e) => e.bbox).map((e) => (
                  <button key={e.id} onClick={() => setSelected(e.id)} title={`${e.type}${e.section ? " · " + e.section : ""}`} className="absolute border" style={{ ...box(e.bbox!), borderColor: EL_COLOR[e.type] || "#fff", background: selected === e.id ? `${EL_COLOR[e.type]}33` : `${EL_COLOR[e.type]}12` }} />
                ))}
                {hl && <div className="pointer-events-none absolute rounded-sm border-2 border-amber bg-amber/20 shadow-[0_0_0_2px_rgba(245,185,66,0.15)]" style={box(hl)} aria-label="Cited passage" />}
              </div>
            ) : view === "visual" && !imgErr ? <div className="grid h-64 place-items-center"><Spinner /></div> : (
              <div className="mx-auto max-w-[760px] space-y-2">
                {imgErr && view === "visual" && <ErrorNote message={imgErr} />}
                {pg.loading && !p ? <Spinner /> : elements.length === 0 ? <p className="text-xs text-paper-mute">No extractable text on this page.</p> : elements.map((e) => <ElementBlock key={e.id} e={e} active={selected === e.id} onClick={() => setSelected(e.id)} />)}
              </div>
            )}
          </div>
        </Panel>

        {/* intelligence panel */}
        <Panel className="min-w-0">
          <Tabs defaultValue="findings">
            <TabsList className="px-2">
              {[["findings", `Findings ${pageInsights.length || ""}`], ["entities", "Entities"], ["tables", "Tables"], ["structure", "Structure"], ["meta", "Meta"]].map(([v, l]) => <TabsTrigger key={v} value={v}>{l}</TabsTrigger>)}
            </TabsList>
            <div className="max-h-[70vh] overflow-y-auto p-3.5">
              <TabsContent value="findings" className="space-y-3">
                {findings.loading && !findings.data ? <Spinner /> : null}
                <p className="label-micro">On this page</p>
                {pageInsights.length === 0 && <p className="text-xs text-paper-mute">No findings are anchored to this page.</p>}
                {pageInsights.map((i) => <InsightBlock key={i.id} i={i} />)}
                {(findings.data?.contradictions.length ?? 0) > 0 && (<><p className="label-micro pt-2 text-magenta">Contradictions with other documents</p>
                  {findings.data!.contradictions.map((c) => (
                    <div key={c.id} className="rounded border border-magenta-line bg-magenta-soft p-2.5 text-xs"><div className="flex items-center justify-between"><span className="font-medium text-magenta">{c.topic}</span><span className="num text-2xs text-paper-mute">{c.confidence.toFixed(2)}</span></div>
                      <p className="mt-1 text-paper-dim">{c.evidence_a.document_name} p.{c.evidence_a.page_number}: <b>{c.evidence_a.value}</b></p><p className="text-paper-dim">{c.evidence_b.document_name} p.{c.evidence_b.page_number}: <b>{c.evidence_b.value}</b></p></div>
                  ))}</>)}
                <p className="label-micro pt-2">All findings in document ({findings.data?.insights.length ?? 0})</p>
                <ul className="space-y-1">{(findings.data?.insights ?? []).slice(0, 40).map((i) => (
                  <li key={i.id}><button className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-ink-700" onClick={() => go(i.evidence[0]?.page_number ?? 1)}><span className="truncate text-paper-dim">{i.title}</span><span className="flex shrink-0 items-center gap-1.5"><SeverityBadge severity={i.severity} /><span className="num text-2xs text-paper-faint">p.{i.evidence[0]?.page_number}</span></span></button></li>))}</ul>
              </TabsContent>
              <TabsContent value="entities" className="space-y-2">
                <p className="label-micro">Entities on page {page}</p>
                <div className="flex flex-wrap gap-1.5">{(p?.entities ?? []).map((e) => <EntityChip key={e.id} name={e.name} type={e.type} onClick={() => router.push(`/knowledge?entity=${e.id}`)} />)}</div>
                {p && p.entities.length === 0 && <p className="text-xs text-paper-mute">No entities extracted on this page.</p>}
                <p className="pt-2 text-2xs text-paper-faint">Click an entity to open it in the knowledge graph.</p>
              </TabsContent>
              <TabsContent value="tables" className="space-y-4">
                {elements.filter((e) => e.type === "table").map((e) => <TableView key={e.id} e={e} />)}
                {!elements.some((e) => e.type === "table") && <p className="text-xs text-paper-mute">No tables detected on this page.</p>}
              </TabsContent>
              <TabsContent value="structure" className="space-y-1">
                <p className="label-micro mb-1">Layout elements · reading order</p>
                {elements.map((e) => (
                  <button key={e.id} onClick={() => { setSelected(e.id); setShowEls(true); }} className={cn("flex w-full items-start gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-ink-700", selected === e.id && "bg-ink-600")}>
                    <span className="mt-0.5 shrink-0 rounded-sm px-1 font-mono text-2xs uppercase" style={{ color: EL_COLOR[e.type], background: `${EL_COLOR[e.type]}18` }}>{e.type}{e.level ? e.level : ""}</span>
                    <span className="line-clamp-2 text-paper-dim">{e.text || "(visual)"}</span></button>))}
              </TabsContent>
              <TabsContent value="meta">
                <KeyVal k="Status" v={<StatusBadge status={d.status} />} /><KeyVal k="Classification" v={`${d.document_type} (${d.classification_confidence.toFixed(2)})`} /><KeyVal k="Method" v={d.classification_method} />
                <KeyVal k="Extraction (this page)" v={p?.method} /><KeyVal k="OCR" v={d.ocr_used ? `yes · ${fmtPct(d.ocr_confidence)}` : "not needed (native text layer)"} />
                <KeyVal k="Chunks" v={d.counts.chunks} /><KeyVal k="Entities" v={d.counts.entities} /><KeyVal k="Tables" v={d.counts.tables} /><KeyVal k="Insights" v={d.counts.insights} /><KeyVal k="Contradictions" v={d.counts.contradictions} />
                <KeyVal k="Version" v={`v${d.version}`} /><KeyVal k="SHA-256" v={<span className="font-mono text-2xs">{d.sha256.slice(0, 16)}…</span>} />
                {d.job && <KeyVal k="Stage timings" v={<span className="font-mono text-2xs">{Object.entries(d.job.timings_ms || {}).map(([k, v]) => `${k.replace("_ms", "")} ${v}`).join(" · ")}</span>} />}
                <p className="label-micro mt-3 mb-1.5">Classifier scores</p>
                {Object.entries(d.classification_detail?.scores ?? {}).map(([k, v]) => <div key={k} className="flex justify-between text-xs"><span className="text-paper-mute">{k}</span><span className="num text-paper-dim">{v}</span></div>)}
                {d.job?.error && <ErrorNote message={d.job.error} />}
              </TabsContent>
            </div>
          </Tabs>
        </Panel>
      </div>
    </>
  );
}

function ElementBlock({ e, active, onClick }: { e: PageElement; active: boolean; onClick: () => void }) {
  const base = cn("rounded border px-3 py-2 text-left transition-colors w-full", active ? "border-violet bg-violet-soft" : "border-ink-500/70 bg-ink-800/80 hover:border-ink-300");
  if (e.type === "table" && e.table) return <div className={base} onClick={onClick}><TableView e={e} /></div>;
  const cls = e.type === "heading" ? "text-sm font-semibold text-paper" : e.type === "footer" || e.type === "header" ? "text-2xs italic text-paper-faint" : "text-sm leading-relaxed text-paper-dim";
  return <button className={base} onClick={onClick}><span className="label-micro !text-[9px]">{e.type}{e.confidence ? ` · ocr ${e.confidence.toFixed(2)}` : ""}</span><p className={cn("mt-0.5 whitespace-pre-wrap", cls)}>{e.text || "(visual element)"}</p></button>;
}

function TableView({ e }: { e: PageElement }) {
  const t = e.table;
  if (!t) return <p className="text-xs text-paper-mute">{e.text}</p>;
  return (
    <div>
      {e.section && <p className="mb-1 text-2xs text-paper-faint">{e.section}</p>}
      <div className="overflow-x-auto rounded border border-ink-500"><table className="w-full text-xs"><thead><tr className="bg-ink-600">{t.headers.map((h, i) => <th key={i} className="px-2 py-1 text-left font-medium text-paper-dim">{h}<span className="ml-1 font-mono text-[9px] text-cyan">{t.profile.columns[i]?.type}</span></th>)}</tr></thead>
        <tbody>{t.rows.map((r, i) => <tr key={i} className={cn("border-t border-ink-500/60", t.profile.total_row_index === i && "bg-amber-soft")}>{r.map((c, j) => <td key={j} className="px-2 py-1 text-paper-dim">{c}</td>)}</tr>)}</tbody></table></div>
      {t.profile.total_checks.map((c) => (
        <p key={c.column} className={cn("mt-1.5 text-2xs", c.consistent ? "text-emerald" : "text-danger")}>{c.consistent ? "✓" : "✗"} {c.column}: stated total {c.claimed_total.toLocaleString()} {c.consistent ? "matches" : "≠"} computed {c.calculated_sum.toLocaleString()}</p>))}
    </div>
  );
}

function InsightBlock({ i }: { i: import("@/lib/types").Insight }) {
  return (
    <div className="rounded border border-ink-500/80 bg-ink-700/50 p-2.5">
      <div className="mb-1 flex items-center justify-between gap-2"><SeverityBadge severity={i.severity} /><ConfidenceMeter compact confidence={{ score: i.confidence, level: i.confidence >= 0.75 ? "HIGH" : i.confidence >= 0.5 ? "MEDIUM" : "LOW" }} /></div>
      <p className="text-xs font-medium text-paper">{i.title}</p>
      <p className="mt-1 text-xs italic text-paper-mute">“{i.description}”</p>
      {i.recommended_action && <p className="mt-1.5 text-xs text-paper-dim"><span className="text-amber">Action:</span> {i.recommended_action}</p>}
      <div className="mt-1.5 flex items-center gap-1.5"><Badge>{i.method}</Badge><StatusBadge status={i.status} /></div>
    </div>
  );
}

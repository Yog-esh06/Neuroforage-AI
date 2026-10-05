"use client";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactFlow, { Background, Controls, Handle, MarkerType, MiniMap, Position, type Edge, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import { Network, Route as RouteIcon, Search } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi, useDebounced } from "@/lib/hooks";
import { cn, entityColor, titleCase } from "@/lib/utils";
import type { EntityDetail, EntityNode, GraphEdge, GraphView } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorNote, Input, Panel, PanelHeader, Select, Spinner } from "@/components/ui/primitives";
import { CitationLink, EntityChip, KeyVal, PageHeader } from "@/components/ui/shared";

const TYPE_OPTIONS = ["ORG", "PERSON", "CONTRACT", "LOCATION", "MONEY", "DATE", "REGULATION", "TECHNOLOGY", "PRODUCT", "EVENT", "METRIC"];

function EntityNodeView({ data, selected }: NodeProps<{ e: EntityNode }>) {
  const e = data.e; const c = entityColor(e.type);
  return (
    <div className={cn("rounded border bg-ink-800 px-2.5 py-1.5 text-xs shadow-lg", selected ? "ring-1 ring-offset-0" : "")} style={{ borderColor: selected || e.is_center ? c : "#343944", boxShadow: e.is_center ? `0 0 0 1px ${c}55, 0 0 18px ${c}22` : undefined, minWidth: 90, maxWidth: 190, ...(selected ? { outline: `1px solid ${c}` } : {}) }}>
      <Handle type="target" position={Position.Top} className="!h-1 !w-1 !border-0 !bg-ink-400" />
      <div className="flex items-center gap-1.5"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: c }} /><span className="truncate font-medium text-paper">{e.name}</span></div>
      <div className="mt-0.5 flex items-center justify-between font-mono text-[9px] uppercase tracking-wider text-paper-faint"><span>{e.type}</span><span>{e.mentions}×</span></div>
      <Handle type="source" position={Position.Bottom} className="!h-1 !w-1 !border-0 !bg-ink-400" />
    </div>
  );
}
const nodeTypes = { entity: EntityNodeView };

/** Deterministic radial layout: centre, then rings by hop distance. */
function layout(view: GraphView): { nodes: Node[]; edges: Edge[] } {
  const byHop = new Map<number, EntityNode[]>();
  view.nodes.forEach((n) => { const h = n.hop ?? 0; byHop.set(h, [...(byHop.get(h) ?? []), n]); });
  const nodes: Node[] = [];
  const positioned = view.nodes.length > 0 && view.nodes.every((n) => typeof (n as EntityNode & { x?: number }).x === "number");
  const overview = !positioned && view.nodes.every((n) => (n.hop ?? 0) === 0) && view.nodes.length > 1 && !view.nodes.some((n) => n.is_center);
  if (positioned) {
    view.nodes.forEach((n) => { const p = n as EntityNode & { x: number; y: number }; nodes.push({ id: String(n.id), type: "entity", position: { x: p.x, y: p.y }, data: { e: n } }); });
  } else if (overview) {
    const ordered = [...view.nodes].sort((a, b) => a.type.localeCompare(b.type) || b.degree - a.degree);
    const R = Math.max(220, ordered.length * 22);
    ordered.forEach((n, i) => { const a = (i / ordered.length) * Math.PI * 2; nodes.push({ id: String(n.id), type: "entity", position: { x: Math.cos(a) * R, y: Math.sin(a) * R * 0.7 }, data: { e: n } }); });
  } else {
    [...byHop.entries()].forEach(([hop, list]) => {
      const R = hop === 0 ? 0 : 230 + (hop - 1) * 210;
      list.sort((a, b) => a.type.localeCompare(b.type));
      list.forEach((n, i) => { const a = (i / Math.max(list.length, 1)) * Math.PI * 2 - Math.PI / 2 + hop * 0.35; nodes.push({ id: String(n.id), type: "entity", position: { x: Math.cos(a) * R * 1.25, y: Math.sin(a) * R }, data: { e: n } }); });
    });
  }
  const edges: Edge[] = view.edges.map((e) => ({
    id: `e${e.id}`, source: String(e.source), target: String(e.target), label: e.relation.replace(/_/g, " "), data: e,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: e.relation === "co_occurs_with" ? "#5d6069" : "#8b7cf6" },
    style: { stroke: e.relation === "co_occurs_with" ? "#3a3e49" : "#8b7cf6", strokeWidth: 0.8 + e.confidence * 1.2, strokeDasharray: e.relation === "co_occurs_with" ? "4 4" : undefined },
    labelStyle: { fill: "#b9b6ae", fontSize: 9, fontFamily: "ui-monospace, monospace" }, labelBgStyle: { fill: "#0d0e12" }, labelBgPadding: [3, 2] as [number, number],
  }));
  return { nodes, edges };
}

export default function Page() { return <Suspense fallback={<Spinner />}><Explorer /></Suspense>; }

function Explorer() {
  const sp = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 250);
  const [type, setType] = useState("");
  const [focus, setFocus] = useState<number | null>(sp.get("entity") ? Number(sp.get("entity")) : null);
  const [hops, setHops] = useState(1);
  const [minConf, setMinConf] = useState(0);
  const [hideWeak, setHideWeak] = useState(true);
  const [selEdge, setSelEdge] = useState<GraphEdge | null>(null);
  const [pathTarget, setPathTarget] = useState("");
  const [paths, setPaths] = useState<Awaited<ReturnType<typeof api.graphPaths>> | null>(null);
  const [pathErr, setPathErr] = useState<string | null>(null);

  const results = useApi(() => api.entities({ q: dq, type: type ? [type] : undefined, limit: 40 }), [dq, type]);
  const stats = useApi(() => api.knowledgeStats(), []);
  const graph = useApi<GraphView>(() => (focus ? api.entityGraph(focus, { hops, max_nodes: 70, min_confidence: minConf }) : api.graphOverview(70)), [focus, hops, minConf]);
  const detail = useApi<EntityDetail | null>(() => (focus ? api.entity(focus) : Promise.resolve(null)), [focus]);

  useEffect(() => { setPaths(null); setPathErr(null); setSelEdge(null); }, [focus]);

  // First visit: open the most connected entity (a readable neighbourhood beats a sparse whole-graph overview).
  const [autoFocused, setAutoFocused] = useState(false);
  useEffect(() => {
    if (!autoFocused && focus === null && !sp.get("entity") && !q && !type && results.data && results.data.length > 0) {
      setAutoFocused(true); setHops(2); setFocus(results.data[0].id);
    }
  }, [results.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const view = useMemo(() => {
    const g = graph.data ?? { nodes: [], edges: [] };
    const edges = hideWeak ? g.edges.filter((e) => e.relation !== "co_occurs_with") : g.edges;
    return layout({ nodes: g.nodes, edges });
  }, [graph.data, hideWeak]);

  const onNodeClick = useCallback((_: unknown, n: Node) => { setFocus(Number(n.id)); router.replace(`/knowledge?entity=${n.id}`); }, [router]);
  async function trace() {
    setPathErr(null); setPaths(null);
    if (!focus) return;
    try {
      const cand = await api.entities({ q: pathTarget, limit: 1 });
      if (!cand.length) { setPathErr(`No entity matches “${pathTarget}”.`); return; }
      const p = await api.graphPaths(focus, cand[0].id);
      setPaths(p); if (!p.length) setPathErr(`No path between these entities within 4 hops.`);
    } catch (e) { setPathErr(e instanceof ApiError ? e.message : String(e)); }
  }
  const ent = detail.data?.entity;

  return (
    <>
      <PageHeader eyebrow="Corpus" title="Knowledge explorer" subtitle="Entities and relationships extracted from your documents. Every edge carries the sentence, document and page it came from."
        actions={stats.data ? <div className="flex gap-2 text-2xs text-paper-mute"><Badge tone="violet">{stats.data.entities} entities</Badge><Badge tone="cyan">{stats.data.relationships} relationships</Badge></div> : undefined} />
      <div className="grid gap-4 xl:grid-cols-[270px_minmax(0,1fr)_370px]">
        <Panel className="max-h-[78vh] overflow-hidden">
          <PanelHeader title="Entity lookup" tone="violet" icon={<Search className="h-3.5 w-3.5" />} />
          <div className="space-y-2 border-b border-ink-500/70 p-2.5">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search entities (e.g. Acme)…" aria-label="Search entities" />
            <Select value={type} onChange={(e) => setType(e.target.value)} className="w-full" aria-label="Entity type"><option value="">All types</option>{TYPE_OPTIONS.map((t) => <option key={t}>{t}</option>)}</Select>
          </div>
          <ul className="max-h-[56vh] overflow-y-auto p-1.5">
            {(results.data ?? []).map((e) => (
              <li key={e.id}><button onClick={() => { setFocus(e.id); router.replace(`/knowledge?entity=${e.id}`); }} className={cn("flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-ink-700", focus === e.id && "bg-ink-600")}>
                <span className="flex min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: entityColor(e.type) }} /><span className="truncate text-paper-dim">{e.name}</span></span>
                <span className="num shrink-0 text-2xs text-paper-faint">{e.type.slice(0, 4)} · {e.degree}</span></button></li>
            ))}
            {results.data?.length === 0 && <p className="p-3 text-xs text-paper-mute">No entities found.</p>}
          </ul>
        </Panel>

        <Panel className="min-w-0">
          <PanelHeader title={ent ? `Neighbourhood of ${ent.name}` : "Graph overview"} tone="cyan" icon={<Network className="h-3.5 w-3.5" />} right={
            <div className="flex items-center gap-2 text-2xs text-paper-mute">
              {focus && <><label className="flex items-center gap-1">Hops<Select value={hops} onChange={(e) => setHops(Number(e.target.value))} className="h-6 px-1 text-xs">{[1, 2, 3].map((h) => <option key={h}>{h}</option>)}</Select></label>
                <label className="flex items-center gap-1">Min conf<input type="range" min={0} max={0.9} step={0.1} value={minConf} onChange={(e) => setMinConf(Number(e.target.value))} className="w-16 accent-violet" aria-label="Minimum confidence" /><span className="num w-6">{minConf.toFixed(1)}</span></label></>}
              <label className="flex items-center gap-1"><input type="checkbox" checked={hideWeak} onChange={(e) => setHideWeak(e.target.checked)} className="accent-violet" />hide co-occurrence</label>
              {focus && <Button size="sm" variant="ghost" onClick={() => { setFocus(null); router.replace("/knowledge"); }}>Overview</Button>}
            </div>} />
          <div className="h-[68vh] min-h-[420px]">
            {graph.loading && !graph.data ? <div className="grid h-full place-items-center"><Spinner /></div> : graph.error ? <div className="p-4"><ErrorNote message={graph.error} /></div> : view.nodes.length === 0 ? (
              <EmptyState icon={<Network className="h-8 w-8" />} title="The graph is empty" hint="Upload documents — entities and relationships are extracted automatically." />
            ) : (
              <ReactFlow key={`${focus}-${hops}-${hideWeak}-${minConf}`} nodes={view.nodes} edges={view.edges} nodeTypes={nodeTypes} onNodeClick={onNodeClick}
                onEdgeClick={(_, e) => setSelEdge(e.data as GraphEdge)} fitView fitViewOptions={{ padding: 0.2 }} minZoom={0.2} maxZoom={1.6} proOptions={{ hideAttribution: true }}>
                <Background color="#252932" gap={22} /><Controls showInteractive={false} /><MiniMap pannable zoomable nodeColor={(n) => entityColor((n.data as { e: EntityNode }).e.type)} maskColor="#0a0b0e99" />
              </ReactFlow>
            )}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-ink-500/70 px-3.5 py-2">{TYPE_OPTIONS.map((t) => <span key={t} className="flex items-center gap-1 text-2xs text-paper-mute"><span className="h-1.5 w-1.5 rounded-full" style={{ background: entityColor(t) }} />{titleCase(t)}</span>)}</div>
        </Panel>

        <Panel className="max-h-[78vh] overflow-y-auto">
          <PanelHeader title="Inspector" tone="violet" />
          {!focus ? <EmptyState title="Select an entity" hint="Click a node or search on the left. Click an edge to see the evidence sentence behind it." /> : detail.loading && !detail.data ? <div className="grid h-40 place-items-center"><Spinner /></div> : ent ? (
            <div className="space-y-4 p-3.5">
              <div><div className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: entityColor(ent.type) }} /><h3 className="text-base font-semibold">{ent.name}</h3></div>
                <div className="mt-1 flex flex-wrap gap-1.5"><Badge>{ent.type}</Badge><Badge tone="violet">{ent.mentions} mentions</Badge><Badge tone="cyan">{detail.data!.relationships.length} relationships</Badge></div>
                {ent.aliases && ent.aliases.length > 0 && <p className="mt-1.5 text-2xs text-paper-mute">Also seen as: {ent.aliases.join(", ")}</p>}
                {ent.attributes && Object.keys(ent.attributes).length > 0 && <div className="mt-2">{Object.entries(ent.attributes).map(([k, v]) => <KeyVal key={k} k={k} v={String(v)} />)}</div>}</div>

              {selEdge && (<div className="rounded border border-violet-line bg-violet-soft p-2.5"><div className="flex items-center justify-between"><Badge tone="violet">{selEdge.relation.replace(/_/g, " ")}</Badge><span className="num text-2xs text-paper-mute">conf {selEdge.confidence.toFixed(2)}</span></div>
                <p className="mt-1.5 text-xs italic text-paper-dim">“{selEdge.evidence}”</p><div className="mt-1.5"><CitationLink docId={selEdge.document_id} page={selEdge.page} name={selEdge.document} /></div></div>)}

              <div><p className="label-micro mb-1.5">Relationships</p>
                <ul className="space-y-1.5">{detail.data!.relationships.filter((r) => !hideWeak || r.relation !== "co_occurs_with").map((r) => (
                  <li key={r.id} className="rounded border border-ink-500/70 bg-ink-700/40 p-2">
                    <div className="flex flex-wrap items-center gap-1.5 text-xs"><span className="text-paper-faint">{r.direction === "out" ? "→" : "←"}</span><Badge tone="violet">{r.relation.replace(/_/g, " ")}</Badge>
                      <button className="text-paper-dim underline-offset-2 hover:underline" onClick={() => { setFocus(r.other.id); router.replace(`/knowledge?entity=${r.other.id}`); }}>{r.other.name}</button><span className="font-mono text-2xs text-paper-faint">{r.other.type}</span></div>
                    <p className="mt-1 line-clamp-3 text-2xs italic text-paper-mute">“{r.evidence}”</p>
                    <div className="mt-1 flex items-center gap-2"><CitationLink docId={r.document_id} page={r.page} name={r.document} /><span className="num text-2xs text-paper-faint">{r.confidence.toFixed(2)}</span></div></li>))}</ul></div>

              <div><p className="label-micro mb-1.5">Source documents</p>{detail.data!.documents.map((d) => (
                <div key={d.document_id} className="flex items-center justify-between py-0.5 text-xs"><CitationLink docId={d.document_id} page={d.pages[0]} name={d.document} label={d.document} /><span className="num text-2xs text-paper-mute">p.{d.pages.join(", ")} · {d.mentions}×</span></div>))}</div>

              <div><p className="label-micro mb-1.5">Trace connection to…</p><div className="flex gap-1.5"><Input value={pathTarget} onChange={(e) => setPathTarget(e.target.value)} placeholder="another entity name" aria-label="Path target" onKeyDown={(e) => e.key === "Enter" && trace()} /><Button onClick={trace} disabled={!pathTarget.trim()}><RouteIcon className="h-3.5 w-3.5" />Trace</Button></div>
                <ErrorNote message={pathErr} />
                {paths?.map((p, i) => (<div key={i} className="mt-2 rounded border border-ink-500 p-2"><p className="mb-1 text-2xs text-paper-mute">{p.hops} hops</p><div className="flex flex-wrap items-center gap-1">{p.nodes.map((n, j) => (<span key={n.id} className="flex items-center gap-1"><EntityChip name={n.name} type={n.type} />{j < p.steps.length && <span className="text-2xs text-violet">—{p.steps[j].relation.replace(/_/g, " ")}→</span>}</span>))}</div>
                  {p.steps.map((s, j) => <p key={j} className="mt-1 text-2xs italic text-paper-faint">“{s.evidence}” <span className="not-italic">({s.document} p.{s.page})</span></p>)}</div>))}</div>
            </div>
          ) : null}
        </Panel>
      </div>
    </>
  );
}

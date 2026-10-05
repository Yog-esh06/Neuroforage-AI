"use client";
import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Image as ImageIcon, RefreshCw, Sheet, Trash2, UploadCloud, ScanLine } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi, useDebounced } from "@/lib/hooks";
import { cn, fmtBytes, fmtDate, fmtMs, fmtPct } from "@/lib/utils";
import type { DocumentItem } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorNote, Input, Panel, PanelHeader, Select, Spinner } from "@/components/ui/primitives";
import { PageHeader, StatusBadge } from "@/components/ui/shared";

const TYPES = ["Contract", "Invoice", "Research Paper", "Financial Report", "Technical Documentation", "Policy", "Resume", "Legal Document", "General Report", "Unknown"];
const KIND_ICON: Record<string, React.ReactNode> = { pdf: <FileText className="h-4 w-4" />, image: <ImageIcon className="h-4 w-4" />, spreadsheet: <Sheet className="h-4 w-4" />, docx: <FileText className="h-4 w-4" />, text: <FileText className="h-4 w-4" /> };

interface UploadState { name: string; state: "uploading" | "queued" | "duplicate" | "error"; message?: string }

export default function DocumentsPage() {
  const router = useRouter();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [dtype, setDtype] = useState("");
  const dq = useDebounced(q);
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const list = useApi(() => api.documents({ q: dq, status, document_type: dtype, limit: 100 }), [dq, status, dtype],
    { pollMs: 2000, pollWhile: (d) => d.items.some((x) => ["QUEUED", "PROCESSING", "INDEXING"].includes(x.status)) });

  const upload = useCallback(async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      setUploads((u) => [{ name: f.name, state: "uploading" }, ...u]);
      try {
        const r = await api.upload(f);
        setUploads((u) => u.map((x) => (x.name === f.name && x.state === "uploading" ? { name: f.name, state: r.duplicate ? "duplicate" : "queued", message: r.duplicate ? `Already in library as #${r.document.id}` : "Queued for processing" } : x)));
      } catch (e) {
        setUploads((u) => u.map((x) => (x.name === f.name && x.state === "uploading" ? { name: f.name, state: "error", message: e instanceof ApiError ? e.message : String(e) } : x)));
      }
      await list.reload();
    }
  }, [list]);

  async function remove(d: DocumentItem) {
    if (!confirm(`Delete "${d.filename}" and everything derived from it (entities, insights, review tasks)? This cannot be undone.`)) return;
    try { await api.deleteDocument(d.id); await list.reload(); } catch (e) { setActionError(e instanceof ApiError ? e.message : String(e)); }
  }
  async function reprocess(d: DocumentItem) {
    try { await api.reprocess(d.id); await list.reload(); } catch (e) { setActionError(e instanceof ApiError ? e.message : String(e)); }
  }

  const items = list.data?.items ?? [];
  return (
    <>
      <PageHeader eyebrow="Corpus" title="Document library" subtitle="Upload PDFs, scans, images, spreadsheets, DOCX and text. Every file is classified, parsed, OCR'd when needed, indexed and analysed asynchronously." />

      {can("analyst") ? (
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) upload(e.dataTransfer.files); }}
          className={cn("mb-4 flex flex-col items-center justify-center gap-2 rounded-md border border-dashed px-6 py-8 text-center transition-colors", drag ? "border-violet bg-violet-soft" : "border-ink-400 bg-ink-800/60")}
        >
          <UploadCloud className="h-6 w-6 text-violet" />
          <p className="text-sm text-paper-dim">Drop files here or <button className="text-violet underline-offset-2 hover:underline" onClick={() => fileRef.current?.click()}>browse</button></p>
          <p className="text-2xs text-paper-faint">pdf · png · jpg · tiff · bmp · webp · docx · xlsx · csv · txt · md — up to 50 MB each (server-enforced)</p>
          <input ref={fileRef} type="file" multiple hidden accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.txt,.md,.csv,.xlsx,.docx" onChange={(e) => { if (e.target.files?.length) upload(e.target.files); e.target.value = ""; }} />
        </div>
      ) : <div className="mb-4 rounded border border-ink-500 bg-ink-800/60 px-4 py-3 text-xs text-paper-mute">Your role (viewer) is read-only. Uploading requires analyst or higher.</div>}

      {uploads.length > 0 && (
        <div className="mb-4 space-y-1">
          {uploads.slice(0, 5).map((u, i) => (
            <div key={i} className="flex items-center justify-between rounded border border-ink-500/80 bg-ink-800/60 px-3 py-1.5 text-xs">
              <span className="truncate text-paper-dim">{u.name}</span>
              <span className="flex items-center gap-2">{u.state === "uploading" && <Spinner className="h-3 w-3" />}
                <Badge tone={u.state === "error" ? "danger" : u.state === "duplicate" ? "amber" : u.state === "queued" ? "emerald" : "neutral"}>{u.state}</Badge>
                {u.message && <span className="max-w-[320px] truncate text-paper-mute">{u.message}</span>}</span>
            </div>
          ))}
        </div>
      )}
      <ErrorNote message={actionError} />

      <Panel>
        <PanelHeader title={`Documents${list.data ? ` · ${list.data.total}` : ""}`} tone="violet" right={
          <div className="flex items-center gap-2">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search filename or title…" className="h-7 w-52" aria-label="Search documents" />
            <Select value={dtype} onChange={(e) => setDtype(e.target.value)} className="h-7" aria-label="Filter by document type"><option value="">All types</option>{TYPES.map((t) => <option key={t}>{t}</option>)}</Select>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-7" aria-label="Filter by status"><option value="">All statuses</option>{["QUEUED", "PROCESSING", "INDEXING", "READY", "FAILED"].map((t) => <option key={t}>{t}</option>)}</Select>
          </div>} />
        {list.loading && !list.data ? <div className="grid h-40 place-items-center"><Spinner /></div> : list.error && !list.data ? <div className="p-4"><ErrorNote message={list.error} /></div> : items.length === 0 ? (
          <EmptyState icon={<FileText className="h-8 w-8" />} title="No documents match" hint="Upload a document above, or clear the filters." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead><tr className="border-b border-ink-500/80 text-paper-mute">{["Document", "Type", "Status", "Pages", "Size", "Processing", "Uploaded", ""].map((h) => <th key={h} className="label-micro px-3.5 py-2 font-normal">{h}</th>)}</tr></thead>
              <tbody>
                {items.map((d) => (
                  <tr key={d.id} onClick={() => d.status === "READY" && router.push(`/documents/${d.id}`)}
                    className={cn("border-b border-ink-500/50 transition-colors last:border-0", d.status === "READY" ? "cursor-pointer hover:bg-ink-700/60" : "opacity-90")}>
                    <td className="px-3.5 py-2.5"><div className="flex items-center gap-2.5"><span className="text-paper-faint">{KIND_ICON[d.file_kind] || <FileText className="h-4 w-4" />}</span>
                      <div className="min-w-0"><p className="max-w-[300px] truncate text-sm text-paper">{d.filename}</p>
                        <p className="flex items-center gap-1.5 text-2xs text-paper-faint">v{d.version}{d.ocr_used && <Badge tone="cyan"><ScanLine className="h-3 w-3" />OCR {d.ocr_confidence ? fmtPct(d.ocr_confidence) : ""}</Badge>}{d.flags.length > 0 && <Badge tone="danger">flagged</Badge>}</p></div></div></td>
                    <td className="px-3.5 py-2.5">{d.status === "READY" ? <div><p className="text-paper-dim">{d.document_type}</p><p className="num text-2xs text-paper-faint">{d.classification_confidence.toFixed(2)} · {d.classification_method.split("+")[0]}</p></div> : <span className="text-paper-faint">—</span>}</td>
                    <td className="px-3.5 py-2.5"><StatusBadge status={d.status} progress={d.job?.progress} />{d.status === "FAILED" && <p className="mt-1 max-w-[220px] truncate text-2xs text-danger" title={d.error || ""}>{d.error}</p>}
                      {["PROCESSING", "INDEXING"].includes(d.status) && <p className="mt-1 text-2xs text-paper-faint">{d.job?.stage}</p>}</td>
                    <td className="num px-3.5 py-2.5 text-paper-dim">{d.page_count || "—"}</td>
                    <td className="num px-3.5 py-2.5 text-paper-mute">{fmtBytes(d.size_bytes)}</td>
                    <td className="num px-3.5 py-2.5 text-paper-mute">{fmtMs(d.processing_ms)}</td>
                    <td className="px-3.5 py-2.5 text-paper-mute">{fmtDate(d.created_at)}</td>
                    <td className="px-3.5 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <div className="flex justify-end gap-1">
                        {can("analyst") && ["READY", "FAILED"].includes(d.status) && <Button size="icon" variant="ghost" title="Reprocess" aria-label="Reprocess" onClick={() => reprocess(d)}><RefreshCw className="h-3.5 w-3.5" /></Button>}
                        {can("reviewer") && <Button size="icon" variant="ghost" title="Delete" aria-label="Delete" onClick={() => remove(d)}><Trash2 className="h-3.5 w-3.5 text-danger" /></Button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

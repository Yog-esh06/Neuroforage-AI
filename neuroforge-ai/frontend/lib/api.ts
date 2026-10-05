/** Typed API client. The browser only ever holds a short-lived user JWT — never provider/API keys. */
import type {
  AskResponse, AuditItem, Comparison, ContradictionItem, Dashboard, DocumentDetail, DocumentItem, EntityDetail, EntityNode, GraphView, Insight,
  PageDetail, PageSummary, ReviewTask, SearchResponse, TableProfile, User, Workflow, WorkflowMeta, WorkflowRun,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const BASE = `${API_URL}/api/v1`;
const TOKEN_KEY = "neuroforge.token";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
}

export const tokenStore = {
  get: (): string | null => { try { return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { window.localStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ } },
  clear: () => { try { window.localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ } },
};

type Params = Record<string, string | number | boolean | string[] | undefined | null>;

function qs(params?: Params): string {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x));
    else u.append(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function parse(res: Response) {
  if (res.status === 204) return null;
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = null; }
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      tokenStore.clear();
      window.location.href = "/login";
    }
    const e = body?.error;
    if (e) throw new ApiError(res.status, e.code, e.message, e.details);
    const detail = Array.isArray(body?.detail) ? body.detail.map((d: any) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ") : undefined;
    throw new ApiError(res.status, "http_error", detail || res.statusText || "Request failed");
  }
  return body;
}

async function request<T>(method: string, path: string, opts: { params?: Params; json?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const tok = tokenStore.get();
  if (tok) headers.Authorization = `Bearer ${tok}`;
  let body: BodyInit | undefined;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
  if (opts.form) body = opts.form;
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${qs(opts.params)}`, { method, headers, body, cache: "no-store" });
  } catch {
    throw new ApiError(0, "network", `Cannot reach the API at ${API_URL}. Is the backend running?`);
  }
  return (await parse(res)) as T;
}

const get = <T>(p: string, params?: Params) => request<T>("GET", p, { params });
const post = <T>(p: string, json?: unknown, params?: Params) => request<T>("POST", p, { json, params });
const patch = <T>(p: string, json?: unknown) => request<T>("PATCH", p, { json });
const del = <T>(p: string) => request<T>("DELETE", p);

export interface SearchFilters {
  document_ids?: number[]; document_types?: string[]; page_min?: number; page_max?: number; entities?: string[]; section_contains?: string;
  chunk_types?: ("text" | "table")[]; uploaded_from?: string; uploaded_to?: string;
}

export const api = {
  login: (email: string, password: string) => post<{ access_token: string; user: User }>("/auth/login", { email, password }),
  me: () => get<User>("/auth/me"),
  health: () => get<{ status: string; checks: Record<string, string>; job_backend: string; embedding_model: string }>("/health"),
  dashboard: () => get<Dashboard>("/stats/dashboard"),

  documents: (params?: Params) => get<{ total: number; items: DocumentItem[] }>("/documents", params),
  document: (id: number) => get<DocumentDetail>(`/documents/${id}`),
  upload: (file: File) => { const f = new FormData(); f.append("file", file); return request<{ duplicate: boolean; document: DocumentItem }>("POST", "/documents", { form: f }); },
  deleteDocument: (id: number) => del<null>(`/documents/${id}`),
  reprocess: (id: number) => post<unknown>(`/documents/${id}/reprocess`),
  pages: (id: number) => get<PageSummary[]>(`/documents/${id}/pages`),
  page: (id: number, n: number) => get<PageDetail>(`/documents/${id}/pages/${n}`),
  docEntities: (id: number) => get<{ id: number; name: string; type: string; mentions: number; first_page: number }[]>(`/documents/${id}/entities`),
  docTables: (id: number) => get<{ id: number; page_number: number; section: string | null; headers: string[]; rows: string[][]; profile: TableProfile }[]>(`/documents/${id}/tables`),
  docInsights: (id: number) => get<{ insights: Insight[]; contradictions: ContradictionItem[] }>(`/documents/${id}/insights`),
  /** Page images need the Authorization header, so they are fetched as blobs and turned into object URLs. */
  pageImage: async (id: number, n: number): Promise<string> => {
    const tok = tokenStore.get();
    const res = await fetch(`${BASE}/documents/${id}/pages/${n}/image`, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
    if (!res.ok) throw new ApiError(res.status, "no_image", "No visual rendering available for this page");
    return URL.createObjectURL(await res.blob());
  },
  downloadFile: async (id: number, name: string) => {
    const tok = tokenStore.get();
    const res = await fetch(`${BASE}/documents/${id}/file`, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
    if (!res.ok) throw new ApiError(res.status, "download", "Download failed");
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a"); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
  },

  search: (body: { query: string; k?: number; filters?: SearchFilters; strategies?: string[] }) => post<SearchResponse>("/search", body),
  ask: (body: { question: string; k?: number; filters?: SearchFilters }) => post<AskResponse>("/search/ask", body),

  entities: (params?: Params) => get<EntityNode[]>("/knowledge/entities", params),
  entity: (id: number) => get<EntityDetail>(`/knowledge/entities/${id}`),
  entityGraph: (id: number, params?: Params) => get<GraphView>(`/knowledge/entities/${id}/graph`, params),
  graphOverview: (max_nodes = 80) => get<GraphView>("/knowledge/overview", { max_nodes }),
  graphPaths: (source: number, target: number) => get<{ nodes: EntityNode[]; hops: number; steps: { relation: string; evidence: string; document: string; page: number }[] }[]>("/knowledge/paths", { source, target }),
  knowledgeStats: () => get<{ entities: number; relationships: number; by_type: Record<string, number>; by_relation: Record<string, number> }>("/knowledge/stats"),

  insights: (params?: Params) => get<{ total: number; items: Insight[] }>("/insights", params),
  setInsightStatus: (id: number, status: string, note?: string) => patch<Insight>(`/insights/${id}/status`, { status, note }),
  contradictions: (params?: Params) => get<{ total: number; items: ContradictionItem[] }>("/insights/contradictions", params),
  setContradictionStatus: (id: number, status: string, note?: string) => patch<ContradictionItem>(`/insights/contradictions/${id}`, { status, note }),
  reanalyze: (docId: number) => post<{ insights: number; contradictions: number }>(`/insights/analyze/${docId}`),

  reviewTasks: (params?: Params) => get<{ total: number; items: ReviewTask[] }>("/review/tasks", params),
  reviewTask: (id: number) => get<ReviewTask>(`/review/tasks/${id}`),
  reviewAction: (id: number, action: string, note?: string, modified_recommendation?: string) =>
    post<ReviewTask>(`/review/tasks/${id}/action`, { action, note, modified_recommendation }),

  workflows: () => get<Workflow[]>("/workflows"),
  workflowMeta: () => get<WorkflowMeta>("/workflows/meta"),
  workflowRuns: (workflow_id?: number) => get<WorkflowRun[]>("/workflows/runs", { workflow_id, limit: 60 }),
  createWorkflow: (w: Partial<Workflow>) => post<Workflow>("/workflows", w),
  updateWorkflow: (id: number, w: Partial<Workflow>) => patch<Workflow>(`/workflows/${id}`, w),
  deleteWorkflow: (id: number) => del<null>(`/workflows/${id}`),
  runWorkflow: (id: number) => post<{ evaluated: number; matched: number }>(`/workflows/${id}/run`),

  compare: (document_ids: number[]) => post<{ base_id: number; comparisons: Comparison[] }>("/compare", { document_ids }),

  audit: (params?: Params) => get<{ total: number; items: AuditItem[] }>("/audit", params),
  auditItem: (id: number) => get<AuditItem>(`/audit/${id}`),
  auditActions: () => get<string[]>("/audit/actions"),
  auditVerify: () => get<{ valid: boolean; checked: number; first_broken_id: number | null }>("/audit/verify"),
};

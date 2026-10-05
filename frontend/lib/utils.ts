import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { BBox, Severity } from "./types";

export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }

export function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}
export function fmtMs(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}
export function fmtDate(s: string | null | undefined) {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z");
  return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
export function fmtPct(v: number | null | undefined, digits = 0) {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}
export function timeAgo(s: string) {
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z").getTime();
  const sec = Math.max(1, Math.round((Date.now() - d) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

/** Semantic colour mapping — violet=AI, cyan=retrieval/data, emerald=verified, amber=review, red=risk, magenta=contradiction. */
export const SEVERITY_STYLE: Record<Severity, { text: string; bg: string; line: string; dot: string }> = {
  critical: { text: "text-danger", bg: "bg-danger-soft", line: "border-danger-line", dot: "bg-danger" },
  high: { text: "text-danger", bg: "bg-danger-soft", line: "border-danger-line", dot: "bg-danger" },
  medium: { text: "text-amber", bg: "bg-amber-soft", line: "border-amber-line", dot: "bg-amber" },
  low: { text: "text-cyan", bg: "bg-cyan-soft", line: "border-cyan-line", dot: "bg-cyan" },
  info: { text: "text-violet", bg: "bg-violet-soft", line: "border-violet-line", dot: "bg-violet" },
};

export const ENTITY_COLOR: Record<string, string> = {
  ORG: "#8b7cf6", PERSON: "#2dd4e6", LOCATION: "#34d399", DATE: "#f5b942", MONEY: "#f2606b", CONTRACT: "#e268d8",
  REGULATION: "#f5b942", TECHNOLOGY: "#2dd4e6", PRODUCT: "#8b7cf6", EVENT: "#b9b6ae", METRIC: "#8a8d96",
};
export const entityColor = (t: string) => ENTITY_COLOR[t] || "#8a8d96";

export function confidenceTone(level: string) {
  return level === "HIGH" ? "text-emerald" : level === "MEDIUM" ? "text-amber" : "text-danger";
}

/** Build the document-viewer URL that opens a citation at its exact location. */
export function citationHref(docId: number, page: number, bbox?: BBox | null) {
  const h = bbox && bbox.length === 4 ? `&h=${bbox.map((v) => Math.round(v * 10) / 10).join(",")}` : "";
  return `/documents/${docId}?page=${page}${h}`;
}

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, FileSearch, GitCompareArrows, Network, ScanText, ScrollText, ShieldCheck, Swords, UserCheck, Workflow } from "lucide-react";
import { Mark } from "@/components/shell/app-shell";
import { useAuth } from "@/lib/auth";

const PIPELINE = [
  ["Ingest", "type sniffing · validation", "cyan"], ["Classify", "content-based, 10 classes", "violet"], ["OCR", "only when no text layer", "cyan"],
  ["Layout", "headings · tables · figures", "cyan"], ["Entities", "rules + spaCy NER", "violet"], ["Graph", "evidence on every edge", "violet"],
  ["Retrieve", "semantic · BM25 · graph", "cyan"], ["Rerank", "7 weighted signals", "cyan"], ["Reason", "evidence-only generation", "violet"],
  ["Verify", "claims checked vs sources", "emerald"], ["Review", "human decides", "amber"], ["Audit", "hash-chained trail", "emerald"],
] as const;
const TONE: Record<string, string> = { cyan: "#2dd4e6", violet: "#8b7cf6", emerald: "#34d399", amber: "#f5b942", magenta: "#e268d8", danger: "#f2606b" };

const CAPS = [
  { icon: ScanText, tone: "cyan", title: "Multimodal understanding", body: "Native text, scanned pages (OCR decided per page), ruled tables recovered from images, figures with captions, spreadsheets and DOCX — all into one layout model with page numbers and bounding boxes." },
  { icon: Network, tone: "violet", title: "Knowledge graph with provenance", body: "People, organisations, contracts, amounts, dates and regulations linked by typed relationships. Click any edge to read the exact sentence and page it came from." },
  { icon: FileSearch, tone: "cyan", title: "Hybrid retrieval & reranking", body: "Dense embeddings, BM25, metadata filters and graph expansion are fused, then reranked on semantic, lexical, entity, graph, recency and source-quality signals." },
  { icon: ShieldCheck, tone: "emerald", title: "Claims are verified, not trusted", body: "Generated statements must cite real evidence. Fabricated citations are stripped, unsupported numbers are rejected, and the platform refuses when evidence is thin." },
  { icon: Swords, tone: "magenta", title: "Contradiction detection", body: "When two documents disagree — expiry dates, amounts, notice periods, governing law — both sides are shown with a conflict confidence. Nothing is silently resolved." },
  { icon: GitCompareArrows, tone: "amber", title: "Semantic comparison", body: "Clauses are aligned by meaning, then diffed by value, date, duration, entity and obligation — not by raw line position." },
  { icon: Workflow, tone: "amber", title: "Decision automation", body: "IF risk severity > threshold AND confidence > threshold THEN create a review task. Every rule evaluation is logged with its reasoning." },
  { icon: UserCheck, tone: "emerald", title: "Human in the loop", body: "Approve, reject, modify, escalate or request more evidence. Decisions are final, attributed and feed back into insight status." },
  { icon: ScrollText, tone: "violet", title: "Reconstructable audit trail", body: "User, model, prompt version, retrieved evidence, generated result, confidence and human decision — chained by hash so tampering is detectable." },
];

export default function Landing() {
  const { user } = useAuth();
  const [active, setActive] = useState(0);
  useEffect(() => { const t = setInterval(() => setActive((a) => (a + 1) % PIPELINE.length), 1100); return () => clearInterval(t); }, []);
  const cta = user ? { href: "/dashboard", label: "Open console" } : { href: "/login", label: "Sign in" };

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2.5"><Mark /><span className="text-sm font-semibold tracking-tight">NeuroForge <span className="text-paper-mute">AI</span></span></div>
        <nav className="flex items-center gap-5 text-sm text-paper-mute"><a href="#pipeline" className="hover:text-paper">Pipeline</a><a href="#trace" className="hover:text-paper">Traceability</a><a href="#capabilities" className="hover:text-paper">Capabilities</a>
          <Link href={cta.href} className="rounded border border-ink-400 px-3 py-1.5 text-paper hover:bg-ink-600">{cta.label}</Link></nav>
      </header>

      <section className="mx-auto max-w-6xl px-6 pb-16 pt-14 md:pt-20">
        <motion.p initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="label-micro mb-4 !text-violet">Multimodal document intelligence · decision automation</motion.p>
        <motion.h1 initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }} className="max-w-4xl text-4xl font-semibold leading-[1.08] tracking-tight md:text-6xl">
          Every AI conclusion, <span className="text-violet">traceable</span> to the page it came from.
        </motion.h1>
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }} className="mt-6 max-w-2xl text-base leading-relaxed text-paper-dim">
          NeuroForge turns contracts, invoices, scans, reports and spreadsheets into structured, verifiable knowledge — then retrieves evidence, reasons over it, flags risks and contradictions, and routes decisions to a human with a complete audit trail.
          It is not a PDF chatbot: it refuses to answer when the evidence does not support one.
        </motion.p>
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.25 }} className="mt-8 flex flex-wrap items-center gap-3">
          <Link href={cta.href} className="inline-flex items-center gap-2 rounded bg-violet px-4 py-2.5 text-sm font-medium text-ink hover:bg-violet/85">{cta.label}<ArrowRight className="h-4 w-4" /></Link>
          <a href="#trace" className="rounded border border-ink-400 px-4 py-2.5 text-sm text-paper-dim hover:bg-ink-600">See how traceability works</a>
        </motion.div>
      </section>

      <section id="pipeline" className="border-y border-ink-500/70 bg-ink-900/70 py-12">
        <div className="mx-auto max-w-6xl px-6">
          <p className="label-micro mb-5">The pipeline · every stage is a real module</p>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-ink-500 bg-ink-500 sm:grid-cols-3 lg:grid-cols-6">
            {PIPELINE.map(([name, hint, tone], i) => (
              <motion.div key={name} animate={{ backgroundColor: i === active ? "#161920" : "#0d0e12" }} transition={{ duration: 0.3 }} className="relative p-3.5">
                <span className="absolute left-0 top-0 h-[2px] transition-all duration-500" style={{ width: i === active ? "100%" : "0%", background: TONE[tone] }} />
                <p className="num text-2xs text-paper-faint">{String(i + 1).padStart(2, "0")}</p>
                <p className="mt-1 text-sm font-medium" style={{ color: i === active ? TONE[tone] : "#ece9e2" }}>{name}</p>
                <p className="mt-0.5 text-2xs leading-snug text-paper-mute">{hint}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section id="trace" className="mx-auto max-w-6xl px-6 py-16">
        <p className="label-micro mb-2">Traceability · illustrative example</p>
        <h2 className="max-w-2xl text-2xl font-semibold tracking-tight">From a question to the exact passage — and back.</h2>
        <div className="mt-8 grid gap-4 lg:grid-cols-[1fr_1fr]">
          <div className="space-y-3">
            <Step n="1" tone="violet" title="Question">“What are the major financial risks across these documents?”</Step>
            <Step n="2" tone="cyan" title="Evidence retrieved">Semantic + BM25 + graph candidates reranked on seven signals. Each passage keeps document, page, section and bounding box.</Step>
            <Step n="3" tone="emerald" title="Claims verified">Each statement is checked against the passages it cites. Values that are not in the source are rejected before you see them.</Step>
            <Step n="4" tone="amber" title="Human verification">High-severity findings enter the review queue with the AI recommendation, evidence and confidence attached.</Step>
          </div>
          <div className="rounded-md border border-ink-500 bg-ink-800/80">
            <div className="flex items-center justify-between border-b border-ink-500 px-4 py-2.5"><span className="label-micro">Example answer shape</span><span className="rounded-sm border border-ink-400 px-1.5 font-mono text-2xs text-paper-mute">sample · not live data</span></div>
            <div className="space-y-3 p-4 text-sm">
              <div className="flex items-center justify-between"><span className="font-semibold">Risk #1</span><span className="rounded-sm border border-danger-line bg-danger-soft px-1.5 py-0.5 font-mono text-2xs uppercase text-danger">high severity</span></div>
              <div><p className="label-micro mb-1">Evidence</p><div className="flex flex-wrap gap-1.5"><Chip>Document A · p.12</Chip><Chip>Document B · p.8</Chip></div></div>
              <div><p className="label-micro mb-1">Supporting entities</p><div className="flex flex-wrap gap-1.5"><Ent>Company X</Ent><Ent>Contract Y</Ent><Ent>Payment obligation Z</Ent></div></div>
              <div className="rounded border border-magenta-line bg-magenta-soft p-2.5"><p className="label-micro !text-magenta">Contradictory evidence</p><p className="mt-1 text-xs text-paper-dim">Document A states expiry in June 2027; Document B states September 2027. Both shown — none chosen.</p></div>
              <div className="flex items-center justify-between border-t border-ink-500 pt-3 text-xs"><span className="text-paper-mute">Confidence <span className="text-paper-faint">(engineering index, not a probability)</span></span><span className="num text-emerald">0.89</span></div>
            </div>
          </div>
        </div>
      </section>

      <section id="capabilities" className="mx-auto max-w-6xl px-6 pb-20">
        <p className="label-micro mb-5">Capabilities</p>
        <div className="grid gap-px overflow-hidden rounded-md border border-ink-500 bg-ink-500 md:grid-cols-2 lg:grid-cols-3">
          {CAPS.map((c, i) => (
            <motion.div key={c.title} initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }} transition={{ delay: (i % 3) * 0.05 }} className="bg-ink-800 p-5">
              <c.icon className="h-5 w-5" style={{ color: TONE[c.tone] }} />
              <h3 className="mt-3 text-sm font-semibold">{c.title}</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-paper-mute">{c.body}</p>
            </motion.div>
          ))}
        </div>
        <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 text-2xs text-paper-faint">
          <span className="flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full bg-violet" />violet — AI reasoning</span><span className="flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full bg-cyan" />cyan — retrieval &amp; data</span>
          <span className="flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full bg-emerald" />emerald — verified</span><span className="flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full bg-amber" />amber — review required</span>
          <span className="flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full bg-danger" />red — high risk</span><span className="flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full bg-magenta" />magenta — contradiction</span>
        </div>
      </section>

      <footer className="border-t border-ink-500/70 py-6 text-center text-2xs text-paper-faint">NeuroForge AI · evidence-grounded document intelligence</footer>
    </div>
  );
}

function Step({ n, tone, title, children }: { n: string; tone: string; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3.5 rounded-md border border-ink-500 bg-ink-800/80 p-4">
      <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-sm text-xs" style={{ background: `${TONE[tone]}22`, color: TONE[tone] }}>{n}</span>
      <div><p className="text-sm font-medium">{title}</p><p className="mt-1 text-xs leading-relaxed text-paper-mute">{children}</p></div>
    </div>
  );
}
const Chip = ({ children }: { children: React.ReactNode }) => <span className="rounded-sm border border-cyan-line bg-cyan-soft px-1.5 py-0.5 font-mono text-2xs text-cyan">{children}</span>;
const Ent = ({ children }: { children: React.ReactNode }) => <span className="rounded-sm border border-ink-400 bg-ink-700 px-1.5 py-0.5 text-xs text-paper-dim">{children}</span>;

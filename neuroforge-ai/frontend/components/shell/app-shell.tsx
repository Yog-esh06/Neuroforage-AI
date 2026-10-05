"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { ClipboardCheck, FileStack, GitCompareArrows, LayoutDashboard, Lightbulb, LogOut, Network, ScrollText, Search, Workflow as WorkflowIcon } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/primitives";

const NAV = [
  { group: "Overview", items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard }] },
  { group: "Corpus", items: [
    { href: "/documents", label: "Documents", icon: FileStack },
    { href: "/search", label: "Search & Ask", icon: Search },
    { href: "/knowledge", label: "Knowledge", icon: Network },
  ] },
  { group: "Analysis", items: [
    { href: "/insights", label: "Insights", icon: Lightbulb },
    { href: "/compare", label: "Compare", icon: GitCompareArrows },
  ] },
  { group: "Governance", items: [
    { href: "/review", label: "Review queue", icon: ClipboardCheck },
    { href: "/workflows", label: "Workflows", icon: WorkflowIcon },
    { href: "/audit", label: "Audit trail", icon: ScrollText },
  ] },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const health = useApi(() => api.health(), [], { pollMs: 20000 });

  useEffect(() => { if (!loading && !user) router.replace("/login"); }, [loading, user, router]);

  if (loading || !user) {
    return <div className="grid min-h-screen place-items-center"><Spinner className="h-5 w-5" /></div>;
  }
  const ok = health.data?.status === "ok";
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[220px] shrink-0 flex-col border-r border-ink-500/80 bg-ink-900/80 backdrop-blur md:flex">
        <Link href="/" className="flex items-center gap-2.5 border-b border-ink-500/80 px-4 py-3.5">
          <Mark />
          <div className="leading-tight"><p className="text-sm font-semibold tracking-tight">NeuroForge</p><p className="label-micro !text-[9px]">Evidence console</p></div>
        </Link>
        <nav className="flex-1 space-y-4 overflow-y-auto px-2.5 py-4">
          {NAV.map((g) => (
            <div key={g.group}>
              <p className="label-micro mb-1.5 px-2 !text-[9px]">{g.group}</p>
              {g.items.map((it) => {
                const active = path === it.href || path.startsWith(it.href + "/");
                return (
                  <Link key={it.href} href={it.href} className={cn("group relative flex items-center gap-2.5 rounded px-2 py-1.5 text-sm transition-colors", active ? "bg-ink-600 text-paper" : "text-paper-mute hover:bg-ink-700 hover:text-paper")}>
                    {active && <span className="absolute -left-2.5 top-1.5 h-4 w-[2px] rounded-full bg-violet" />}
                    <it.icon className={cn("h-4 w-4", active ? "text-violet" : "text-paper-faint group-hover:text-paper-mute")} />{it.label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="space-y-2 border-t border-ink-500/80 px-3.5 py-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-paper-mute"><span className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-emerald" : health.error ? "bg-danger" : "bg-amber")} />{ok ? "API online" : health.error ? "API offline" : "Degraded"}</span>
            <span className="font-mono text-2xs text-paper-faint">{health.data?.job_backend}</span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0"><p className="truncate text-paper-dim">{user.name}</p><p className="label-micro !text-[9px]">{user.role}</p></div>
            <button onClick={logout} className="rounded p-1.5 text-paper-mute hover:bg-ink-600 hover:text-paper" title="Sign out" aria-label="Sign out"><LogOut className="h-4 w-4" /></button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <MobileNav path={path} />
        <div className="mx-auto max-w-[1500px] px-5 py-6 md:px-8">{children}</div>
      </main>
    </div>
  );
}

function MobileNav({ path }: { path: string }) {
  const flat = NAV.flatMap((g) => g.items);
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-ink-500/80 bg-ink-900 px-3 py-2 md:hidden">
      {flat.map((it) => (
        <Link key={it.href} href={it.href} className={cn("flex shrink-0 items-center gap-1.5 rounded px-2.5 py-1.5 text-xs", path.startsWith(it.href) ? "bg-ink-600 text-paper" : "text-paper-mute")}><it.icon className="h-3.5 w-3.5" />{it.label}</Link>
      ))}
    </div>
  );
}

export function Mark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect x="1" y="1" width="30" height="30" rx="7" fill="#111318" stroke="#343944" />
      <path d="M9 22V10l14 12V10" stroke="#8b7cf6" strokeWidth="2.2" strokeLinecap="square" />
      <circle cx="9" cy="10" r="2" fill="#2dd4e6" /><circle cx="23" cy="22" r="2" fill="#34d399" />
    </svg>
  );
}

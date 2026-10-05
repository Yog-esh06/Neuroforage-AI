"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { Button, ErrorNote, Input } from "@/components/ui/primitives";
import { Mark } from "@/components/shell/app-shell";

export default function LoginPage() {
  const { user, login, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (!loading && user) router.replace("/dashboard"); }, [loading, user, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await login(email.trim(), password); router.replace("/dashboard"); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Sign-in failed"); }
    finally { setBusy(false); }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-[360px] space-y-4 rounded-md border border-ink-500 bg-ink-800/90 p-6">
        <div className="flex items-center gap-3"><Mark size={32} /><div><h1 className="text-base font-semibold">Sign in to NeuroForge</h1><p className="text-xs text-paper-mute">Evidence-grounded document intelligence</p></div></div>
        <div className="space-y-1.5"><label className="label-micro" htmlFor="email">Email</label><Input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" /></div>
        <div className="space-y-1.5"><label className="label-micro" htmlFor="pw">Password</label><Input id="pw" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        <ErrorNote message={error} />
        <Button type="submit" variant="primary" className="w-full" loading={busy}>Sign in</Button>
        <p className="text-center text-2xs text-paper-faint">Access is role-based: viewer · analyst · reviewer · admin</p>
      </form>
    </div>
  );
}

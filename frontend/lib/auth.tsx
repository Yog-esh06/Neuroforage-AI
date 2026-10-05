"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, tokenStore } from "./api";
import type { Role, User } from "./types";

interface AuthState { user: User | null; loading: boolean; login: (email: string, password: string) => Promise<void>; logout: () => void; can: (min: Role) => boolean }
const Ctx = createContext<AuthState | null>(null);
const RANK: Record<Role, number> = { viewer: 0, analyst: 1, reviewer: 2, admin: 3 };

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    // With AUTH_ENABLED=false the backend serves an anonymous admin, so /auth/me works without a token.
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api.login(email, password);
    tokenStore.set(r.access_token);
    setUser(r.user);
  }, []);
  const logout = useCallback(() => { tokenStore.clear(); setUser(null); router.push("/login"); }, [router]);
  const can = useCallback((min: Role) => !!user && RANK[user.role] >= RANK[min], [user]);
  const value = useMemo(() => ({ user, loading, login, logout, can }), [user, loading, login, logout, can]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used inside AuthProvider");
  return c;
}

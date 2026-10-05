"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export interface Resource<T> { data: T | null; error: string | null; loading: boolean; reload: () => Promise<void>; setData: (d: T | null) => void }

/** Minimal data hook: fetches on mount / when deps change, optional polling while `pollWhile(data)` is true. */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[], opts: { pollMs?: number; pollWhile?: (d: T) => boolean; enabled?: boolean } = {}): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const alive = useRef(true);
  const enabled = opts.enabled !== false;

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const d = await fnRef.current();
      if (!alive.current) return d;
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      if (alive.current) setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      if (alive.current && !silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    if (!enabled) { setLoading(false); return; }
    load();
    return () => { alive.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);

  useEffect(() => {
    if (!opts.pollMs || !enabled) return;
    const t = setInterval(async () => {
      if (data !== null && opts.pollWhile && !opts.pollWhile(data)) return;
      await load(true);
    }, opts.pollMs);
    return () => clearInterval(t);
  }, [opts.pollMs, opts.pollWhile, data, enabled, load]);

  return { data, error, loading, reload: async () => { await load(true); }, setData };
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

export function useAction<A extends unknown[], R>(fn: (...a: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (...a: A): Promise<R | undefined> => {
    setBusy(true); setError(null);
    try { return await fn(...a); }
    catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  }, [fn]);
  return { run, busy, error, clearError: () => setError(null) };
}

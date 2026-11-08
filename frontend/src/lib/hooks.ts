"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { api, authStorage, peekApiCache, User } from "@/lib/api";

// ---------------------------------------------------------------------------
// Current user (from localStorage), without hydration mismatches.
// ---------------------------------------------------------------------------
let cachedRaw: string | null = null;
let cachedUser: User | null = null;

function readUser(): User | null {
  const raw = typeof window === "undefined" ? null : localStorage.getItem("rag_user_data");
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedUser = raw ? (JSON.parse(raw) as User) : null;
    } catch {
      cachedUser = null;
    }
  }
  return cachedUser;
}

function subscribeUser(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener("agis:user", onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener("agis:user", onChange);
  };
}

export function notifyUserChanged() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("agis:user"));
}

export function useCurrentUser(): User | null {
  return useSyncExternalStore(subscribeUser, readUser, () => null);
}

/**
 * Redirects to /login without a token, and non-admins away from admin pages.
 * Returns true once the visitor is allowed to see the page.
 */
export function useRequireAuth(opts: { adminOnly?: boolean } = {}): boolean {
  const router = useRouter();
  const user = useCurrentUser();
  const hasToken = useSyncExternalStore(
    subscribeUser,
    () => Boolean(authStorage.getToken()),
    () => true // assume allowed on the server; the client corrects it immediately
  );
  const allowed = hasToken && (!opts.adminOnly || user?.role === "admin");

  useEffect(() => {
    if (!hasToken) router.replace("/login");
    else if (opts.adminOnly && user && user.role !== "admin") router.replace("/knowledge-bases");
  }, [hasToken, user, opts.adminOnly, router]);

  return allowed;
}

// ---------------------------------------------------------------------------
// Data fetching with stale-while-revalidate.
// ---------------------------------------------------------------------------
export interface ApiState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean; // true only while there is nothing to show yet
  refreshing: boolean;
  reload: () => Promise<void>;
  setData: (updater: (prev: T | undefined) => T | undefined) => void;
}

/**
 * `key` is the API path the fetcher reads (used to show cached data at once).
 * Pass `null` to skip fetching (e.g. until a selection exists).
 */
export function useApi<T>(key: string | null, fetcher: () => Promise<T>): ApiState<T> {
  const [state, setState] = useState<{ key: string | null; data: T | undefined; error: string | null; refreshing: boolean }>(
    () => ({ key, data: key ? peekApiCache<T>(key) : undefined, error: null, refreshing: false })
  );
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  // Key changed: show whatever is cached for the new key straight away.
  if (state.key !== key) {
    setState({ key, data: key ? peekApiCache<T>(key) : undefined, error: null, refreshing: false });
  }

  const reload = useCallback(async () => {
    if (!key) return;
    setState((s) => ({ ...s, refreshing: true }));
    try {
      const data = await fetcherRef.current();
      setState((s) => (s.key === key ? { ...s, data, error: null, refreshing: false } : s));
    } catch (e) {
      const message = e instanceof Error ? e.message : "Something went wrong.";
      setState((s) => (s.key === key ? { ...s, error: message, refreshing: false } : s));
    }
  }, [key]);

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    fetcherRef.current()
      .then((data) => {
        if (!cancelled) setState((s) => (s.key === key ? { ...s, data, error: null, refreshing: false } : s));
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          const message = e instanceof Error ? e.message : "Something went wrong.";
          setState((s) => (s.key === key ? { ...s, error: message, refreshing: false } : s));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [key]);

  const setData = useCallback((updater: (prev: T | undefined) => T | undefined) => {
    setState((s) => ({ ...s, data: updater(s.data) }));
  }, []);

  return {
    data: state.data,
    error: state.error,
    loading: Boolean(key) && state.data === undefined && state.error === null,
    refreshing: state.refreshing,
    reload,
    setData,
  };
}

// ---------------------------------------------------------------------------
// Warm the API cache when a nav link is hovered, so the page opens with data.
// ---------------------------------------------------------------------------
const warmed = new Set<string>();

export function prefetchRouteData(href: string) {
  if (warmed.has(href) || !authStorage.getToken()) return;
  warmed.add(href);
  setTimeout(() => warmed.delete(href), 20000);
  const swallow = () => undefined;
  switch (href) {
    case "/knowledge-bases":
    case "/upload":
    case "/retrieval":
    case "/evaluation":
      api.listKBs().catch(swallow);
      break;
    case "/chat":
      api.listKBs().catch(swallow);
      api.listConversations().catch(swallow);
      break;
    case "/dashboard":
      api.getDashboardStats().catch(swallow);
      break;
    case "/analytics":
      api.getObservabilityLogs().catch(swallow);
      break;
    case "/users":
      api.listUsers().catch(swallow);
      break;
    case "/admin/documents":
      api.listAllDocumentsAdmin().catch(swallow);
      break;
    case "/settings":
      api.getConfigStatus().catch(swallow);
      break;
  }
}

export function formatBytes(bytes: number, decimals = 1) {
  if (!+bytes) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(decimals))} ${sizes[i]}`;
}

export function errorMessage(e: unknown, fallback = "Something went wrong.") {
  return e instanceof Error && e.message ? e.message : fallback;
}

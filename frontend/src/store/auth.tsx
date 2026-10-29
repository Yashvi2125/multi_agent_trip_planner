import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setUnauthorizedHandler, tokenStore } from "@/services/api";
import type { User } from "@/types/api";

interface AuthCtx {
  user: User | null;
  status: "loading" | "authed" | "anon";
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}
const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthCtx["status"]>(tokenStore.get() ? "loading" : "anon");

  const drop = useCallback(() => { tokenStore.clear(); setUser(null); setStatus("anon"); }, []);

  const refresh = useCallback(async () => {
    try { setUser(await api.auth.me()); setStatus("authed"); } catch { drop(); }
  }, [drop]);

  useEffect(() => {
    setUnauthorizedHandler(drop); // an expired token anywhere sends the user to sign in again
    if (tokenStore.get()) void refresh();
    return () => setUnauthorizedHandler(null);
  }, [drop, refresh]);

  const accept = (r: { access_token: string; user: User }) => { tokenStore.set(r.access_token); setUser(r.user); setStatus("authed"); };
  const value = useMemo<AuthCtx>(() => ({
    user, status, refresh,
    login: async (email, password) => accept(await api.auth.login({ email, password })),
    register: async (name, email, password) => accept(await api.auth.register({ name, email, password })),
    logout: async () => { try { await api.auth.logout(); } catch { /* token may already be invalid */ } drop(); },
  }), [user, status, refresh, drop]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used inside AuthProvider");
  return c;
}

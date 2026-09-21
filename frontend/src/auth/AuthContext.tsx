import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, tokens } from "../api/client";
import type { LoginResult, MfaChallenge, Profile, RoleCode } from "../api/types";

interface AuthState {
  user: Profile | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<MfaChallenge | null>;
  verifyMfa: (mfaToken: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
  can: (permission: string) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function homePath(role: RoleCode) {
  return role === "admin" ? "/admin" : role === "teacher" ? "/teacher" : "/student";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  const accept = (res: LoginResult) => {
    tokens.set(res.access_token, res.refresh_token);
    setUser(res.user);
  };

  const reload = useCallback(async () => {
    setUser(await api.get<Profile>("/auth/me"));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    if (!tokens.access && !tokens.refresh) { setLoading(false); return; }
    reload().catch(() => tokens.clear()).finally(() => setLoading(false));
  }, [reload]);

  const value = useMemo<AuthState>(() => ({
    user,
    loading,
    async login(username, password) {
      const res = await api.anon<LoginResult | MfaChallenge>("/auth/login", { username, password });
      if ("mfa_required" in res) return res;
      accept(res);
      return null;
    },
    async verifyMfa(mfaToken, code) {
      accept(await api.anon<LoginResult>("/auth/mfa", { mfa_token: mfaToken, code }));
    },
    async logout() {
      const refresh = tokens.refresh;
      try { if (refresh) await api.anon("/auth/logout", { refresh_token: refresh }); } catch { /* уже недействителен */ }
      tokens.clear();
      setUser(null);
    },
    reload,
    can: (p) => !!user?.permissions.includes(p),
  }), [user, loading, reload]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth вне AuthProvider");
  return v;
}

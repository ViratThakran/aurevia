"use client";

/**
 * The signed-in session: who the user is, in which tenant, and what they may do.
 * Hiding UI by permission is a convenience only; the API checks every request.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  api,
  onSessionExpired,
  refreshAccess,
  sessionCall,
  setAccessToken,
  type Schemas,
} from "./api";

export type Me = Schemas["MeResponse"];
export type Permission =
  | "calls.place"
  | "leads.manage"
  | "leads.privacy"
  | "campaigns.manage"
  | "agents.manage"
  | "numbers.manage"
  | "compliance.manage"
  | "team.manage"
  | "audit.read"
  | "analytics.read";

interface SessionValue {
  status: "loading" | "anonymous" | "ready";
  me: Me | null;
  can: (permission: Permission) => boolean;
  login: (email: string, password: string, tenantId?: string) => Promise<void>;
  signup: (body: Schemas["SignupRequest"]) => Promise<void>;
  acceptInvitation: (token: string, password: string, fullName?: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SessionValue["status"]>("loading");
  const [me, setMe] = useState<Me | null>(null);

  const loadMe = useCallback(async () => {
    const current = await api<Me>("/auth/me");
    setMe(current);
    setStatus("ready");
  }, []);

  useEffect(() => {
    onSessionExpired(() => {
      setAccessToken(null);
      setMe(null);
      setStatus("anonymous");
    });
    refreshAccess().then((ok) => (ok ? loadMe() : setStatus("anonymous"))).catch(() => {
      setStatus("anonymous");
    });
  }, [loadMe]);

  const value = useMemo<SessionValue>(
    () => ({
      status,
      me,
      can: (permission) => Boolean(me?.permissions?.includes(permission)),
      login: async (email, password, tenantId) => {
        await sessionCall("login", { email, password, tenant_id: tenantId ?? null });
        await loadMe();
      },
      signup: async (body) => {
        await sessionCall("signup", body);
        await loadMe();
      },
      acceptInvitation: async (token, password, fullName) => {
        await sessionCall("accept", { token, password, full_name: fullName || null });
        await loadMe();
      },
      logout: async () => {
        await sessionCall("logout").catch(() => undefined);
        setAccessToken(null);
        setMe(null);
        setStatus("anonymous");
      },
      reload: loadMe,
    }),
    [status, me, loadMe],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (value === null) throw new Error("useSession outside SessionProvider");
  return value;
}

export { ApiError };

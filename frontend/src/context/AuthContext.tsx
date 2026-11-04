"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

import { api, ApiError, getToken, setToken } from "@/lib/api";
import type { ApiUser, LoginResponse, MeResponse, Membership } from "@/lib/types";

interface AuthContextType {
  user: ApiUser | null;
  membership: Membership | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Adopt a session the API just issued (e.g. after a reset link). */
  startSession: (res: LoginResponse) => void;
  /** Replace the current user after a change the API reported back. */
  setMe: (me: MeResponse) => void;
}

// Reachable without a session: the login screen and the "Olvidé mi
// contraseña" flow (request a link, then follow it).
const PUBLIC_PATHS = ["/login", "/recuperar", "/restablecer"];
// Where a user with a temporary password is held until they replace it.
export const CHANGE_PASSWORD_PATH = "/cambiar-contrasena";

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [membership, setMembership] = useState<Membership | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  // Hydrate the current user from the token on mount.
  useEffect(() => {
    let cancelled = false;
    async function hydrate() {
      const token = getToken();
      if (!token) {
        setLoading(false);
        return;
      }
      try {
        const me = await api<MeResponse>("/auth/me");
        if (!cancelled) {
          setUser(me.user);
          setMembership(me.membership);
        }
      } catch {
        setToken(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    hydrate();
    return () => {
      cancelled = true;
    };
  }, []);

  // Route guard.
  useEffect(() => {
    if (loading) return;
    if (!user && !PUBLIC_PATHS.includes(pathname)) {
      router.push("/login");
    } else if (user?.must_change_password && pathname !== CHANGE_PASSWORD_PATH) {
      router.push(CHANGE_PASSWORD_PATH);
    } else if (user && pathname === "/login") {
      // Land authenticated users on the Centro de mando — the daily
      // command-center view; the navbar category picker drives its data.
      router.push("/centro-de-mando");
    }
  }, [user, loading, pathname, router]);

  const startSession = useCallback(
    (res: LoginResponse) => {
      setToken(res.access_token, res.expires_at);
      setUser(res.user);
      setMembership(res.membership);
      router.push(res.user.must_change_password ? CHANGE_PASSWORD_PATH : "/centro-de-mando");
    },
    [router],
  );

  const setMe = useCallback((me: MeResponse) => {
    setUser(me.user);
    setMembership(me.membership);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api<LoginResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      startSession(res);
    },
    [startSession],
  );

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setMembership(null);
    router.push("/login");
  }, [router]);

  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          width: "100%",
          height: "100vh",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        Loading...
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user, membership, login, logout, startSession, setMe }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

export { ApiError };

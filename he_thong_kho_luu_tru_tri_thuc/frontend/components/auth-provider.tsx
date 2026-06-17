"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, DashboardData, User } from "@/lib/api";
import { permissionsForRole } from "@/src/config/role-menu";

type AuthContextValue = {
  token: string;
  user: User | null;
  ready: boolean;
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
  login: (code: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);
const SESSION_KEY = "eduvault_session";

function normalizeUser(user: User): User {
  return {
    ...user,
    permissions: user.permissions?.length ? user.permissions : permissionsForRole(user.role),
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const savedSession = sessionStorage.getItem(SESSION_KEY);
    if (savedSession) {
      try {
        const parsed = JSON.parse(savedSession) as { token: string; user: User };
        if (parsed.token && parsed.user) {
          setToken(parsed.token);
          setUser(normalizeUser(parsed.user));
        }
      } catch {
        sessionStorage.removeItem(SESSION_KEY);
      }
    }
    const stored = localStorage.getItem("eduvault_token") || "";
    if (!stored) {
      setReady(true);
      return;
    }
    api<DashboardData>("/api/dashboard", {}, stored)
      .then((data) => {
        const nextUser = normalizeUser(data.user);
        setToken(stored);
        setUser(nextUser);
        sessionStorage.setItem(SESSION_KEY, JSON.stringify({ token: stored, user: nextUser }));
      })
      .catch(() => {
        localStorage.removeItem("eduvault_token");
        sessionStorage.removeItem(SESSION_KEY);
      })
      .finally(() => setReady(true));
  }, []);

  async function login(code: string, password: string) {
    const result = await api<{ token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ code, password }),
    });
    const nextUser = normalizeUser(result.user);
    localStorage.setItem("eduvault_token", result.token);
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ token: result.token, user: nextUser }));
    setToken(result.token);
    setUser(nextUser);
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" }, token);
    } finally {
      localStorage.removeItem("eduvault_token");
      sessionStorage.removeItem(SESSION_KEY);
      setToken("");
      setUser(null);
    }
  }

  const request = useCallback(async function request<T>(path: string, options: RequestInit = {}) {
    try {
      return await api<T>(path, options, token);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        localStorage.removeItem("eduvault_token");
        sessionStorage.removeItem(SESSION_KEY);
        setToken("");
        setUser(null);
      }
      throw error;
    }
  }, [token]);

  return <AuthContext.Provider value={{ token, user, ready, request, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

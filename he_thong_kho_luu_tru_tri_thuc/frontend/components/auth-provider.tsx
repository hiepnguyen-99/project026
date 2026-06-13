"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, DashboardData, User } from "@/lib/api";

type AuthContextValue = {
  token: string;
  user: User | null;
  ready: boolean;
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
  login: (code: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("eduvault_token") || "";
    if (!stored) {
      setReady(true);
      return;
    }
    api<DashboardData>("/api/dashboard", {}, stored)
      .then((data) => {
        setToken(stored);
        setUser(data.user);
      })
      .catch(() => localStorage.removeItem("eduvault_token"))
      .finally(() => setReady(true));
  }, []);

  async function login(code: string, password: string) {
    const result = await api<{ token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ code, password }),
    });
    localStorage.setItem("eduvault_token", result.token);
    setToken(result.token);
    setUser(result.user);
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" }, token);
    } finally {
      localStorage.removeItem("eduvault_token");
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

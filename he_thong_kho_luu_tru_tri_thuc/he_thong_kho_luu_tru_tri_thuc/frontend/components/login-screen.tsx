"use client";

import { useState } from "react";
import { BookOpenCheck, LoaderCircle, LockKeyhole } from "lucide-react";
import { useAuth } from "@/components/auth-provider";

export function LoginScreen() {
  const { login } = useAuth();
  const [code, setCode] = useState("GV001");
  const [password, setPassword] = useState("GV001");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await login(code, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng nhập thất bại.");
    } finally {
      setLoading(false);
    }
  }

  return <main className="min-h-screen bg-[var(--bg)] grid place-items-center p-4">
    <div className="app-card w-full max-w-md overflow-hidden">
      <div className="bg-[var(--sidebar)] p-7 text-white">
        <div className="h-11 w-11 rounded-xl bg-blue-500 grid place-items-center"><BookOpenCheck size={24}/></div>
        <h1 className="mt-5 text-2xl font-bold">EduVault</h1>
        <p className="mt-1 text-sm text-blue-100/70">Đăng nhập vào kho tri thức của khoa.</p>
      </div>
      <form className="p-7" onSubmit={submit}>
        <label className="text-xs font-bold">Mã người dùng<input className="field mt-2" value={code} onChange={e=>setCode(e.target.value)} /></label>
        <label className="mt-4 block text-xs font-bold">Mật khẩu<input type="password" className="field mt-2" value={password} onChange={e=>setPassword(e.target.value)} /></label>
        {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}
        <button disabled={loading} className="btn-primary mt-5 w-full">{loading?<LoaderCircle className="animate-spin" size={16}/>:<LockKeyhole size={16}/>}Đăng nhập</button>
        <p className="muted mt-4 text-[11px]">Tài khoản demo: GV001, GVNEW, TBM01 hoặc ADMIN. Mật khẩu mặc định giống mã tài khoản.</p>
      </form>
    </div>
  </main>;
}

"use client";

import { useState } from "react";
import { BookOpenCheck, CheckCircle2, LoaderCircle, LockKeyhole, UserPlus, X } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { API_URL } from "@/lib/api";

const ROLES = [
  { value: "lecturer", label: "Giảng viên" },
  { value: "new_lecturer", label: "Giảng viên mới" },
];

function RequestModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ full_name: "", email: "", department: "", reason: "Đăng ký tài khoản", requested_role: "lecturer" });
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  function set(key: string, value: string) {
    setForm(f => ({ ...f, [key]: value }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${API_URL}/api/account-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || "Gửi yêu cầu thất bại.");
      }
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi không xác định.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="app-card w-full max-w-md overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--muted)]">Đăng ký tài khoản</p>
            <h2 className="mt-0.5 text-sm font-bold">Gửi yêu cầu tạo tài khoản</h2>
          </div>
          <button onClick={onClose} className="icon-btn"><X size={16}/></button>
        </div>

        {done ? (
          <div className="p-8 text-center">
            <CheckCircle2 className="mx-auto text-green-500" size={40}/>
            <p className="mt-3 font-bold">Yêu cầu đã được gửi!</p>
            <p className="muted mt-1 text-xs">Admin sẽ xem xét và tạo tài khoản cho bạn. Vui lòng kiểm tra email để nhận thông tin đăng nhập.</p>
            <button className="btn-primary mt-5" onClick={onClose}>Đóng</button>
          </div>
        ) : (
          <form className="p-5 space-y-3" onSubmit={submit}>
            <label className="block text-xs font-bold">
              Họ và tên <span className="text-red-500">*</span>
              <input className="field mt-1" required value={form.full_name} onChange={e => set("full_name", e.target.value)} placeholder="Nguyễn Văn A"/>
            </label>
            <label className="block text-xs font-bold">
              Email <span className="text-red-500">*</span>
              <input type="email" className="field mt-1" required value={form.email} onChange={e => set("email", e.target.value)} placeholder="email@example.com"/>
            </label>
            <label className="block text-xs font-bold">
              Bộ môn / Khoa <span className="text-red-500">*</span>
              <input className="field mt-1" required value={form.department} onChange={e => set("department", e.target.value)} placeholder="Công nghệ thông tin"/>
            </label>
            <label className="block text-xs font-bold">
              Vai trò mong muốn
              <select className="field mt-1" value={form.requested_role} onChange={e => set("requested_role", e.target.value)}>
                {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </label>
            {error && <p className="rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
            <div className="flex gap-2 pt-1">
              <button type="button" className="btn-secondary flex-1" onClick={onClose}>Hủy</button>
              <button disabled={loading} className="btn-primary flex-1">
                {loading ? <LoaderCircle className="animate-spin" size={14}/> : <UserPlus size={14}/>}Gửi yêu cầu
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export function LoginScreen() {
  const { login } = useAuth();
  const [code, setCode] = useState("GV001");
  const [password, setPassword] = useState("GV001");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showRequest, setShowRequest] = useState(false);

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

  return (
    <>
      <main className="min-h-screen bg-[var(--bg)] grid place-items-center p-4">
        <div className="app-card w-full max-w-md overflow-hidden">
          <div className="bg-[var(--sidebar)] p-7 text-white">
            <div className="h-11 w-11 rounded-xl bg-blue-500 grid place-items-center"><BookOpenCheck size={24}/></div>
            <h1 className="mt-5 text-2xl font-bold">EduVault</h1>
            <p className="mt-1 text-sm text-blue-100/70">Đăng nhập vào kho tri thức của khoa.</p>
          </div>
          <form className="p-7" onSubmit={submit}>
            <label className="text-xs font-bold">Mã người dùng<input className="field mt-2" value={code} onChange={e => setCode(e.target.value)}/></label>
            <label className="mt-4 block text-xs font-bold">Mật khẩu<input type="password" className="field mt-2" value={password} onChange={e => setPassword(e.target.value)}/></label>
            {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}
            <button disabled={loading} className="btn-primary mt-5 w-full">
              {loading ? <LoaderCircle className="animate-spin" size={16}/> : <LockKeyhole size={16}/>}Đăng nhập
            </button>
            <div className="mt-4 flex items-center justify-between">
              <p className="muted text-[11px]">Tài khoản demo: GV001, GVNEW, TBM01, ADMIN</p>
              <button type="button" onClick={() => setShowRequest(true)} className="flex items-center gap-1 text-[11px] font-bold text-blue-600 hover:underline">
                <UserPlus size={12}/>Chưa có tài khoản?
              </button>
            </div>
          </form>
        </div>
      </main>
      {showRequest && <RequestModal onClose={() => setShowRequest(false)}/>}
    </>
  );
}

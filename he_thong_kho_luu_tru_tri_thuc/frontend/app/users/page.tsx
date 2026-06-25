"use client";

import { useState } from "react";
import { CheckCircle2, LoaderCircle, Pencil, ShieldCheck, UserCheck, UserPlus, Users, X } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { useBackendData } from "@/lib/hooks";
import { PageHeader, Panel } from "@/components/ui";

type User = { code: string; name: string; role: string; department: string; active: number };
type ProfileUpdateRequest = {
  id: string;
  user_code: string;
  new_name: string;
  new_department: string;
  reason: string;
  status: string;
  created_at: string;
  current_name: string;
  current_department: string;
};

const roleLabels: Record<string, string> = { lecturer: "Giang vien", new_lecturer: "Giang vien moi", head: "Truong bo mon", admin: "Quan tri vien" };
const roleBadge: Record<string, string> = { lecturer: "badge-green", new_lecturer: "badge-amber", head: "badge-blue", admin: "badge-red" };

function randomCode(name: string) {
  const ascii = name.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[đĐ]/g, "D");
  const initials = ascii.trim().split(/\s+/).map(w => w[0]?.toUpperCase() || "").filter(c => /[A-Z]/.test(c)).join("").slice(0, 3);
  const num = String(Math.floor(Math.random() * 900) + 100);
  return (initials || "USR") + num;
}

function CreateUserModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { request } = useAuth();
  const [form, setForm] = useState({ code: randomCode(""), name: "", password: "", role: "lecturer", department: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function set(key: string, value: string) {
    setForm(current => {
      const next = { ...current, [key]: value };
      if (key === "name") next.code = randomCode(value);
      return next;
    });
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await request("/api/admin/users", { method: "POST", body: JSON.stringify({ ...form, code: form.code.toUpperCase() }) });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Loi tao tai khoan.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="app-card w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div><p className="eyebrow">Tao moi</p><h2 className="mt-0.5 text-sm font-bold">Them tai khoan</h2></div>
          <button onClick={onClose} className="icon-btn"><X size={16}/></button>
        </div>
        <form className="p-5 space-y-3" onSubmit={submit}>
          <label className="block text-xs font-bold">Ho ten <span className="text-red-500">*</span>
            <input className="field mt-1" required value={form.name} onChange={e => set("name", e.target.value)} placeholder="Nguyen Van A"/>
          </label>
          <label className="block text-xs font-bold">Ma tai khoan <span className="text-red-500">*</span>
            <div className="mt-1 flex gap-2">
              <input className="field flex-1 uppercase" required value={form.code} onChange={e => setForm(current => ({ ...current, code: e.target.value.toUpperCase() }))}/>
              <button type="button" className="btn-secondary shrink-0 text-xs" onClick={() => setForm(current => ({ ...current, code: randomCode(current.name) }))}>Doi ma</button>
            </div>
          </label>
          <label className="block text-xs font-bold">Mat khau <span className="text-red-500">*</span>
            <input className="field mt-1" required minLength={4} value={form.password} onChange={e => set("password", e.target.value)}/>
          </label>
          <label className="block text-xs font-bold">Bo mon <span className="text-red-500">*</span>
            <input className="field mt-1" required value={form.department} onChange={e => set("department", e.target.value)} placeholder="Cong nghe thong tin"/>
          </label>
          <label className="block text-xs font-bold">Vai tro
            <select className="field mt-1" value={form.role} onChange={e => set("role", e.target.value)}>
              <option value="lecturer">Giang vien</option>
              <option value="new_lecturer">Giang vien moi</option>
              <option value="head">Truong bo mon</option>
              <option value="admin">Quan tri vien</option>
            </select>
          </label>
          {error && <p className="rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button type="button" className="btn-secondary flex-1" onClick={onClose}>Huy</button>
            <button className="btn-primary flex-1" disabled={loading}>
              {loading ? <LoaderCircle className="animate-spin" size={14}/> : <UserPlus size={14}/>}Tao tai khoan
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function EditUserModal({ userRow, onClose, onDone }: { userRow: User; onClose: () => void; onDone: () => void }) {
  const { request } = useAuth();
  const [form, setForm] = useState({ name: userRow.name, role: userRow.role, department: userRow.department, active: Boolean(userRow.active) });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function set(key: string, value: string | boolean) {
    setForm(current => ({ ...current, [key]: value }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await request(`/api/admin/users/${userRow.code}`, { method: "PUT", body: JSON.stringify(form) });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Loi cap nhat tai khoan.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="app-card w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div><p className="eyebrow">Chinh sua tai khoan</p><h2 className="mt-0.5 text-sm font-bold font-mono">{userRow.code}</h2></div>
          <button onClick={onClose} className="icon-btn"><X size={16}/></button>
        </div>
        <form className="p-5 space-y-3" onSubmit={submit}>
          <label className="block text-xs font-bold">Ho ten <span className="text-red-500">*</span>
            <input className="field mt-1" required value={form.name} onChange={e => set("name", e.target.value)}/>
          </label>
          <label className="block text-xs font-bold">Bo mon <span className="text-red-500">*</span>
            <input className="field mt-1" required value={form.department} onChange={e => set("department", e.target.value)}/>
          </label>
          <label className="block text-xs font-bold">Vai tro
            <select className="field mt-1" value={form.role} onChange={e => set("role", e.target.value)}>
              <option value="lecturer">Giang vien</option>
              <option value="new_lecturer">Giang vien moi</option>
              <option value="head">Truong bo mon</option>
              <option value="admin">Quan tri vien</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs font-bold cursor-pointer">
            <input type="checkbox" checked={form.active} onChange={e => set("active", e.target.checked)} className="h-4 w-4 rounded"/>
            Tai khoan dang hoat dong
          </label>
          {error && <p className="rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button type="button" className="btn-secondary flex-1" onClick={onClose}>Huy</button>
            <button className="btn-primary flex-1" disabled={loading}>
              {loading ? <LoaderCircle className="animate-spin" size={14}/> : <Pencil size={14}/>}Luu thay doi
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function UsersPage() {
  const { user, request } = useAuth();
  const { data: users, reload: reloadUsers } = useBackendData<User[]>("/api/admin/users", []);
  const { data: profileRequests, reload: reloadProfileRequests } = useBackendData<ProfileUpdateRequest[]>("/api/admin/profile-update-requests", []);
  const [editing, setEditing] = useState<User | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [message, setMessage] = useState("");

  if (user?.role !== "admin") {
    return <div className="p-10 text-center"><ShieldCheck className="mx-auto mb-3 text-[var(--muted)]" size={40}/><p className="font-bold">Chi quan tri vien moi co quyen truy cap trang nay.</p></div>;
  }

  async function approveProfile(id: string) {
    if (!confirm("Phe duyet cap nhat thong tin nay?")) return;
    try {
      await request(`/api/admin/profile-update-requests/${id}/approve`, { method: "PUT" });
      setMessage("Da phe duyet. Thong tin nguoi dung da duoc cap nhat.");
      reloadProfileRequests();
      reloadUsers();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Loi khi phe duyet.");
    }
  }

  async function rejectProfile(id: string) {
    if (!confirm("Tu choi yeu cau cap nhat nay?")) return;
    try {
      await request(`/api/admin/profile-update-requests/${id}/reject`, { method: "PUT" });
      setMessage("Da tu choi yeu cau cap nhat.");
      reloadProfileRequests();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Loi khi tu choi.");
    }
  }

  async function toggleActive(code: string, userRow: User) {
    await request(`/api/admin/users/${code}`, {
      method: "PUT",
      body: JSON.stringify({ name: userRow.name, role: userRow.role, department: userRow.department, active: !userRow.active }),
    });
    reloadUsers();
  }

  const pendingProfileRequests = profileRequests.filter(item => item.status === "pending");

  return (
    <div>
      <PageHeader
        eyebrow="Quan tri he thong"
        title="Nguoi dung"
        description="Quan ly tai khoan, vai tro va yeu cau cap nhat ho so trong he thong."
        actions={<button className="btn-primary" onClick={() => setShowCreate(true)}><UserPlus size={15}/>Tao tai khoan</button>}
      />

      {message && <p className="mb-4 rounded bg-green-50 p-3 text-xs text-green-700">{message}</p>}

      {pendingProfileRequests.length > 0 && (
        <Panel title={`Yeu cau cap nhat ho so (${pendingProfileRequests.length} cho duyet)`} className="mb-5">
          <div className="divide-y divide-[var(--border)]">
            {pendingProfileRequests.map(req => (
              <div key={req.id} className="flex items-start gap-4 p-4">
                <div className="h-9 w-9 shrink-0 rounded-full bg-blue-100 text-blue-700 grid place-items-center text-xs font-bold">
                  {req.user_code.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0 text-xs">
                  <p className="font-bold text-sm">{req.user_code}</p>
                  <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5">
                    <span className="muted">Ten hien tai:</span><span>{req.current_name}</span>
                    <span className="muted">Ten moi:</span><strong>{req.new_name}</strong>
                    <span className="muted">Bo mon hien tai:</span><span>{req.current_department}</span>
                    <span className="muted">Bo mon moi:</span><strong>{req.new_department}</strong>
                  </div>
                  <p className="muted mt-1">Ly do: {req.reason}</p>
                </div>
                <div className="flex shrink-0 flex-col gap-2">
                  <button className="btn-primary text-xs" onClick={() => approveProfile(req.id)}><UserCheck size={13}/>Duyet</button>
                  <button className="btn-secondary text-xs text-red-600" onClick={() => rejectProfile(req.id)}>Tu choi</button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel title={`Tai khoan he thong (${users.length})`}>
        <div className="table-shell">
          <table className="data-table">
            <thead><tr><th>Ma</th><th>Ho ten</th><th>Vai tro</th><th>Bo mon</th><th>Trang thai</th><th></th></tr></thead>
            <tbody>
              {users.map(userRow => (
                <tr key={userRow.code}>
                  <td><strong className="font-mono text-xs">{userRow.code}</strong></td>
                  <td>{userRow.name}</td>
                  <td><span className={`badge ${roleBadge[userRow.role] || "badge-green"}`}>{roleLabels[userRow.role] || userRow.role}</span></td>
                  <td className="muted text-xs">{userRow.department}</td>
                  <td>
                    <span className={`badge ${userRow.active ? "badge-green" : "badge-red"}`}>
                      {userRow.active ? <><CheckCircle2 size={11}/>Hoat dong</> : "Da khoa"}
                    </span>
                  </td>
                  <td>
                    <div className="flex gap-2">
                      <button className="btn-secondary text-xs" onClick={() => setEditing(userRow)}>
                        <Pencil size={12}/>Sua
                      </button>
                      {userRow.code !== user?.code && (
                        <button className="btn-secondary text-xs" onClick={() => toggleActive(userRow.code, userRow)}>
                          {userRow.active ? "Khoa" : "Mo khoa"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {showCreate && (
        <CreateUserModal onClose={() => setShowCreate(false)} onDone={() => { setShowCreate(false); setMessage("Tao tai khoan thanh cong."); reloadUsers(); }}/>
      )}
      {editing && (
        <EditUserModal userRow={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); setMessage("Da cap nhat tai khoan."); reloadUsers(); }}/>
      )}
    </div>
  );
}

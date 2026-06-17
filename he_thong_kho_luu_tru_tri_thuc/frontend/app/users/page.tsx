"use client";

import { useState } from "react";
import { CheckCircle2, LoaderCircle, Pencil, ShieldCheck, UserCheck, UserMinus, UserPlus, Users, X } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { useBackendData } from "@/lib/hooks";
import { PageHeader, Panel } from "@/components/ui";

type User = { code: string; name: string; role: string; department: string; active: number };
type AccountRequest = { id: string; full_name: string; email: string; department: string; reason: string; requested_role: string; status: string; created_at: string };
type ProfileUpdateRequest = { id: string; user_code: string; new_name: string; new_department: string; reason: string; status: string; created_at: string; current_name: string; current_department: string };

const roleLabels: Record<string, string> = { lecturer: "Giảng viên", new_lecturer: "Giảng viên mới", head: "Trưởng bộ môn", admin: "Quản trị viên" };
const roleBadge: Record<string, string> = { lecturer: "badge-green", new_lecturer: "badge-amber", head: "badge-blue", admin: "badge-red" };

function randomCode(name: string) {
  const ascii = name.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[đĐ]/g, "D");
  const initials = ascii.trim().split(/\s+/).map(w => w[0]?.toUpperCase() || "").filter(c => /[A-Z]/.test(c)).join("").slice(0, 3);
  const num = String(Math.floor(Math.random() * 900) + 100);
  return (initials || "USR") + num;
}

function ApproveModal({ req, onClose, onDone }: { req: AccountRequest; onClose: () => void; onDone: () => void }) {
  const { request } = useAuth();
  const [code, setCode] = useState(() => randomCode(req.full_name));
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(req.requested_role);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function approve(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await request(`/api/admin/account-requests/${req.id}/approve`, {
        method: "PUT",
        body: JSON.stringify({ code, password, role }),
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi khi duyệt yêu cầu.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="app-card w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div>
            <p className="eyebrow">Duyệt yêu cầu tài khoản</p>
            <h2 className="mt-0.5 text-sm font-bold">{req.full_name}</h2>
          </div>
          <button onClick={onClose} className="icon-btn"><X size={16}/></button>
        </div>
        <div className="p-5 text-xs space-y-1 bg-[var(--soft)]">
          <p><span className="muted">Email:</span> {req.email}</p>
          <p><span className="muted">Bộ môn:</span> {req.department}</p>
          <p><span className="muted">Lý do:</span> {req.reason}</p>
        </div>
        <form className="p-5 space-y-3" onSubmit={approve}>
          <label className="block text-xs font-bold">
            Mã tài khoản <span className="text-red-500">*</span>
            <div className="mt-1 flex gap-2">
              <input className="field flex-1 uppercase" required value={code} onChange={e => setCode(e.target.value.toUpperCase())}/>
              <button type="button" className="btn-secondary shrink-0 text-xs" onClick={() => setCode(randomCode(req.full_name))}>Đổi mã</button>
            </div>
          </label>
          <label className="block text-xs font-bold">
            Mật khẩu ban đầu <span className="text-red-500">*</span>
            <input className="field mt-1" required minLength={4} value={password} onChange={e => setPassword(e.target.value)} placeholder="Tối thiểu 4 ký tự"/>
          </label>
          <label className="block text-xs font-bold">
            Vai trò
            <select className="field mt-1" value={role} onChange={e => setRole(e.target.value)}>
              <option value="lecturer">Giảng viên</option>
              <option value="new_lecturer">Giảng viên mới</option>
              <option value="head">Trưởng bộ môn</option>
              <option value="admin">Quản trị viên</option>
            </select>
          </label>
          {error && <p className="rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button type="button" className="btn-secondary flex-1" onClick={onClose}>Hủy</button>
            <button className="btn-primary flex-1" disabled={loading}>
              {loading ? <LoaderCircle className="animate-spin" size={14}/> : <UserCheck size={14}/>}Tạo tài khoản
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function CreateUserModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { request } = useAuth();
  const [form, setForm] = useState({ code: randomCode(""), name: "", password: "", role: "lecturer", department: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function set(key: string, value: string) {
    setForm(f => {
      const updated = { ...f, [key]: value };
      if (key === "name") updated.code = randomCode(value);
      return updated;
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await request("/api/admin/users", { method: "POST", body: JSON.stringify({ ...form, code: form.code.toUpperCase() }) });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi tạo tài khoản.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="app-card w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div><p className="eyebrow">Tạo mới</p><h2 className="mt-0.5 text-sm font-bold">Thêm tài khoản</h2></div>
          <button onClick={onClose} className="icon-btn"><X size={16}/></button>
        </div>
        <form className="p-5 space-y-3" onSubmit={submit}>
          <label className="block text-xs font-bold">Họ tên <span className="text-red-500">*</span>
            <input className="field mt-1" required value={form.name} onChange={e => set("name", e.target.value)} placeholder="Nguyễn Văn A"/>
          </label>
          <label className="block text-xs font-bold">Mã tài khoản <span className="text-red-500">*</span>
            <div className="mt-1 flex gap-2">
              <input className="field flex-1 uppercase" required value={form.code} onChange={e => setForm(f => ({ ...f, code: e.target.value.toUpperCase() }))}/>
              <button type="button" className="btn-secondary shrink-0 text-xs" onClick={() => setForm(f => ({ ...f, code: randomCode(f.name) }))}>Đổi mã</button>
            </div>
          </label>
          <label className="block text-xs font-bold">Mật khẩu <span className="text-red-500">*</span>
            <input className="field mt-1" required minLength={4} value={form.password} onChange={e => set("password", e.target.value)}/>
          </label>
          <label className="block text-xs font-bold">Bộ môn <span className="text-red-500">*</span>
            <input className="field mt-1" required value={form.department} onChange={e => set("department", e.target.value)} placeholder="Công nghệ thông tin"/>
          </label>
          <label className="block text-xs font-bold">Vai trò
            <select className="field mt-1" value={form.role} onChange={e => set("role", e.target.value)}>
              <option value="lecturer">Giảng viên</option>
              <option value="new_lecturer">Giảng viên mới</option>
              <option value="head">Trưởng bộ môn</option>
              <option value="admin">Quản trị viên</option>
            </select>
          </label>
          {error && <p className="rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button type="button" className="btn-secondary flex-1" onClick={onClose}>Hủy</button>
            <button className="btn-primary flex-1" disabled={loading}>
              {loading ? <LoaderCircle className="animate-spin" size={14}/> : <UserPlus size={14}/>}Tạo tài khoản
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function EditUserModal({ u, onClose, onDone }: { u: User; onClose: () => void; onDone: () => void }) {
  const { request } = useAuth();
  const [form, setForm] = useState({ name: u.name, role: u.role, department: u.department, active: Boolean(u.active) });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function set(key: string, value: string | boolean) { setForm(f => ({ ...f, [key]: value })); }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await request(`/api/admin/users/${u.code}`, { method: "PUT", body: JSON.stringify(form) });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi cập nhật.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="app-card w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div>
            <p className="eyebrow">Chỉnh sửa tài khoản</p>
            <h2 className="mt-0.5 text-sm font-bold font-mono">{u.code}</h2>
          </div>
          <button onClick={onClose} className="icon-btn"><X size={16}/></button>
        </div>
        <form className="p-5 space-y-3" onSubmit={submit}>
          <label className="block text-xs font-bold">Họ tên <span className="text-red-500">*</span>
            <input className="field mt-1" required value={form.name} onChange={e => set("name", e.target.value)}/>
          </label>
          <label className="block text-xs font-bold">Bộ môn <span className="text-red-500">*</span>
            <input className="field mt-1" required value={form.department} onChange={e => set("department", e.target.value)}/>
          </label>
          <label className="block text-xs font-bold">Vai trò
            <select className="field mt-1" value={form.role} onChange={e => set("role", e.target.value)}>
              <option value="lecturer">Giảng viên</option>
              <option value="new_lecturer">Giảng viên mới</option>
              <option value="head">Trưởng bộ môn</option>
              <option value="admin">Quản trị viên</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs font-bold cursor-pointer">
            <input type="checkbox" checked={form.active} onChange={e => set("active", e.target.checked)} className="h-4 w-4 rounded"/>
            Tài khoản đang hoạt động
          </label>
          {error && <p className="rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button type="button" className="btn-secondary flex-1" onClick={onClose}>Hủy</button>
            <button className="btn-primary flex-1" disabled={loading}>
              {loading ? <LoaderCircle className="animate-spin" size={14}/> : <Pencil size={14}/>}Lưu thay đổi
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
  const { data: requests, reload: reloadRequests } = useBackendData<AccountRequest[]>("/api/admin/account-requests", []);
  const { data: profileRequests, reload: reloadProfileRequests } = useBackendData<ProfileUpdateRequest[]>("/api/admin/profile-update-requests", []);
  const [approving, setApproving] = useState<AccountRequest | null>(null);
  const [editing, setEditing] = useState<User | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [message, setMessage] = useState("");

  if (user?.role !== "admin") {
    return <div className="p-10 text-center"><ShieldCheck className="mx-auto mb-3 text-[var(--muted)]" size={40}/><p className="font-bold">Chỉ quản trị viên mới có quyền truy cập trang này.</p></div>;
  }

  const pending = requests.filter(r => r.status === "pending");
  const done = requests.filter(r => r.status !== "pending");

  async function reject(id: string) {
    if (!confirm("Từ chối yêu cầu này?")) return;
    await request(`/api/admin/account-requests/${id}/reject`, { method: "PUT" });
    setMessage("Đã từ chối yêu cầu.");
    reloadRequests();
  }

  async function approveProfile(id: string) {
    if (!confirm("Phê duyệt cập nhật thông tin này?")) return;
    try {
      await request(`/api/admin/profile-update-requests/${id}/approve`, { method: "PUT" });
      setMessage("Đã phê duyệt. Thông tin người dùng đã được cập nhật.");
      reloadProfileRequests(); reloadUsers();
    } catch (err) { setMessage(err instanceof Error ? err.message : "Lỗi khi duyệt."); }
  }

  async function rejectProfile(id: string) {
    if (!confirm("Từ chối yêu cầu cập nhật này?")) return;
    try {
      await request(`/api/admin/profile-update-requests/${id}/reject`, { method: "PUT" });
      setMessage("Đã từ chối yêu cầu cập nhật.");
      reloadProfileRequests();
    } catch (err) { setMessage(err instanceof Error ? err.message : "Lỗi khi từ chối."); }
  }

  async function toggleActive(code: string, u: User) {
    await request(`/api/admin/users/${code}`, {
      method: "PUT",
      body: JSON.stringify({ name: u.name, role: u.role, department: u.department, active: !u.active }),
    });
    reloadUsers();
  }

  return (
    <div>
      <PageHeader
        eyebrow="Quản trị hệ thống"
        title="Quản lý tài khoản"
        description="Xem và quản lý tất cả người dùng trong hệ thống."
        actions={<button className="btn-primary" onClick={() => setShowCreate(true)}><UserPlus size={15}/>Tạo tài khoản</button>}
      />

      {message && <p className="mb-4 rounded bg-green-50 p-3 text-xs text-green-700">{message}</p>}

      {pending.length > 0 && (
        <Panel title={`Yêu cầu đang chờ duyệt (${pending.length})`} className="mb-5">
          <div className="divide-y divide-[var(--border)]">
            {pending.map(req => (
              <div key={req.id} className="flex items-start gap-4 p-4">
                <div className="h-9 w-9 shrink-0 rounded-full bg-amber-100 text-amber-700 grid place-items-center text-xs font-bold">
                  {req.full_name.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold">{req.full_name}</p>
                  <p className="muted text-xs">{req.email} · {req.department} · {roleLabels[req.requested_role] || req.requested_role}</p>
                  <p className="mt-1 text-xs text-[var(--text)]">{req.reason}</p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button className="btn-primary text-xs" onClick={() => setApproving(req)}><UserCheck size={13}/>Duyệt</button>
                  <button className="btn-secondary text-xs text-red-600" onClick={() => reject(req.id)}><UserMinus size={13}/>Từ chối</button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {profileRequests.filter(r => r.status === "pending").length > 0 && (
        <Panel title={`Yêu cầu cập nhật hồ sơ (${profileRequests.filter(r => r.status === "pending").length} chờ duyệt)`} className="mb-5">
          <div className="divide-y divide-[var(--border)]">
            {profileRequests.filter(r => r.status === "pending").map(req => (
              <div key={req.id} className="flex items-start gap-4 p-4">
                <div className="h-9 w-9 shrink-0 rounded-full bg-blue-100 text-blue-700 grid place-items-center text-xs font-bold">
                  {req.user_code.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0 text-xs">
                  <p className="font-bold text-sm">{req.user_code}</p>
                  <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5">
                    <span className="muted">Tên hiện tại:</span><span>{req.current_name}</span>
                    <span className="muted">Tên mới:</span><strong>{req.new_name}</strong>
                    <span className="muted">Bộ môn hiện tại:</span><span>{req.current_department}</span>
                    <span className="muted">Bộ môn mới:</span><strong>{req.new_department}</strong>
                  </div>
                  <p className="muted mt-1">Lý do: {req.reason}</p>
                </div>
                <div className="flex shrink-0 flex-col gap-2">
                  <button className="btn-primary text-xs" onClick={() => approveProfile(req.id)}><UserCheck size={13}/>Duyệt</button>
                  <button className="btn-secondary text-xs text-red-600" onClick={() => rejectProfile(req.id)}><UserMinus size={13}/>Từ chối</button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel title={`Tài khoản hệ thống (${users.length})`}>
        <div className="table-shell">
          <table className="data-table">
            <thead><tr><th>Mã</th><th>Họ tên</th><th>Vai trò</th><th>Bộ môn</th><th>Trạng thái</th><th></th></tr></thead>
            <tbody>
              {users.map(u => (
                <tr key={u.code}>
                  <td><strong className="font-mono text-xs">{u.code}</strong></td>
                  <td>{u.name}</td>
                  <td><span className={`badge ${roleBadge[u.role] || "badge-green"}`}>{roleLabels[u.role] || u.role}</span></td>
                  <td className="muted text-xs">{u.department}</td>
                  <td>
                    <span className={`badge ${u.active ? "badge-green" : "badge-red"}`}>
                      {u.active ? <><CheckCircle2 size={11}/>Hoạt động</> : "Đã khóa"}
                    </span>
                  </td>
                  <td>
                    <div className="flex gap-2">
                      <button className="btn-secondary text-xs" onClick={() => setEditing(u)}>
                        <Pencil size={12}/>Sửa
                      </button>
                      {u.code !== user?.code && (
                        <button className="btn-secondary text-xs" onClick={() => toggleActive(u.code, u)}>
                          {u.active ? "Khóa" : "Mở khóa"}
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

      {done.length > 0 && (
        <Panel title="Lịch sử yêu cầu" className="mt-5">
          <div className="table-shell">
            <table className="data-table">
              <thead><tr><th>Họ tên</th><th>Email</th><th>Bộ môn</th><th>Trạng thái</th></tr></thead>
              <tbody>
                {done.map(r => (
                  <tr key={r.id}>
                    <td>{r.full_name}</td>
                    <td className="muted text-xs">{r.email}</td>
                    <td className="muted text-xs">{r.department}</td>
                    <td><span className={`badge ${r.status === "approved" ? "badge-green" : "badge-red"}`}>{r.status === "approved" ? "Đã duyệt" : "Từ chối"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {approving && (
        <ApproveModal req={approving} onClose={() => setApproving(null)} onDone={() => { setApproving(null); setMessage("Đã tạo tài khoản thành công!"); reloadUsers(); reloadRequests(); }}/>
      )}
      {showCreate && (
        <CreateUserModal onClose={() => setShowCreate(false)} onDone={() => { setShowCreate(false); setMessage("Tạo tài khoản thành công!"); reloadUsers(); }}/>
      )}
      {editing && (
        <EditUserModal u={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); setMessage("Đã cập nhật tài khoản!"); reloadUsers(); }}/>
      )}
    </div>
  );
}

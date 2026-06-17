"use client";

import { CheckCircle2, Clock, Edit3, KeyRound, Save, UserCog, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { PermissionGuard } from "@/components/permission-guard";
import { useAuth } from "@/components/auth-provider";
import { PageHeader, Panel } from "@/components/ui";
import { ProfileSpecializations, formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { ROLE_LABELS, toAppRole } from "@/src/config/role-menu";

const emptyProfile: ProfileSpecializations = { policy: null, available: [], selected_ids: [] };

type UpdateRequest = {
  id: string; user_code: string; new_name: string; new_department: string;
  reason: string; status: "pending" | "approved" | "rejected";
  created_at: string; reviewed_at: string | null; reviewed_by: string | null;
};

function StatusBadge({ status }: { status: string }) {
  if (status === "pending") return <span className="badge badge-amber flex items-center gap-1"><Clock size={10}/>Đang chờ duyệt</span>;
  if (status === "approved") return <span className="badge badge-green flex items-center gap-1"><CheckCircle2 size={10}/>Đã duyệt</span>;
  return <span className="badge badge-red flex items-center gap-1"><XCircle size={10}/>Bị từ chối</span>;
}

function ProfileContent() {
  const { user, request } = useAuth();
  const { data: profile, reload: reloadProfile } = useBackendData<ProfileSpecializations>("/api/profile/specializations", emptyProfile);
  const { data: myRequests, reload: reloadRequests } = useBackendData<UpdateRequest[]>("/api/profile/update-requests", []);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const selected = useMemo(() => new Set(selectedIds.length ? selectedIds : profile.selected_ids), [selectedIds, profile.selected_ids]);
  const roleLabel = user ? ROLE_LABELS[toAppRole(user.role)] : "";

  // Update info request form
  const [editMode, setEditMode] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDept, setNewDept] = useState("");
  const [reason, setReason] = useState("");
  const [updateMsg, setUpdateMsg] = useState("");
  const [updateLoading, setUpdateLoading] = useState(false);

  // Password change form
  const [pwOpen, setPwOpen] = useState(false);
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwMsg, setPwMsg] = useState("");
  const [pwLoading, setPwLoading] = useState(false);

  const hasPending = myRequests.some(r => r.status === "pending");

  function openEdit() {
    setNewName(user?.name ?? "");
    setNewDept(user?.department ?? "");
    setReason("");
    setUpdateMsg("");
    setEditMode(true);
  }

  async function submitUpdate(e: React.FormEvent) {
    e.preventDefault();
    setUpdateLoading(true); setUpdateMsg("");
    try {
      await request("/api/profile/update-request", {
        method: "POST",
        body: JSON.stringify({ new_name: newName, new_department: newDept, reason }),
      });
      setUpdateMsg("Yêu cầu đã được gửi. Admin sẽ xem xét và phê duyệt trong thời gian sớm nhất.");
      setEditMode(false);
      await reloadRequests();
    } catch (err) {
      setUpdateMsg(err instanceof Error ? err.message : "Không thể gửi yêu cầu.");
    } finally {
      setUpdateLoading(false);
    }
  }

  async function submitPw(e: React.FormEvent) {
    e.preventDefault();
    if (newPw !== confirmPw) { setPwMsg("Mật khẩu xác nhận không khớp."); return; }
    setPwLoading(true); setPwMsg("");
    try {
      const r = await request<{ message: string }>("/api/profile/password", {
        method: "PUT",
        body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
      });
      setPwMsg(r.message);
      setCurrentPw(""); setNewPw(""); setConfirmPw("");
      setPwOpen(false);
    } catch (err) {
      setPwMsg(err instanceof Error ? err.message : "Không thể đổi mật khẩu.");
    } finally {
      setPwLoading(false);
    }
  }

  async function saveSpecializations() {
    try {
      const result = await request<ProfileSpecializations & { message?: string }>(
        "/api/profile/specializations",
        { method: "PUT", body: JSON.stringify({ specialization_ids: [...selected] }) }
      );
      setSelectedIds(result.selected_ids);
      await reloadProfile();
    } catch { /* silent */ }
  }

  function toggle(id: string) {
    setSelectedIds(cur => {
      const next = new Set(cur.length ? cur : profile.selected_ids);
      if (next.has(id)) next.delete(id); else next.add(id);
      return [...next];
    });
  }

  return (
    <div>
      <PageHeader
        eyebrow="Hồ sơ"
        title="Hồ sơ cá nhân"
        description="Xem thông tin tài khoản, gửi yêu cầu cập nhật hoặc đổi mật khẩu."
      />

      {updateMsg && (
        <p className={`mb-4 rounded p-3 text-xs ${updateMsg.startsWith("Yêu cầu đã") ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>
          {updateMsg}
        </p>
      )}
      {pwMsg && (
        <p className={`mb-4 rounded p-3 text-xs ${pwMsg.includes("thành công") ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>
          {pwMsg}
        </p>
      )}

      <div className="grid gap-5 xl:grid-cols-[1fr_1fr]">
        {/* ── Thông tin tài khoản ── */}
        <Panel title="Thông tin tài khoản">
          <div className="p-5">
            <div className="flex items-center gap-3 mb-5">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-white font-bold text-lg">
                {user?.name?.[0]?.toUpperCase() ?? "?"}
              </div>
              <div>
                <strong className="block">{user?.name}</strong>
                <span className="muted text-xs">{roleLabel}</span>
              </div>
            </div>
            <div className="space-y-3">
              {[
                ["Mã tài khoản", user?.code],
                ["Họ tên", user?.name],
                ["Vai trò", roleLabel],
                ["Đơn vị / Bộ môn", user?.department],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between border-b border-[var(--border)] pb-3 text-sm">
                  <span className="muted text-xs">{label}</span>
                  <strong className="text-xs">{value || "—"}</strong>
                </div>
              ))}
            </div>

            <div className="mt-5 flex flex-col gap-2">
              {!hasPending ? (
                <button className="btn-secondary w-full" onClick={openEdit}>
                  <Edit3 size={14}/>Gửi yêu cầu cập nhật thông tin
                </button>
              ) : (
                <p className="rounded bg-amber-50 p-2 text-[11px] text-amber-800 text-center">
                  Bạn có yêu cầu đang chờ admin duyệt.
                </p>
              )}
              <button className="btn-secondary w-full" onClick={() => { setPwOpen(o => !o); setPwMsg(""); }}>
                <KeyRound size={14}/>{pwOpen ? "Đóng đổi mật khẩu" : "Đổi mật khẩu"}
              </button>
            </div>

            {/* Password change form */}
            {pwOpen && (
              <form onSubmit={submitPw} className="mt-4 space-y-3 rounded-xl border border-[var(--border)] p-4">
                <p className="text-xs font-bold">Đổi mật khẩu</p>
                <input className="field text-xs" type="password" placeholder="Mật khẩu hiện tại" value={currentPw} onChange={e => setCurrentPw(e.target.value)} required/>
                <input className="field text-xs" type="password" placeholder="Mật khẩu mới (tối thiểu 4 ký tự)" value={newPw} onChange={e => setNewPw(e.target.value)} required minLength={4}/>
                <input className="field text-xs" type="password" placeholder="Xác nhận mật khẩu mới" value={confirmPw} onChange={e => setConfirmPw(e.target.value)} required/>
                <button type="submit" disabled={pwLoading} className="btn-primary w-full disabled:opacity-50">
                  {pwLoading ? "Đang xử lý..." : "Xác nhận đổi mật khẩu"}
                </button>
              </form>
            )}
          </div>
        </Panel>

        {/* ── Cập nhật thông tin / Lịch sử ── */}
        <div className="flex flex-col gap-5">
          {/* Update info form */}
          {editMode && (
            <Panel title="Gửi yêu cầu cập nhật thông tin">
              <form onSubmit={submitUpdate} className="space-y-3 p-5">
                <p className="muted text-[11px]">Yêu cầu sẽ được gửi đến Admin để xem xét và phê duyệt.</p>
                <div>
                  <label className="muted mb-1 block text-[10px] uppercase font-bold">Họ tên mới</label>
                  <input className="field text-sm" value={newName} onChange={e => setNewName(e.target.value)} required minLength={2} maxLength={120}/>
                </div>
                <div>
                  <label className="muted mb-1 block text-[10px] uppercase font-bold">Đơn vị / Bộ môn mới</label>
                  <input className="field text-sm" value={newDept} onChange={e => setNewDept(e.target.value)} required minLength={2} maxLength={120}/>
                </div>
                <div>
                  <label className="muted mb-1 block text-[10px] uppercase font-bold">Lý do cập nhật</label>
                  <textarea className="field text-sm resize-none" rows={3} value={reason} onChange={e => setReason(e.target.value)} required minLength={5} maxLength={500} placeholder="Ví dụ: Thay đổi bộ môn công tác..."/>
                </div>
                <div className="flex gap-2">
                  <button type="submit" disabled={updateLoading} className="btn-primary flex-1 disabled:opacity-50">
                    <Save size={14}/>{updateLoading ? "Đang gửi..." : "Gửi yêu cầu"}
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => setEditMode(false)}>Hủy</button>
                </div>
              </form>
            </Panel>
          )}

          {/* History of update requests */}
          <Panel title="Lịch sử yêu cầu cập nhật">
            <div className="p-4">
              {myRequests.length === 0 ? (
                <p className="muted text-xs text-center py-3">Chưa có yêu cầu cập nhật nào.</p>
              ) : (
                <div className="space-y-3">
                  {myRequests.map(r => (
                    <div key={r.id} className="rounded-lg border border-[var(--border)] p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-xs">
                          <span className="muted">Họ tên → </span><strong>{r.new_name}</strong>
                          <br/>
                          <span className="muted">Bộ môn → </span><strong>{r.new_department}</strong>
                        </div>
                        <StatusBadge status={r.status}/>
                      </div>
                      <p className="muted mt-2 text-[10px]">Lý do: {r.reason}</p>
                      <p className="muted mt-1 text-[10px]">Gửi: {formatDate(r.created_at)}{r.reviewed_at ? ` · Xử lý: ${formatDate(r.reviewed_at)}` : ""}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Panel>

          {/* Specializations */}
          <Panel title="Nhóm chuyên môn">
            <div className="space-y-3 p-5">
              {!profile.policy && <p className="rounded bg-amber-50 p-3 text-xs text-amber-800">Hệ thống chưa có policy active. Vui lòng liên hệ Admin.</p>}
              {profile.available.map(spec => (
                <label key={spec.id} className="flex items-center gap-3 rounded-lg border border-[var(--border)] p-3 text-sm cursor-pointer hover:bg-[var(--soft)]">
                  <input type="checkbox" checked={selected.has(spec.id)} onChange={() => toggle(spec.id)}/>
                  <span>
                    <strong className="block">{spec.name}</strong>
                    <span className="muted text-[10px]">Virtual view sẽ lấy subtree tương ứng từ Master Folder Tree.</span>
                  </span>
                </label>
              ))}
              {!profile.available.length && profile.policy && <p className="muted text-xs">Policy active chưa có nhóm chuyên môn.</p>}
              {profile.available.length > 0 && (
                <button className="btn-primary w-full mt-2" onClick={saveSpecializations}>
                  <Save size={14}/>Lưu nhóm chuyên môn
                </button>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  return <PermissionGuard permission="profile.manage"><ProfileContent /></PermissionGuard>;
}

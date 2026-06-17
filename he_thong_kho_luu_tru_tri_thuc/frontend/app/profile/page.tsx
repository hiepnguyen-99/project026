"use client";

import { ChevronDown, ChevronRight, Folder, FolderOpen, Save, UserCog } from "lucide-react";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { PermissionGuard } from "@/components/permission-guard";
import { useAuth } from "@/components/auth-provider";
import { PageHeader, Panel } from "@/components/ui";
import { LecturerFolderNode, ProfileSpecializations, Specialization } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { ROLE_LABELS, toAppRole } from "@/src/config/role-menu";

const emptyProfile: ProfileSpecializations = { policy: null, available: [], selected_ids: [] };

function ProfileContent() {
  const { user, request } = useAuth();
  const { data: profile, reload } = useBackendData<ProfileSpecializations>("/api/profile/specializations", emptyProfile);
  const { data: specializations } = useBackendData<Specialization[]>("/api/specializations", []);
  const { data: folderTree, reload: reloadFolderTree } = useBackendData<LecturerFolderNode[]>(
    user ? `/api/lecturers/${user.code}/folder-tree` : "",
    [],
  );
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const available = specializations.length ? specializations : profile.available;
  const selected = useMemo(() => new Set(selectedIds.length ? selectedIds : profile.selected_ids), [selectedIds, profile.selected_ids]);
  const roleLabel = user ? ROLE_LABELS[toAppRole(user.role)] : "";

  function toggle(id: string) {
    setSelectedIds(current => {
      const next = new Set(current.length ? current : profile.selected_ids);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return [...next];
    });
  }

  async function save() {
    if (!user) return;
    setMessage("");
    try {
      const result = await request<ProfileSpecializations & { message?: string }>(
        `/api/lecturers/${user.code}/specializations`,
        { method: "POST", body: JSON.stringify({ specialization_ids: [...selected] }) },
      );
      setSelectedIds(result.selected_ids);
      await Promise.all([reload(), reloadFolderTree()]);
      setMessage(result.message || "Cây thư mục cá nhân đã được tạo theo nhóm chuyên môn đã chọn.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Không lưu được nhóm chuyên môn.");
    }
  }

  return <div>
    <PageHeader
      eyebrow="Hồ sơ"
      title="Hồ sơ cá nhân"
      description="Cập nhật nhóm chuyên môn giảng dạy để EduVault tự tạo cây thư mục cá nhân."
      actions={<button className="btn-primary" onClick={save}><Save size={15}/>Lưu hồ sơ</button>}
    />
    {message && <p className="mb-4 rounded bg-emerald-50 p-3 text-xs text-emerald-800">{message}</p>}
    <div className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]">
      <Panel title="Thông tin phiên đăng nhập">
        <div className="space-y-3 p-5 text-sm">
          <div className="flex items-center gap-3"><UserCog className="text-blue-600"/><strong>{user?.name}</strong></div>
          {[["Mã tài khoản", user?.code], ["Vai trò", roleLabel], ["Đơn vị", user?.department]].map(item =>
            <div key={item[0]} className="flex justify-between border-b border-[var(--border)] pb-2 text-xs">
              <span className="muted">{item[0]}</span><strong>{item[1]}</strong>
            </div>,
          )}
        </div>
      </Panel>
      <Panel title="Nhóm chuyên môn giảng dạy" description="Danh sách này được lấy từ Policy đang active, không hard-code ở frontend.">
        <div className="space-y-3 p-5">
          {!profile.policy && <p className="rounded bg-amber-50 p-3 text-xs text-amber-800">Hệ thống chưa có Policy active. Vui lòng liên hệ Admin.</p>}
          {available.map(spec => <label key={spec.id} className="flex items-center gap-3 rounded-lg border border-[var(--border)] p-3 text-sm">
            <input type="checkbox" checked={selected.has(spec.id)} onChange={() => toggle(spec.id)}/>
            <span>
              <strong className="block">{spec.name}</strong>
              <span className="muted text-[10px]">{spec.courses_count ?? 0} học phần sẽ được đưa vào cây thư mục cá nhân.</span>
            </span>
          </label>)}
          {!available.length && profile.policy && <p className="muted text-xs">Policy active chưa có nhóm chuyên môn.</p>}
        </div>
      </Panel>
    </div>
    <Panel title="Cây thư mục cá nhân" description="Các nhánh được tạo tự động từ chuyên môn đã tick." className="mt-5">
      <div className="p-4">
        {folderTree.length ? <FolderTree nodes={folderTree}/> : <p className="muted text-xs">Chưa có cây thư mục cá nhân. Hãy chọn nhóm chuyên môn và bấm Lưu hồ sơ.</p>}
      </div>
    </Panel>
  </div>;
}

function FolderTree({ nodes }: { nodes: LecturerFolderNode[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(nodes.map(node => node.id)));

  function toggle(id: string) {
    setExpanded(current => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function render(node: LecturerFolderNode, depth = 0): ReactNode {
    const isExpanded = expanded.has(node.id);
    return <div key={node.id}>
      <button type="button" className="flex w-full items-center gap-1 rounded-md py-1.5 pr-2 text-left text-xs hover:bg-[var(--soft)]" style={{ paddingLeft: `${6 + depth * 16}px` }} onClick={() => toggle(node.id)}>
        {node.children.length ? (isExpanded ? <ChevronDown size={14}/> : <ChevronRight size={14}/>) : <span className="w-[14px]"/>}
        {isExpanded ? <FolderOpen className="text-amber-500" size={15}/> : <Folder className="text-amber-500" size={15}/>}
        <span className="truncate font-semibold">{node.name}</span>
      </button>
      {isExpanded && node.children.map(child => render(child, depth + 1))}
    </div>;
  }

  return <div role="tree" className="max-h-[55vh] overflow-auto">{nodes.map(node => render(node))}</div>;
}

export default function ProfilePage() {
  return <PermissionGuard permission="profile.manage"><ProfileContent /></PermissionGuard>;
}

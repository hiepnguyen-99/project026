"use client";

import { UserCog, Users } from "lucide-react";
import { PermissionGuard } from "@/components/permission-guard";
import { PageHeader, Panel } from "@/components/ui";
import { useBackendData } from "@/lib/hooks";

type AdminUser = {
  code: string;
  name: string;
  role: string;
  department: string;
  active: number;
};

function UsersPageContent() {
  const { data, error } = useBackendData<AdminUser[]>("/api/admin/users", []);
  return <div>
    <PageHeader eyebrow="Người dùng" title="Quản lý tài khoản" description="Danh sách actor trong hệ thống EduVault theo RBAC."/>
    {error&&<p className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">{error}</p>}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div className="app-card p-4"><Users className="text-blue-600" size={18}/><strong className="mt-3 block text-xl">{data.length}</strong><span className="muted text-xs">Tài khoản</span></div>
      <div className="app-card p-4"><UserCog className="text-blue-600" size={18}/><strong className="mt-3 block text-xl">{data.filter(user=>user.active).length}</strong><span className="muted text-xs">Đang hoạt động</span></div>
    </div>
    <Panel title="Danh sách người dùng" className="mt-5">
      <div className="table-shell"><table className="data-table"><thead><tr><th>Mã</th><th>Tên</th><th>Role</th><th>Đơn vị</th><th>Trạng thái</th></tr></thead><tbody>{data.map(user=><tr key={user.code}><td><strong>{user.code}</strong></td><td>{user.name}</td><td>{user.role}</td><td>{user.department}</td><td><span className={`badge ${user.active?"badge-green":"badge-amber"}`}>{user.active?"active":"inactive"}</span></td></tr>)}</tbody></table></div>
    </Panel>
  </div>;
}

export default function UsersPage() {
  return <PermissionGuard permission="users.manage"><UsersPageContent /></PermissionGuard>;
}

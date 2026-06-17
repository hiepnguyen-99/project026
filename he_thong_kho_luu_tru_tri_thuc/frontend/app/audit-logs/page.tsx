"use client";

import { ScrollText } from "lucide-react";
import { PermissionGuard } from "@/components/permission-guard";
import { Audit, DashboardData, formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { PageHeader, Panel } from "@/components/ui";

const empty: DashboardData = {
  user: { code:"", name:"", role:"admin", department:"", permissions:[] },
  stats: { documents:0, private:0, topics:0 },
  documents: [],
  requests: [],
  backups: [],
  audit: [],
};

function AuditLogsContent() {
  const { data, error } = useBackendData<DashboardData>("/api/dashboard", empty);
  const audits: Audit[] = data.audit;
  return <div>
    <PageHeader eyebrow="Audit Logs" title="Nhật ký hệ thống" description="Theo dõi hành động quản trị, upload, policy và truy cập trong EduVault."/>
    {error&&<p className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">{error}</p>}
    <div className="app-card mb-5 p-4"><ScrollText className="text-blue-600" size={18}/><strong className="mt-3 block text-xl">{audits.length}</strong><span className="muted text-xs">Sự kiện gần đây</span></div>
    <Panel title="Audit gần đây">
      <div className="table-shell"><table className="data-table"><thead><tr><th>ID</th><th>Actor</th><th>Action</th><th>Resource</th><th>Thời gian</th></tr></thead><tbody>{audits.map(item=><tr key={item.id}><td>{item.id}</td><td>{item.actor_code}</td><td><strong>{item.action}</strong></td><td>{item.resource_type}{item.resource_id?`/${item.resource_id}`:""}</td><td>{formatDate(item.created_at)}</td></tr>)}</tbody></table></div>
    </Panel>
  </div>;
}

export default function AuditLogsPage() {
  return <PermissionGuard permission="audit.view"><AuditLogsContent /></PermissionGuard>;
}

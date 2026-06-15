"use client";

import { useState } from "react";
import { CheckCircle2, Cloud, DatabaseBackup, HardDrive, LoaderCircle, RefreshCw, RotateCcw, ShieldCheck } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { Backup as BackupType, DashboardData, formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { Metric, PageHeader, Panel } from "@/components/ui";

type Compliance = {
  compliant: boolean;
  copies: number;
  media: number;
  offsite: number;
  required: { copies: number; media: number; offsite: number };
  storages: { id: string; name: string; provider: string; last_status: string }[];
};

type CloudConnection = {
  provider: "google_drive" | "onedrive";
  label: string;
  configured: boolean;
  connected: boolean;
  account_email?: string;
  last_sync_at?: string;
  last_error?: string;
};

const emptyDash: DashboardData = {
  user: { code: "", name: "", role: "lecturer", department: "" },
  stats: { documents: 0, private: 0, topics: 0 },
  documents: [],
  requests: [],
  backups: [],
  audit: [],
};
const emptyCompliance: Compliance = {
  compliant: false,
  copies: 0,
  media: 0,
  offsite: 0,
  required: { copies: 3, media: 2, offsite: 1 },
  storages: [],
};

export default function Backup() {
  const { user, request } = useAuth();
  const { data: dash, reload } = useBackendData("/api/dashboard", emptyDash);
  const { data: c, error: complianceError } = useBackendData("/api/backups/compliance", emptyCompliance);
  const { data: connections, error: cloudError, reload: reloadConnections } = useBackendData<CloudConnection[]>("/api/cloud/connections", []);
  const [syncing, setSyncing] = useState("");
  const [message, setMessage] = useState("");
  const canViewCompliance = user?.role === "head" || user?.role === "admin";

  async function create() {
    await request("/api/admin/backups", { method: "POST" });
    await reload();
  }

  async function restore(x: BackupType) {
    if (confirm(`Khôi phục ${x.id}?`)) await request(`/api/admin/backups/${x.id}/restore`, { method: "POST" });
  }

  async function connect(provider: CloudConnection["provider"]) {
    setMessage("");
    const result = await request<{ authorization_url: string }>("/api/cloud/connect", {
      method: "POST",
      body: JSON.stringify({ provider }),
    });
    window.open(result.authorization_url, "_blank", "noopener,noreferrer");
  }

  async function sync(provider: CloudConnection["provider"]) {
    setSyncing(provider);
    setMessage("");
    try {
      const result = await request<{ results: { status: string }[] }>(`/api/cloud/connections/${provider}/sync`, { method: "POST" });
      const succeeded = result.results.filter(item => item.status === "success").length;
      setMessage(`Đã đồng bộ thành công ${succeeded}/${result.results.length} tài liệu.`);
      await reloadConnections();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Không thể đồng bộ kho cloud.");
    } finally {
      setSyncing("");
    }
  }

  return <div>
    <PageHeader eyebrow="Sao lưu và phục hồi" title="Trung tâm sao lưu" description="Theo dõi bản sao hệ thống và đồng bộ tài liệu lên cloud cá nhân." actions={user?.role === "admin" ? <button className="btn-primary" onClick={create}><DatabaseBackup size={15}/>Sao lưu ngay</button> : undefined}/>

    {canViewCompliance ? <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="Bản sao khả dụng" value={String(c.copies)} detail={`Yêu cầu ${c.required.copies}`} icon={<DatabaseBackup size={18}/>}/>
      <Metric label="Loại phương tiện" value={String(c.media)} detail={`Yêu cầu ${c.required.media}`} icon={<HardDrive size={18}/>}/>
      <Metric label="Bản sao ngoài hệ thống" value={String(c.offsite)} detail={`Yêu cầu ${c.required.offsite}`} icon={<Cloud size={18}/>}/>
      <Metric label="Tuân thủ" value={c.compliant ? "Đạt" : "Chưa đạt"} detail="Chiến lược 3-2-1" icon={<ShieldCheck size={18}/>}/>
    </div> : <p className="rounded bg-amber-50 p-3 text-xs text-amber-800">Thống kê tuân thủ 3-2-1 toàn hệ thống chỉ dành cho Trưởng bộ môn và Quản trị viên. Kết nối cloud cá nhân của bạn được hiển thị bên dưới.</p>}

    {canViewCompliance && complianceError && <p className="mt-4 rounded bg-amber-50 p-3 text-xs text-amber-800">{complianceError}</p>}

    <Panel title="Cloud cá nhân" description="Tài liệu do bạn sở hữu sẽ được đồng bộ lên tài khoản cloud đã kết nối." className="mt-5">
      {cloudError && <p className="m-4 rounded bg-amber-50 p-3 text-xs text-amber-800">{cloudError}</p>}
      {message && <p className="m-4 rounded bg-blue-50 p-3 text-xs text-blue-800">{message}</p>}
      <div className="grid gap-3 p-5 sm:grid-cols-2">
        {connections.map(connection => <div key={connection.provider} className="rounded-xl border border-[var(--border)] p-4">
          <div className="flex items-start justify-between gap-3">
            <div><Cloud className="text-blue-600" size={20}/><strong className="mt-3 block text-sm">{connection.label}</strong></div>
            <span className={`badge ${connection.connected ? "badge-green" : "badge-amber"}`}>{connection.connected ? <CheckCircle2 size={11}/> : null}{connection.connected ? "Đã kết nối" : "Chưa kết nối"}</span>
          </div>
          <p className="muted mt-3 text-xs">{connection.account_email || (connection.configured ? "Sẵn sàng kết nối" : "OAuth chưa được cấu hình")}</p>
          <p className="muted mt-1 text-[10px]">Đồng bộ gần nhất: {formatDate(connection.last_sync_at)}</p>
          {connection.last_error && <p className="mt-2 text-[10px] text-red-600">{connection.last_error}</p>}
          <div className="mt-4 flex gap-2">
            {connection.connected ? <button className="btn-primary" disabled={syncing === connection.provider} onClick={() => sync(connection.provider)}>{syncing === connection.provider ? <LoaderCircle className="animate-spin" size={14}/> : <RefreshCw size={14}/>}Đồng bộ ngay</button> : <button className="btn-secondary" disabled={!connection.configured} onClick={() => connect(connection.provider)}>Kết nối</button>}
          </div>
        </div>)}
      </div>
    </Panel>

    {canViewCompliance && <Panel title="Kho lưu trữ hệ thống đang hoạt động" className="mt-5"><div className="grid gap-3 p-5 sm:grid-cols-3">{c.storages.map(x => <div key={x.id} className="rounded-xl border border-[var(--border)] p-4"><Cloud size={20}/><strong className="mt-3 block text-sm">{x.name}</strong><span className="muted text-xs">{x.provider}</span><span className="badge badge-green mt-3"><CheckCircle2 size={11}/>{x.last_status}</span></div>)}</div></Panel>}

    <Panel title="Lịch sử sao lưu hệ thống" className="mt-5"><div className="table-shell"><table className="data-table"><thead><tr><th>Mã backup</th><th>Trạng thái</th><th>Người tạo</th><th>Thời gian</th><th></th></tr></thead><tbody>{dash.backups.map(x => <tr key={x.id}><td><strong>{x.id}</strong></td><td><span className="badge badge-green">{x.status}</span></td><td>{x.created_by}</td><td>{formatDate(x.created_at)}</td><td>{user?.role === "admin" && <button className="btn-secondary" onClick={() => restore(x)}><RotateCcw size={13}/>Khôi phục</button>}</td></tr>)}</tbody></table></div></Panel>
  </div>;
}

"use client";

import { useState } from "react";
import { CheckCircle2, Cloud, DatabaseBackup, HardDrive, LoaderCircle, RefreshCw, RotateCcw, ShieldCheck } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { Backup as BackupType, BackupManifest, DashboardData, formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { Metric, PageHeader, Panel } from "@/components/ui";
import { statusLabel } from "@/src/constants/ui-text";

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
  user: { code: "", name: "", role: "lecturer", department: "", permissions: [] },
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
      const result = await request<{ results: { status: string; detail?: string }[] }>(`/api/cloud/connections/${provider}/sync`, { method: "POST" });
      const succeeded = result.results.filter(item => item.status === "success").length;
      const failed = result.results.length - succeeded;
      const firstError = result.results.find(item => item.status !== "success")?.detail;
      setMessage(failed
        ? `Đồng bộ thành công ${succeeded}/${result.results.length} tài liệu. ${failed} tài liệu lỗi${firstError ? `: ${firstError}` : "."}`
        : `Đã đồng bộ thành công ${succeeded}/${result.results.length} tài liệu.`
      );
      await reloadConnections();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Không thể đồng bộ kho cloud.");
    } finally {
      setSyncing("");
    }
  }

  return <div>
    <PageHeader
      eyebrow="Sao lưu"
      title={canViewCompliance ? "Trung tâm sao lưu" : "Đồng bộ cloud cá nhân"}
      description="Theo dõi dữ liệu được bảo vệ, tệp tài liệu gốc, chỉ mục tìm kiếm nâng cao và kho đối tượng MinIO."
      actions={user?.role === "admin" ? <button className="btn-primary" onClick={create}><DatabaseBackup size={15}/>Sao lưu ngay</button> : undefined}
    />

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
            {connection.connected ? <>
              <button className="btn-primary" disabled={syncing === connection.provider} onClick={() => sync(connection.provider)}>{syncing === connection.provider ? <LoaderCircle className="animate-spin" size={14}/> : <RefreshCw size={14}/>}Đồng bộ ngay</button>
              {connection.last_error && <button className="btn-secondary" disabled={!connection.configured} onClick={() => connect(connection.provider)}>Kết nối lại</button>}
            </> : <button className="btn-secondary" disabled={!connection.configured} onClick={() => connect(connection.provider)}>Kết nối</button>}
          </div>
        </div>)}
      </div>
    </Panel>

    {canViewCompliance && <Panel title="Kho lưu trữ hệ thống đang hoạt động" className="mt-5">
      <div className="grid gap-3 p-5 sm:grid-cols-3">
        {c.storages.map(x => <div key={x.id} className="rounded-xl border border-[var(--border)] p-4">
          <Cloud size={20}/>
          <strong className="mt-3 block text-sm">{x.name}</strong>
          <span className="muted text-xs">{x.provider}</span>
          <span className={`badge ${x.last_status === "success" || x.last_status === "ready" ? "badge-green" : "badge-amber"} mt-3`}>
            {x.last_status === "success" || x.last_status === "ready" ? <CheckCircle2 size={11}/> : null}
            {x.last_status}
          </span>
        </div>)}
      </div>
    </Panel>}

    {canViewCompliance && <Panel title="Các bản sao lưu hệ thống" description="Cho biết dữ liệu nào đang được bảo vệ và thành phần nào cần kiểm tra thêm." className="mt-5">
      <div className="space-y-3 p-5">
        {dash.backups.length === 0 && <p className="muted rounded-lg border border-[var(--border)] p-4 text-sm">Chưa có bản sao lưu hệ thống.</p>}
        {dash.backups.map(x => <BackupExplorerCard key={x.id} backup={x} canRestore={user?.role === "admin"} onRestore={() => restore(x)} />)}
      </div>
    </Panel>}
  </div>;
}

function BackupExplorerCard({ backup, canRestore, onRestore }: { backup: BackupType; canRestore: boolean; onRestore: () => void }) {
  const manifest = backup.manifest && Object.keys(backup.manifest).length > 0 ? backup.manifest : null;
  const qdrantBytes = (manifest?.qdrant?.collections || []).reduce((sum, item) => sum + (item.snapshot_size_bytes || 0), 0);
  const protectedBytes = manifest ? manifest.local_storage_size_bytes + manifest.minio_size_bytes + (manifest.database_snapshot?.size_bytes || 0) + qdrantBytes : 0;
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <strong className="block text-sm">{backup.id}</strong>
          <p className="muted mt-1 text-xs">Tạo bởi {backup.created_by} · {formatDate(backup.created_at)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className={`badge ${backup.status === "success" ? "badge-green" : "badge-amber"}`}>{statusLabel(backup.status)}</span>
          {manifest?.checksum?.entries_count ? <span className="badge badge-blue">Checksum {manifest.checksum.entries_count} tệp</span> : <span className="badge badge-amber">Chưa có checksum</span>}
          {canRestore && <button className="btn-secondary" onClick={onRestore}><RotateCcw size={13}/>Khôi phục</button>}
        </div>
      </div>

      {manifest ? (() => {
        const rawComponents = manifest.included_components || [];
        const components = rawComponents.map(item => {
          if (typeof item === "string") {
            return { key: item, label: item, included: true };
          }
          return item;
        });
        return <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
            <BackupStat label="Tài liệu" value={manifest.documents_count || 0} />
            <BackupStat label="Phiên bản" value={manifest.versions_count || 0} />
            <BackupStat label="Tri thức đã lưu" value={manifest.chunks_count || 0} />
            <BackupStat label="Tệp gốc" value={manifest.file_assets_count || 0} />
            <BackupStat label="Chỉ mục Qdrant" value={manifest.qdrant_vectors_count || 0} />
            <BackupStat label="Đối tượng MinIO" value={manifest.minio_objects_count || 0} />
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr_auto]">
            <ComponentList title="Dữ liệu được bảo vệ" items={components.filter(item => item.included)} />
            <ComponentList title="Cần kiểm tra thêm" items={components.filter(item => !item.included)} muted />
            <div className="rounded-lg border border-[var(--border)] p-3">
              <p className="muted text-[11px] font-bold uppercase tracking-wide">Dung lượng được bảo vệ</p>
              <strong className="mt-1 block text-lg">{formatBytes(protectedBytes)}</strong>
              <p className="muted mt-1 text-xs">{manifest.local_storage_files_count || 0} tệp trong gói sao lưu</p>
            </div>
          </div>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <SampleList title="Ví dụ tài liệu" items={(manifest.sample_documents || []).map(item => `${item.title || ""} · v${item.current_version || 1}`)} />
            <SampleList title="Ví dụ tệp" items={(manifest.sample_files || []).map(item => `${item.original_name || ""} · ${formatBytes(Number(item.size || 0))}`)} />
          </div>
        </>;
      })() : <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">Bản sao lưu này được tạo trước khi có tóm tắt chi tiết. Có thể khôi phục theo cơ chế cũ, nhưng chưa hiển thị được số tài liệu, phiên bản và checksum.</p>}
    </div>
  );
}

function BackupStat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg border border-[var(--border)] p-3"><p className="muted text-[11px] font-bold uppercase tracking-wide">{label}</p><strong className="mt-1 block text-lg">{value}</strong></div>;
}

function ComponentList({ title, items, muted = false }: { title: string; items: BackupManifest["included_components"]; muted?: boolean }) {
  return <div className="rounded-lg border border-[var(--border)] p-3"><p className="muted text-[11px] font-bold uppercase tracking-wide">{title}</p><div className="mt-2 flex flex-wrap gap-2">{items.length ? items.map(item => <span key={item.key} className={`badge ${muted ? "badge-amber" : "badge-green"}`}>{item.label}</span>) : <span className="muted text-xs">Không có.</span>}</div>{items.some(item => item.error) && <p className="mt-2 text-xs text-amber-700">{items.find(item => item.error)?.error}</p>}</div>;
}

function SampleList({ title, items }: { title: string; items: string[] }) {
  return <div className="rounded-lg border border-[var(--border)] p-3"><p className="muted text-[11px] font-bold uppercase tracking-wide">{title}</p>{items.length ? <ul className="mt-2 space-y-1 text-xs">{items.slice(0, 3).map(item => <li key={item} className="truncate">{item}</li>)}</ul> : <p className="muted mt-2 text-xs">Chưa có dữ liệu mẫu.</p>}</div>;
}

function formatBytes(value: number) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(size >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

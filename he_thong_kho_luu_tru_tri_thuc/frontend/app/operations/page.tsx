"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { Activity, AlertTriangle, CheckCircle2, Database, DatabaseBackup, HardDrive, RefreshCw, Server, Workflow } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { useBackendData } from "@/lib/hooks";
import { formatDate } from "@/lib/api";
import { Metric, PageHeader, Panel } from "@/components/ui";

type ServiceStatus = {
  provider: string;
  configured: boolean;
  available: boolean;
  detail?: string;
  collection_prefix?: string;
  vector_count?: number;
};

type Backup = { id: string; status: string; storage_path: string; created_by: string; created_at: string };
type RestoreVerification = { id: string; backup_id: string; status: string; detail: Record<string, unknown>; verified_by: string; verified_at: string };
type AlertItem = { severity: "critical" | "warning"; code: string; title: string; detail: string; source: string };
type RecentEvent = { kind: string; title: string; detail: string; at?: string | null; source: string; severity: "info" | "warning" | "critical" };
type Heartbeat = {
  workflow: string;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  failure_count: number;
  updated_at?: string | null;
  last_detail: Record<string, unknown>;
  last_status: "success" | "error" | "offline";
  last_heartbeat_at?: string | null;
  age_seconds?: number | null;
  health: "healthy" | "warning" | "offline";
};
type OperationsStatus = {
  api: { status: string };
  database: { provider: string; available: boolean };
  qdrant: ServiceStatus;
  object_storage: ServiceStatus;
  queue: ServiceStatus;
  ready: boolean;
  last_backup: Backup | null;
  last_restore_verification: RestoreVerification | null;
  n8n: Record<string, Heartbeat>;
  qdrant_fallback: { count_last_hour: number; threshold_per_hour: number; warning: boolean };
  alerts: {
    critical: AlertItem[];
    warnings: AlertItem[];
    recent_events: RecentEvent[];
  };
  storage: {
    storage_used_bytes: number;
    documents_count: number;
    versions_count: number;
    chunks_count: number;
    object_refs_count: number;
    file_assets_count: number;
  };
};

const emptyStatus: OperationsStatus = {
  api: { status: "unknown" },
  database: { provider: "", available: false },
  qdrant: { provider: "", configured: false, available: false },
  object_storage: { provider: "", configured: false, available: false },
  queue: { provider: "", configured: false, available: false },
  ready: false,
  last_backup: null,
  last_restore_verification: null,
  n8n: {},
  qdrant_fallback: { count_last_hour: 0, threshold_per_hour: 0, warning: false },
  alerts: { critical: [], warnings: [], recent_events: [] },
  storage: { storage_used_bytes: 0, documents_count: 0, versions_count: 0, chunks_count: 0, object_refs_count: 0, file_assets_count: 0 },
};

function isWorkflowNotification(source: string) {
  return source === "automation_heartbeats";
}

export default function OperationsPage() {
  const { request } = useAuth();
  const { data, error, loading, reload } = useBackendData<OperationsStatus>("/api/operations/status", emptyStatus);
  const [verifying, setVerifying] = useState(false);
  const [message, setMessage] = useState("");
  const backupAge = backupAgeHours(data.last_backup?.created_at);
  const visibleWarnings = data.alerts.warnings.filter(item => !isWorkflowNotification(item.source));
  const visibleRecentEvents = data.alerts.recent_events.filter(item => !isWorkflowNotification(item.source));

  async function verifyRestore() {
    if (!data.last_backup) return;
    setVerifying(true);
    setMessage("");
    try {
      const result = await request<RestoreVerification>(`/api/operations/backups/${data.last_backup.id}/verify`, { method: "POST" });
      setMessage(`Đã kiểm tra khôi phục ${restoreStatusLabel(result.status)} cho bản sao lưu ${result.backup_id}.`);
      await reload();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Kiểm tra khôi phục thất bại.");
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Vận hành"
        title="Bảng trạng thái vận hành"
        description="Theo dõi hạ tầng chạy thử, sao lưu, kiểm tra khôi phục, luồng tự động và dung lượng lưu trữ."
        actions={<button className="btn-secondary" onClick={reload}><RefreshCw size={15}/>Làm mới</button>}
      />

      {(error || message) && <p className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">{message || error}</p>}

      {data.alerts.critical.length > 0 && (
        <Panel title="Canh bao nghiem trong" description="Can xu ly ngay de tranh anh huong he thong." className="mb-5">
          <div className="grid gap-3 p-4 lg:grid-cols-2">
            {data.alerts.critical.map(item => <AlertCard key={item.code} item={item} />)}
          </div>
        </Panel>
      )}

      {visibleWarnings.length > 0 && (
        <Panel title="Canh bao can theo doi" description="Nhung diem can xu ly som de tranh anh huong van hanh." className="mb-5">
          <div className="grid gap-3 p-4 lg:grid-cols-2">
            {visibleWarnings.map(item => <AlertCard key={item.code} item={item} />)}
          </div>
        </Panel>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatusMetric label="Sức khỏe API" value={loading ? "..." : apiStatusLabel(data.api.status)} detail={data.ready ? "Hạ tầng đã sẵn sàng" : "Có dịch vụ cần kiểm tra"} icon={<Server size={18}/>} tone={data.ready ? "green" : "yellow"}/>
        <StatusMetric label="Sức khỏe cơ sở dữ liệu" value={data.database.available ? "ĐANG CHẠY" : "NGỪNG"} detail={data.database.provider || "Chưa xác định"} icon={<Database size={18}/>} tone={data.database.available ? "green" : "red"}/>
        <StatusMetric label="Trạng thái Qdrant" value={serviceState(data.qdrant)} detail={serviceDetail(data.qdrant)} icon={<Activity size={18}/>} tone={serviceTone(data.qdrant)}/>
        <StatusMetric label="Kho đối tượng" value={serviceState(data.object_storage)} detail={serviceDetail(data.object_storage)} icon={<HardDrive size={18}/>} tone={serviceTone(data.object_storage)}/>
        <StatusMetric label="Sao lưu gần nhất" value={data.last_backup ? formatAgeHours(backupAge) : "CHƯA CÓ"} detail={data.last_backup ? formatDate(data.last_backup.created_at) : "Chưa có bản sao lưu"} icon={<DatabaseBackup size={18}/>} tone={backupTone(data.last_backup?.created_at)}/>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Số tài liệu" value={String(data.storage.documents_count)} detail={`${data.storage.file_assets_count} tệp gốc`} icon={<Database size={18}/>}/>
        <Metric label="Số đoạn dữ liệu" value={String(data.storage.chunks_count)} detail="Đơn vị truy xuất đã lập chỉ mục" icon={<Activity size={18}/>}/>
        <Metric label="Số phiên bản" value={String(data.storage.versions_count)} detail="Phiên bản tài liệu đã lưu" icon={<DatabaseBackup size={18}/>}/>
        <Metric label="Dung lượng đã dùng" value={formatBytes(data.storage.storage_used_bytes)} detail={`${data.storage.object_refs_count} tham chiếu đối tượng`} icon={<HardDrive size={18}/>}/>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Panel title="Dịch vụ chạy nền">
          <div className="space-y-3 p-4">
            <ServiceRow label="Cơ sở dữ liệu" status={{ provider: data.database.provider, configured: true, available: data.database.available }}/>
            <ServiceRow label="Qdrant" status={data.qdrant}/>
            <ServiceRow label="Kho đối tượng" status={data.object_storage}/>
            <ServiceRow label="Hàng đợi" status={data.queue}/>
          </div>
        </Panel>

        <Panel
          title="Kiểm tra khôi phục"
          action={<button className="btn-secondary" disabled={!data.last_backup || verifying} onClick={verifyRestore}><DatabaseBackup size={14}/>{verifying ? "Đang kiểm tra" : "Kiểm tra khôi phục"}</button>}
        >
          <div className="space-y-3 p-4 text-sm">
            <Info label="Bản sao lưu gần nhất" value={data.last_backup ? `${data.last_backup.id} - ${formatDate(data.last_backup.created_at)}` : "Chưa có bản sao lưu"}/>
            <Info label="Lần kiểm tra khôi phục gần nhất" value={data.last_restore_verification ? `${restoreStatusLabel(data.last_restore_verification.status)} - ${formatDate(data.last_restore_verification.verified_at)}` : "Chưa kiểm tra"}/>
            <Info label="Người kiểm tra" value={data.last_restore_verification?.verified_by || "Chưa có dữ liệu"}/>
          </div>
        </Panel>
      </div>

      <Panel title="Nhịp hoạt động n8n" className="mt-5">
        <div className="grid gap-3 p-4 md:grid-cols-2">
          {Object.values(data.n8n).map(item => {
            const eventStatus = heartbeatEventStatus(item);
            return (
            <div key={item.workflow} className={`rounded-lg border p-4 ${heartbeatBorder(eventStatus)}`}>
              <div className="flex items-center justify-between gap-3">
                <strong className="text-sm">{labelWorkflow(item.workflow)}</strong>
                <span className={`badge ${heartbeatBadge(eventStatus)}`}>
                  <Workflow size={12}/>{heartbeatLabel(eventStatus)}
                </span>
              </div>
              <p className="muted mt-3 text-xs">Mã luồng: {item.workflow}</p>
              <p className="muted mt-1 text-xs">Kết quả gần nhất: {lastStatusLabel(item.last_status)}</p>
              <p className="muted mt-1 text-xs">Nhịp gần nhất: {formatDate(item.last_heartbeat_at || undefined)}</p>
              <p className="muted mt-1 text-xs">Đã qua: {formatAge(item.age_seconds)}</p>
              <p className="muted mt-1 text-xs">Số lần lỗi: {item.failure_count}</p>
            </div>
          );})}
        </div>
      </Panel>

      <Panel title="Sự kiện gần đây" description="Tổng hợp sự kiện sao lưu, khôi phục, tín hiệu hoạt động và dự phòng mới nhất." className="mt-5">
        <div className="space-y-3 p-4">
          {visibleRecentEvents.length === 0 ? (
            <p className="muted text-xs">Chưa có sự kiện vận hành nào để hiển thị.</p>
          ) : (
            visibleRecentEvents.map(item => (
              <div key={`${item.kind}-${item.source}-${item.at || "empty"}`} className={`rounded-lg border p-3 ${eventBorder(item.severity)}`}>
                <div className="flex items-center justify-between gap-3">
                  <strong className="text-sm">{eventTitle(item.title)}</strong>
                  <span className={`badge ${eventBadge(item.severity)}`}>{eventLabel(item.severity)}</span>
                </div>
                <p className="muted mt-2 text-xs">{eventDetail(item.detail)}</p>
                <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-[var(--muted)]">
                  <span>{eventSource(item.source)}</span>
                  <span>{formatDate(item.at || undefined)}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}

function StatusMetric({ label, value, detail, icon, tone }: { label: string; value: string; detail: string; icon: ReactNode; tone: "green" | "yellow" | "red" }) {
  return (
    <div className={`app-card p-4 ${toneBorder(tone)}`}>
      <div className="flex items-center justify-between gap-3">
        <span className={`badge ${toneBadge(tone)}`}>{icon}{toneLabel(tone)}</span>
      </div>
      <p className="muted mt-4 text-[11px] font-bold uppercase tracking-wide">{label}</p>
      <strong className="mt-1 block text-xl">{value}</strong>
      <p className="muted mt-1 truncate text-xs" title={detail}>{detail}</p>
    </div>
  );
}

function AlertCard({ item }: { item: AlertItem }) {
  const tone = item.severity === "critical" ? "red" : "yellow";
  return (
    <div className={`rounded-lg border p-4 ${tone === "red" ? "border-red-200 bg-red-50 text-red-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
      <div className="flex items-center gap-2 text-sm font-bold"><AlertTriangle size={16}/>{item.title}</div>
      <p className="mt-2 text-xs leading-5">{item.detail}</p>
      <p className="mt-2 text-[11px] opacity-80">Nguon: {item.source}</p>
    </div>
  );
}

function ServiceRow({ label, status }: { label: string; status: ServiceStatus }) {
  const tone = serviceTone(status);
  return (
    <div className={`flex items-center justify-between gap-3 rounded-lg border p-3 ${toneBorder(tone)}`}>
      <div>
        <strong className="text-sm">{label}</strong>
        <p className="muted mt-1 text-xs">{status.provider || "Chưa xác định"}{status.collection_prefix ? ` - ${status.collection_prefix}` : ""}</p>
        {status.detail && <p className="mt-1 text-xs text-red-600">{status.detail}</p>}
      </div>
      <span className={`badge ${toneBadge(tone)}`}>{status.available ? <CheckCircle2 size={12}/> : <Activity size={12}/>}{toneLabel(tone)}</span>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-3 rounded-lg bg-[var(--soft)] px-3 py-2"><span className="muted text-xs">{label}</span><strong className="text-xs">{value}</strong></div>;
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

function labelWorkflow(value: string) {
  if (value === "policy_activation") return "Kích hoạt chính sách";
  if (value === "lecturer_assignment") return "Phân công giảng viên";
  return value;
}

type HeartbeatEventStatus = "recent" | "stale" | "empty";

function heartbeatEventStatus(item: Heartbeat): HeartbeatEventStatus {
  if (!item.last_heartbeat_at || item.age_seconds === null || item.age_seconds === undefined) return "empty";
  return item.age_seconds <= 15 * 60 ? "recent" : "stale";
}

function heartbeatBadge(value: HeartbeatEventStatus) {
  if (value === "recent") return "badge-green";
  if (value === "stale") return "badge-amber";
  return "badge-amber";
}

function heartbeatLabel(value: HeartbeatEventStatus) {
  if (value === "recent") return "Hoạt động gần đây";
  if (value === "stale") return "Đã lâu chưa chạy";
  return "Chưa có dữ liệu";
}

function formatAge(value?: number | null) {
  if (value === null || value === undefined) return "Chưa có dữ liệu";
  if (value < 60) return `${value} giây`;
  const minutes = Math.floor(value / 60);
  if (minutes < 60) return `${minutes} phút`;
  return `${Math.floor(minutes / 60)} giờ ${minutes % 60} phút`;
}

function serviceTone(status: ServiceStatus): "green" | "yellow" | "red" {
  if (status.available) return "green";
  return status.configured ? "red" : "yellow";
}

function serviceState(status: ServiceStatus) {
  if (status.available) return "ĐANG CHẠY";
  return status.configured ? "LỖI" : "CHƯA CẤU HÌNH";
}

function serviceDetail(status: ServiceStatus) {
  if (status.vector_count !== undefined) return `${status.provider || "Chưa xác định"} - ${status.vector_count} véc-tơ`;
  return status.detail || status.provider || "Chưa xác định";
}

function backupAgeHours(value?: string) {
  if (!value) return null;
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return null;
  return Math.max(0, (Date.now() - time) / 36e5);
}

function backupTone(value?: string): "green" | "yellow" | "red" {
  const age = backupAgeHours(value);
  if (age === null) return "red";
  return age > 24 ? "yellow" : "green";
}

function formatAgeHours(value: number | null) {
  if (value === null) return "Chưa rõ";
  if (value < 1) return `${Math.round(value * 60)} phút trước`;
  return `${Math.floor(value)} giờ trước`;
}

function toneBadge(value: "green" | "yellow" | "red") {
  if (value === "green") return "badge-green";
  if (value === "yellow") return "badge-amber";
  return "badge-red";
}

function toneBorder(value: "green" | "yellow" | "red") {
  if (value === "green") return "border-green-200";
  if (value === "yellow") return "border-amber-200";
  return "border-red-200";
}

function toneLabel(value: "green" | "yellow" | "red") {
  if (value === "green") return "ỔN ĐỊNH";
  if (value === "yellow") return "CẦN THEO DÕI";
  return "CẦN XỬ LÝ";
}

function heartbeatBorder(value: HeartbeatEventStatus) {
  if (value === "recent") return "border-green-200";
  return "border-amber-200";
}

function eventBadge(value: RecentEvent["severity"]) {
  if (value === "critical") return "badge-red";
  if (value === "warning") return "badge-amber";
  return "badge-green";
}

function eventBorder(value: RecentEvent["severity"]) {
  if (value === "critical") return "border-red-200";
  if (value === "warning") return "border-amber-200";
  return "border-green-200";
}

function eventLabel(value: RecentEvent["severity"]) {
  if (value === "critical") return "Nghiêm trọng";
  if (value === "warning") return "Cần theo dõi";
  return "Thông tin";
}

function eventTitle(value: string) {
  const normalized = value.trim().toLowerCase();
  const labels: Record<string, string> = {
    "restore verification": "Kiểm tra khôi phục",
    "backup freshness": "Độ mới bản sao lưu",
    "backup is older than 24 hours": "Bản sao lưu đã quá 24 giờ",
    "lecturer_assignment offline": "Phân công giảng viên đã lâu chưa chạy",
    "policy_activation offline": "Kích hoạt chính sách đã lâu chưa chạy",
  };
  return labels[normalized] || value;
}

function eventDetail(value: string) {
  return value
    .replaceAll("Backup", "Bản sao lưu")
    .replaceAll("backup", "bản sao lưu")
    .replaceAll("Restore verification", "Kiểm tra khôi phục")
    .replaceAll("restore verification", "kiểm tra khôi phục")
    .replaceAll("Workflow", "Quy trình tự động")
    .replaceAll("workflow", "quy trình tự động")
    .replaceAll("offline", "đã lâu chưa chạy")
    .replaceAll("success", "thành công")
    .replaceAll("failed", "thất bại");
}

function eventSource(value: string) {
  const labels: Record<string, string> = {
    backup_logs: "Nhật ký sao lưu",
    automation_heartbeats: "Tín hiệu tự động hóa",
    ops_restore_verifications: "Kiểm tra khôi phục",
  };
  return labels[value] || value;
}

function apiStatusLabel(value: string) {
  return value.toLowerCase() === "ok" ? "ỔN ĐỊNH" : value.toUpperCase();
}

function lastStatusLabel(value: Heartbeat["last_status"]) {
  if (value === "success") return "Thành công";
  if (value === "error") return "Lỗi";
  return "Chưa có dữ liệu";
}

function restoreStatusLabel(value: string) {
  if (value === "verified") return "đã xác minh";
  if (value === "success") return "thành công";
  if (value === "failed") return "thất bại";
  return value;
}

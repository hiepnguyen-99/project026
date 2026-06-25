"use client";

import { useState } from "react";
import { CheckCircle2, Clock3, FileText, LoaderCircle, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { EmptyState, PageHeader, Panel } from "@/components/ui";
import { formatDate } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { useBackendData } from "@/lib/hooks";

type GovernanceRule = {
  id: string;
  rule_type: string;
  rule_name: string;
  status: string;
  created_by?: string;
  created_at?: string;
  applied_at?: string | null;
  expired_at?: string | null;
  affected_documents?: number;
  affected_users?: number;
  permissions_created?: number;
  permissions_revoked?: number;
  release_at?: string | null;
  target_groups?: string[];
};

type GovernanceRulesResponse = {
  items: GovernanceRule[];
};

type TimelineItem = {
  event: string;
  action?: string;
  actor?: string | null;
  at?: string | null;
  detail?: Record<string, unknown>;
};

type RuleDetail = {
  rule: GovernanceRule;
  content: Record<string, unknown>;
  timeline: TimelineItem[];
  traceability: {
    permissions_generated: Array<Record<string, unknown>>;
    affected_users: string[];
    affected_documents: string[];
  };
  impact: {
    documents_affected?: number;
    users_affected?: number;
    permissions_created?: number;
    permissions_revoked?: number;
  };
  audit_history: Array<Record<string, unknown>>;
  confirmations: Array<Record<string, unknown>>;
};

const emptyRules: GovernanceRulesResponse = { items: [] };

export default function GovernanceRulesPage() {
  const { request } = useAuth();
  const { data, loading, error, reload } = useBackendData<GovernanceRulesResponse>("/api/governance-rules", emptyRules);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<RuleDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  async function selectRule(rule: GovernanceRule) {
    setSelectedId(rule.id);
    setDetail(null);
    setDetailError("");
    setDetailLoading(true);
    try {
      setDetail(await request<RuleDetail>(`/api/governance-rules/${rule.id}`));
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "Không thể tải chi tiết quy tắc quản trị.");
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Quản trị tri thức"
        title="Quy tắc quản trị"
        description="Theo dõi các quy tắc policy đã được ghi nhận, trạng thái áp dụng và tác động tới tài liệu/người dùng."
        actions={<button className="btn-secondary" onClick={reload} disabled={loading}><RefreshCw size={15} />Làm mới</button>}
      />

      {error && <p className="mb-4 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}

      <div className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
        <Panel title="Danh sách quy tắc quản trị" description={loading ? "Đang tải quy tắc..." : `${data.items.length} quy tắc`}>
          {data.items.length ? (
            <div className="table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Tên quy tắc</th>
                    <th>Loại quy tắc</th>
                    <th>Trạng thái</th>
                    <th>Mô tả</th>
                    <th>Ngày tạo/cập nhật</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map(rule => (
                    <tr key={rule.id} className={selectedId === rule.id ? "bg-[var(--soft)]" : ""}>
                      <td>
                        <button className="text-left font-bold hover:text-blue-600" onClick={() => selectRule(rule)}>
                          {rule.rule_name}
                        </button>
                        <span className="muted block text-[10px]">{rule.id}</span>
                      </td>
                      <td>{ruleTypeLabel(rule.rule_type)}</td>
                      <td><StatusBadge status={rule.status} /></td>
                      <td>{descriptionFor(rule)}</td>
                      <td>{formatRuleDate(rule)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="Chưa có quy tắc quản trị." description="Backend chưa trả về quy tắc quản trị nào trong phạm vi quyền của bạn." />
          )}
        </Panel>

        <Panel title="Chi tiết quy tắc" description="Chọn một quy tắc để xem traceability, impact và timeline.">
          <div className="p-5">
            {detailLoading && <p className="rounded-lg bg-blue-50 p-3 text-xs text-blue-800"><LoaderCircle className="mr-2 inline animate-spin" size={14} />Đang tải chi tiết...</p>}
            {detailError && <p className="rounded-lg bg-red-50 p-3 text-xs text-red-700">{detailError}</p>}
            {!detailLoading && !detail && !detailError && <EmptyState title="Chưa chọn quy tắc" description="Nhấn vào tên quy tắc ở bảng bên trái để xem chi tiết." />}
            {detail && <RuleDetailView detail={detail} />}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function RuleDetailView({ detail }: { detail: RuleDetail }) {
  const rule = detail.rule;
  return (
    <div className="space-y-5">
      <div>
        <p className="eyebrow">Quy tắc quản trị</p>
        <h2 className="mt-1 text-lg font-bold">{rule.rule_name}</h2>
        <p className="muted mt-1 text-xs">{descriptionFor(rule)}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <MetricBox icon={<FileText size={16} />} label="Tài liệu ảnh hưởng" value={String(rule.affected_documents ?? detail.impact.documents_affected ?? 0)} />
        <MetricBox icon={<Users size={16} />} label="Người dùng ảnh hưởng" value={String(rule.affected_users ?? detail.impact.users_affected ?? 0)} />
        <MetricBox icon={<CheckCircle2 size={16} />} label="Quyền được tạo" value={String(rule.permissions_created ?? detail.impact.permissions_created ?? 0)} />
        <MetricBox icon={<ShieldCheck size={16} />} label="Quyền thu hồi" value={String(rule.permissions_revoked ?? detail.impact.permissions_revoked ?? 0)} />
      </div>

      <section>
        <h3 className="section-title mb-2">Nội dung quy tắc</h3>
        <pre className="max-h-64 overflow-auto rounded-lg bg-[var(--soft)] p-3 text-[11px]">{JSON.stringify(detail.content, null, 2)}</pre>
      </section>

      <section>
        <h3 className="section-title mb-2">Traceability</h3>
        <div className="grid gap-2 text-xs">
          <InfoRow label="Tài liệu liên quan" value={detail.traceability.affected_documents.length ? detail.traceability.affected_documents.join(", ") : "Chưa có dữ liệu"} />
          <InfoRow label="Người dùng liên quan" value={detail.traceability.affected_users.length ? detail.traceability.affected_users.join(", ") : "Chưa có dữ liệu"} />
          <InfoRow label="Quyền phát sinh" value={`${detail.traceability.permissions_generated.length}`} />
        </div>
      </section>

      <section>
        <h3 className="section-title mb-2">Timeline</h3>
        <div className="space-y-2">
          {detail.timeline.map((item, index) => (
            <div key={`${item.event}-${item.at || index}`} className="rounded-lg border border-[var(--border)] p-3 text-xs">
              <div className="flex items-center gap-2">
                <Clock3 size={14} className="text-blue-600" />
                <strong>{eventLabel(item.event)}</strong>
                <span className="muted ml-auto">{item.at ? formatDate(item.at) : "Chưa có thời gian"}</span>
              </div>
              {item.action && <p className="muted mt-1">{item.action}</p>}
            </div>
          ))}
          {!detail.timeline.length && <p className="muted text-xs">Chưa có timeline.</p>}
        </div>
      </section>
    </div>
  );
}

function MetricBox({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <div className="flex items-center gap-2 text-blue-600">{icon}<span className="muted text-[10px] font-bold uppercase">{label}</span></div>
      <strong className="mt-2 block text-lg">{value}</strong>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md bg-[var(--soft)] p-3"><span className="muted block text-[10px] font-bold uppercase">{label}</span><strong className="mt-1 block break-words">{value}</strong></div>;
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === "active" || status === "applied" ? "badge-green" : status === "expired" ? "badge-amber" : "badge-blue";
  return <span className={`badge ${cls}`}>{statusLabel(status)}</span>;
}

function descriptionFor(rule: GovernanceRule) {
  const parts = [
    rule.target_groups?.length ? `Nhóm áp dụng: ${rule.target_groups.join(", ")}` : "",
    rule.release_at ? `Thời điểm mở quyền: ${formatDate(rule.release_at)}` : "",
    `${rule.affected_documents ?? 0} tài liệu`,
    `${rule.affected_users ?? 0} người dùng`,
  ].filter(Boolean);
  return parts.join(" · ");
}

function formatRuleDate(rule: GovernanceRule) {
  const value = rule.applied_at || rule.expired_at || rule.created_at;
  return value ? formatDate(value) : "Chưa có dữ liệu";
}

function ruleTypeLabel(value: string) {
  const labels: Record<string, string> = {
    permission_rule: "Quy tắc phân quyền",
    time_based_permission: "Phân quyền theo thời gian",
    storage_rule: "Quy tắc lưu trữ",
    retention_rule: "Quy tắc lưu giữ",
  };
  return labels[value] || value;
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    active: "Đang áp dụng",
    applied: "Đã áp dụng",
    pending: "Đang chờ",
    expired: "Đã hết hiệu lực",
    draft: "Bản nháp",
  };
  return labels[value] || value;
}

function eventLabel(value: string) {
  const labels: Record<string, string> = {
    Created: "Đã tạo",
    Applied: "Đã áp dụng",
    Expired: "Đã hết hiệu lực",
    Confirmed: "Đã xác nhận",
  };
  return labels[value] || value;
}

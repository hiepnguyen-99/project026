"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  FileUp,
  Folder,
  FolderOpen,
  History,
  LoaderCircle,
  RefreshCw,
  Search,
  Send,
  Shield,
  Trash2,
  UploadCloud,
  UserCheck,
  Users,
} from "lucide-react";
import { PermissionGuard } from "@/components/permission-guard";
import { PageHeader, Panel } from "@/components/ui";
import { useAuth } from "@/components/auth-provider";
import { useBackendData } from "@/lib/hooks";
import { FolderNode, PolicyFile, User, formatDate } from "@/lib/api";

type GovernanceTab = "assistant" | "import" | "tree" | "assignment" | "audit";
type MasterTree = { policy: PolicyFile | null; tree: FolderNode | null; message?: string };
type PolicyAudit = { id: string; actor: string; action: string; status: string; created_at: string };
type PolicyRequest = { id: string; actor: string; message: string; action_json: Record<string, unknown>; status: string; created_at: string; applied_at?: string };
type Assignment = {
  id: string;
  batch_id: string;
  lecturer_code: string;
  lecturer_name?: string;
  lecturer_name_snapshot?: string;
  specialization_id: string;
  specialization_code_snapshot?: string;
  specialization_name?: string;
  specialization_name_snapshot?: string;
  source: string;
  status: string;
  created_at: string;
  updated_at: string;
};
type AssignmentList = { items: Assignment[] };
type AssignmentPreviewRow = {
  row: number;
  lecturer_code: string;
  lecturer_name: string;
  specialization_input: string;
  specialization_id: string | null;
  specialization_code: string;
  specialization_name: string;
  status: "valid" | "error";
  errors: string[];
  warnings: string[];
};
type AssignmentPreview = {
  status: "validated" | "has_errors";
  batch_preview_id: string;
  summary: { total_rows: number; valid_rows: number; error_rows: number; warning_rows: number };
  assignments: AssignmentPreviewRow[];
  errors: Array<{ row: number; lecturer_code: string; message: string }>;
  warnings: Array<{ row: number; message: string }>;
};
type ActivationSpecialization = { key?: string; code?: string; name?: string; name_en?: string; courses_count?: number };
type ActivationPreview = {
  policy_id: string;
  policy_title: string;
  current_policy_id?: string | null;
  current_policy_title?: string | null;
  status: string;
  tree_impact: {
    added_specializations: ActivationSpecialization[];
    removed_specializations: ActivationSpecialization[];
    matched_specializations: Array<{ old: ActivationSpecialization; new: ActivationSpecialization }>;
    summary: { added: number; removed: number; matched: number };
  };
  assignment_impact: {
    valid_assignments: number;
    needs_resolution_assignments: number;
    valid: Array<Record<string, string>>;
    requires_admin_resolution: Array<Record<string, string>>;
  };
  virtual_tree_impact: { virtual_trees_to_rebuild: number; affected_lecturers: string[] };
  folder_permission_impact: { active_permissions_to_deprecate: number; will_rebuild_permissions: boolean };
};
type PolicyAssistantAction = {
  action: string;
  node?: string;
  parent?: string;
  new_parent?: string;
  new_name?: string;
  lecturer_code?: string;
  lecturer_name?: string;
  specialization_name?: string;
  specialization_code?: string;
  confirm_blocked_reason?: string | null;
  document_type?: string;
  visibility?: string;
  roles?: string[];
  [key: string]: unknown;
};
type PolicyAssistantPreview = {
  status: "preview" | "need_clarification";
  message?: string;
  action?: PolicyAssistantAction;
  preview?: {
    summary?: string;
    before?: Record<string, unknown>;
    after?: Record<string, unknown>;
    impact?: AssignmentAgentImpact | TimeBasedPermissionImpact | GovernanceAdvisorImpact;
    assignment_preview?: AssignmentPreview | null;
    requires_confirmation?: boolean;
    confirm_blocked_reason?: string | null;
    route?: string;
  };
};
type PolicyAssistantConfirmResult = {
  id: string;
  status: string;
  n8n?: { status?: string; reason?: string; message?: string };
  applied?: { status: string; audit_log_id: string; action: PolicyAssistantAction };
};

const emptyMaster: MasterTree = { policy: null, tree: null };
type ImpactSpec = { id?: string; name: string; code?: string };
type AssignmentAgentImpact = {
  lecturer: { code: string; name: string; role: string };
  current_specializations: ImpactSpec[];
  target_specializations: ImpactSpec[];
  assignment_impact: {
    added_specializations: ImpactSpec[];
    removed_specializations: ImpactSpec[];
    unchanged_specializations: ImpactSpec[];
  };
  virtual_tree_impact: { rebuild: boolean; affected_nodes: number };
  folder_permission_impact: { permissions_to_revoke: number; permissions_to_grant: number };
  risk_warnings: string[];
};
type TimeBasedPermissionImpact = {
  rule_id: string;
  rule_type: string;
  document_type: string;
  course: string;
  target_specializations: ImpactSpec[];
  release_at: string;
  before_permission: string;
  after_permission: string;
  permission_impact: { documents_to_open: number; target_lecturers: number; access_grants_to_create: number };
  risk_warnings: string[];
};
type AdvisorAction = {
  priority?: string;
  category?: string;
  title?: string;
  reason?: string;
  recommended_actions?: string[];
  scope?: Record<string, unknown>;
};
type AdvisorRiskArea = {
  specialization_name?: string;
  scope_name?: string;
  knowledge_risk?: string;
  risk?: string;
  document_coverage_percent?: number;
  assigned_lecturer_count?: number;
  reason?: string;
};
type AdvisorCourseGap = {
  course_name?: string;
  specialization_name?: string;
  coverage_percent?: number;
  missing_types?: string[];
};
type AdvisorDependencyWarning = {
  lecturer_code?: string;
  specialization_name?: string;
  dependency_risk?: string;
  owned_document_count?: number;
  owner_concentration_percent?: number;
};
type GovernanceAdvisorImpact = {
  risk_summary: Record<string, unknown>;
  governance_score: number;
  high_risk_areas: AdvisorRiskArea[];
  recommended_actions: AdvisorAction[];
  dependency_warnings: AdvisorDependencyWarning[];
  course_gaps: AdvisorCourseGap[];
  source: Record<string, boolean>;
};
const assistantExamples = [
  "Chuyen GV001 sang IoT",
  "Gan GV002 phu trach Data Science",
  "Bo GV001 khoi AI",
  "De thi Toan chi duoc mo cho AI, Data Science, IoT vao 08:00 ngay 10/09/2026",
  "Hien tai khoa co rui ro gi?",
  "Nhung viec nao nen lam tiep?",
  "Chuyen nganh nao dang thieu tri thuc?",
  "Them AI Agent thuoc AI",
  "Them hoc phan Data Engineering vao Data Science",
  "De thi chi truong bo mon duoc xem",
];

export default function PolicyPage() {
  return <PermissionGuard permission="policy.manage"><KnowledgeGovernanceCenter /></PermissionGuard>;
}

function KnowledgeGovernanceCenter() {
  const { user } = useAuth();
  const { data: masterTree, reload: reloadMaster } = useBackendData<MasterTree>("/api/admin/master-tree", emptyMaster);
  const { data: policyFiles, reload: reloadPolicies } = useBackendData<PolicyFile[]>("/api/policies", []);
  const { data: audits, reload: reloadAudits } = useBackendData<PolicyAudit[]>("/api/policy-assistant/audit", []);
  const { data: requests, reload: reloadRequests } = useBackendData<PolicyRequest[]>("/api/policy-assistant/requests", []);
  const { data: assignments, reload: reloadAssignments } = useBackendData<AssignmentList>("/api/lecturer-assignments", { items: [] });
  const { data: users, reload: reloadUsers } = useBackendData<User[]>(user?.role === "admin" ? "/api/admin/users" : "/api/specializations", []);
  const [activeTab, setActiveTab] = useState<GovernanceTab>("assistant");

  const tabs = useMemo<GovernanceTab[]>(() => {
    if (user?.role === "admin") return ["assistant", "import", "tree", "assignment", "audit"];
    return ["assistant", "tree", "assignment", "audit"];
  }, [user?.role]);

  async function refreshAll() {
    await Promise.all([reloadMaster(), reloadPolicies(), reloadAudits(), reloadRequests(), reloadAssignments(), reloadUsers()]);
  }

  return (
    <div>
      <PageHeader
        eyebrow="Quản trị tri thức"
        title="Knowledge Governance Center"
        description="Điều phối policy, cây tri thức, phân công giảng viên và nhật ký governance của khoa CNTT."
        actions={<button className="btn-secondary" onClick={refreshAll}><RefreshCw size={15}/>Làm mới</button>}
      />

      <OverviewCards masterTree={masterTree} policyFiles={policyFiles} assignments={assignments.items} audits={audits} users={user?.role === "admin" ? users : []} />

      <div className="mb-5 mt-5 flex flex-wrap gap-2 border-b border-[var(--border)] pb-3">
        {tabs.map(tab => (
          <button
            key={tab}
            className={`inline-flex h-10 items-center gap-2 rounded-lg border px-3 text-xs font-bold transition ${activeTab === tab ? "border-blue-500 bg-blue-50 text-blue-700" : "border-[var(--border)] bg-[var(--card)] text-[var(--muted)] hover:bg-[var(--soft)]"}`}
            onClick={() => setActiveTab(tab)}
          >
            {tabIcon(tab)}
            {tabLabel(tab)}
          </button>
        ))}
      </div>

      {activeTab === "assistant" && <AIGovernanceAssistantTab reloadAll={refreshAll} />}
      {activeTab === "import" && user?.role === "admin" && <ImportPolicyTab policyFiles={policyFiles} reloadAll={refreshAll} />}
      {activeTab === "tree" && <KnowledgeTreeTab masterTree={masterTree} />}
      {activeTab === "assignment" && <LecturerAssignmentTab assignments={assignments.items} users={user?.role === "admin" ? users : []} canSeeUsers={user?.role === "admin"} reloadAll={refreshAll} />}
      {activeTab === "audit" && <AuditLogTab audits={audits} requests={requests} assignments={assignments.items} reloadAll={refreshAll} />}
    </div>
  );
}

function OverviewCards({ masterTree, policyFiles, assignments, audits, users }: { masterTree: MasterTree; policyFiles: PolicyFile[]; assignments: Assignment[]; audits: PolicyAudit[]; users: User[] }) {
  const activePolicy = policyFiles.find(policy => policy.status === "active") || masterTree.policy;
  const activeAssignments = assignments.filter(item => item.status === "active");
  const lecturerUsers = users.filter(item => item.role === "lecturer" || item.role === "new_lecturer");
  const assignedCodes = new Set(activeAssignments.map(item => item.lecturer_code));
  const unassigned = lecturerUsers.length ? lecturerUsers.filter(item => !assignedCodes.has(item.code)).length : null;

  return (
    <div className="grid gap-4 xl:grid-cols-4">
      <OverviewItem title="Active Policy" value={activePolicy?.title || "Chưa có"} detail={activePolicy ? `Kích hoạt: ${formatDate(activePolicy.activated_at || activePolicy.created_at)}` : "Admin cần activate policy"} icon={<Shield size={18}/>} />
      <OverviewItem title="Master Tree" value={masterTree.tree ? "Đang hoạt động" : "Chưa sẵn sàng"} detail={masterTree.tree ? `${activePolicy?.parsed_json?.specializations?.length || 0} nhóm chuyên môn` : masterTree.message || "Chưa có cây active"} icon={<FolderOpen size={18}/>} />
      <OverviewItem title="Assignment Count" value={`${activeAssignments.length}`} detail={unassigned === null ? "Unassigned: chưa có dữ liệu" : `Unassigned Lecturers: ${unassigned}`} icon={<UserCheck size={18}/>} />
      <OverviewItem title="Last Change" value={audits[0] ? actionLabel(audits[0].action) : "Chưa có"} detail={audits[0] ? `${audits[0].actor} - ${formatDate(audits[0].created_at)}` : "Chưa có audit"} icon={<History size={18}/>} />
    </div>
  );
}

function OverviewItem({ title, value, detail, icon }: { title: string; value: string; detail: string; icon: ReactNode }) {
  return (
    <section className="app-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="muted text-[10px] font-bold uppercase">{title}</p>
          <strong className="mt-1 block text-sm">{value}</strong>
          <span className="muted mt-1 block text-[11px]">{detail}</span>
        </div>
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-blue-50 text-blue-600">{icon}</div>
      </div>
    </section>
  );
}

function AIGovernanceAssistantTab({ reloadAll }: { reloadAll: () => Promise<void> }) {
  const { request } = useAuth();
  const [command, setCommand] = useState(assistantExamples[0]);
  const [preview, setPreview] = useState<PolicyAssistantPreview | null>(null);
  const [result, setResult] = useState<PolicyAssistantConfirmResult | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function runPreview() {
    const nextCommand = command.trim();
    if (!nextCommand) return;
    setBusy(true);
    setMessage("");
    setResult(null);
    try {
      const data = await request<PolicyAssistantPreview>("/api/policy-assistant/preview", {
        method: "POST",
        body: JSON.stringify({ message: nextCommand }),
      });
      setPreview(data);
      if (data.status === "need_clarification") {
        setMessage(data.message || "Lệnh chưa đủ rõ để tạo preview.");
      }
    } catch (err) {
      setPreview(null);
      setMessage(err instanceof Error ? err.message : "Không phân tích được yêu cầu.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmPreview() {
    if (!preview?.action || !preview.preview) return;
    setConfirming(true);
    setMessage("");
    try {
      const data = await request<PolicyAssistantConfirmResult>("/api/policy-assistant/confirm", {
        method: "POST",
        body: JSON.stringify({ message: command.trim(), action: preview.action, preview: preview.preview, apply_now: true }),
      });
      setResult(data);
      setMessage(data.applied ? "Đã áp dụng thay đổi policy và refresh Master Tree/Audit." : "Đã confirm yêu cầu policy.");
      await reloadAll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không confirm được thay đổi.");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_1fr]">
      <Panel title="Knowledge Governance Agent" description="Nhập yêu cầu governance bằng ngôn ngữ tự nhiên để preview impact trước khi áp dụng.">
        <div className="space-y-4 p-4">
          <div>
            <p className="mb-2 text-xs font-bold">Phân công chuyên môn</p>
            <div className="flex flex-wrap gap-2">
              {assistantExamples.slice(0, 3).map(item => <button key={item} className="btn-secondary px-2 py-1 text-[11px]" onClick={() => { setCommand(item); setPreview(null); setResult(null); setMessage(""); }}>{item}</button>)}
            </div>
            <p className="mb-2 mt-3 text-xs font-bold">Policy tree và rule</p>
            <div className="flex flex-wrap gap-2">
              {assistantExamples.slice(3, 4).map(item => <button key={item} className="btn-secondary px-2 py-1 text-[11px]" onClick={() => { setCommand(item); setPreview(null); setResult(null); setMessage(""); }}>{item}</button>)}
            </div>
            <p className="mb-2 mt-3 text-xs font-bold">Co van governance</p>
            <div className="flex flex-wrap gap-2">
              {assistantExamples.slice(4, 7).map(item => <button key={item} className="btn-secondary px-2 py-1 text-[11px]" onClick={() => { setCommand(item); setPreview(null); setResult(null); setMessage(""); }}>{item}</button>)}
            </div>
            <p className="mb-2 mt-3 text-xs font-bold">Policy tree va rule</p>
            <div className="flex flex-wrap gap-2">
              {assistantExamples.slice(7).map(item => <button key={item} className="btn-secondary px-2 py-1 text-[11px]" onClick={() => { setCommand(item); setPreview(null); setResult(null); setMessage(""); }}>{item}</button>)}
            </div>
          </div>
          <textarea className="field min-h-32" value={command} onChange={event => setCommand(event.target.value)} placeholder="Ví dụ: Chuyển GV001 sang IoT" />
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" onClick={runPreview} disabled={busy || !command.trim()}>{busy ? <LoaderCircle className="animate-spin" size={15}/> : <Send size={15}/>}Phân tích</button>
            <button className="btn-secondary" onClick={confirmPreview} disabled={confirming || !preview?.action || preview.status !== "preview" || !!preview.preview?.confirm_blocked_reason || isAdvisorAction(preview.action)}>{confirming ? <LoaderCircle className="animate-spin" size={15}/> : <Check size={15}/>}Confirm</button>
          </div>
          {message && <p className={`rounded-lg px-3 py-2 text-xs ${result?.applied ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>{message}</p>}
        </div>
      </Panel>
      <Panel title="Kết quả phân tích" description="Admin xem interpretation, tree changes và permission changes trước khi confirm.">
        <div className="space-y-4 p-4">
          {preview?.status === "preview" && preview.action ? (
            <>
              <AssistantSection title="Interpretation" items={assistantInterpretation(preview.action, preview.preview?.summary)} />
              {isAssignmentAction(preview.action) ? (
                <AssignmentAgentPreview impact={preview.preview?.impact} blockedReason={preview.preview?.confirm_blocked_reason} />
              ) : isTimeBasedPermissionAction(preview.action) ? (
                <TimeBasedPermissionPreview impact={preview.preview?.impact} />
              ) : isAdvisorAction(preview.action) ? (
                <GovernanceAdvisorPreview impact={preview.preview?.impact} />
              ) : (
                <>
                  <AssistantSection title="Tree Changes" items={assistantTreeChanges(preview.action)} />
                  <AssistantSection title="Permission Changes" items={assistantPermissionChanges(preview.action)} />
                </>
              )}
              {result?.applied && <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-xs text-green-800">Applied audit: <strong>{result.applied.audit_log_id}</strong></div>}
            </>
          ) : (
            <>
              <PlaceholderBox title="Interpretation" text="Bấm Phân tích để xem hệ thống hiểu yêu cầu như thế nào." />
              <PlaceholderBox title="Tree Changes" text="Các thay đổi Master Tree sẽ hiển thị tại đây nếu có." />
              <PlaceholderBox title="Permission Changes" text="Các thay đổi quyền sẽ hiển thị tại đây nếu có." />
            </>
          )}
        </div>
      </Panel>
    </div>
  );
}

function AssistantSection({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-lg border border-[var(--border)] p-4">
      <strong className="block text-xs">{title}</strong>
      <div className="mt-2 space-y-2">
        {items.map(item => <p key={item} className="rounded-md bg-[var(--soft)] px-3 py-2 text-xs">{item}</p>)}
      </div>
    </div>
  );
}

function isAssignmentAction(action: PolicyAssistantAction) {
  return action.action.startsWith("assignment.");
}

function isTimeBasedPermissionAction(action: PolicyAssistantAction) {
  return action.action === "permission.time_based_release";
}

function isAdvisorAction(action: PolicyAssistantAction) {
  return action.action.startsWith("advisor.");
}

function specList(items?: ImpactSpec[]) {
  if (!items?.length) return "Không có";
  return items.map(item => item.code ? `${item.code} - ${item.name}` : item.name).join(", ");
}

function isTimeBasedPermissionImpact(impact?: AssignmentAgentImpact | TimeBasedPermissionImpact | GovernanceAdvisorImpact): impact is TimeBasedPermissionImpact {
  return !!impact && "before_permission" in impact;
}

function TimeBasedPermissionPreview({ impact }: { impact?: AssignmentAgentImpact | TimeBasedPermissionImpact | GovernanceAdvisorImpact }) {
  if (!isTimeBasedPermissionImpact(impact)) return <PlaceholderBox title="Permission Impact" text="Chưa có dữ liệu impact." />;
  return (
    <div className="space-y-4">
      <AssistantSection title="Rule ID" items={[impact.rule_id]} />
      <AssistantSection title="Rule Type" items={[impact.rule_type]} />
      <AssistantSection title="Loại tài liệu" items={[impact.document_type]} />
      <AssistantSection title="Học phần" items={[impact.course]} />
      <AssistantSection title="Nhóm được mở quyền" items={[specList(impact.target_specializations)]} />
      <AssistantSection title="Thời điểm mở quyền" items={[impact.release_at]} />
      <AssistantSection title="Quyền trước thời điểm đó" items={[impact.before_permission]} />
      <AssistantSection title="Quyền sau thời điểm đó" items={[impact.after_permission]} />
      <AssistantSection title="Impact" items={[`Tài liệu match: ${impact.permission_impact.documents_to_open}`, `Giảng viên mục tiêu: ${impact.permission_impact.target_lecturers}`, `Access grants sẽ tạo: ${impact.permission_impact.access_grants_to_create}`]} />
      <AssistantSection title="Risk Warning" items={impact.risk_warnings.length ? impact.risk_warnings : ["Không có cảnh báo rủi ro."]} />
    </div>
  );
}

function isAssignmentAgentImpact(impact?: AssignmentAgentImpact | TimeBasedPermissionImpact | GovernanceAdvisorImpact): impact is AssignmentAgentImpact {
  return !!impact && "assignment_impact" in impact;
}

function AssignmentAgentPreview({ impact, blockedReason }: { impact?: AssignmentAgentImpact | TimeBasedPermissionImpact | GovernanceAdvisorImpact; blockedReason?: string | null }) {
  if (!isAssignmentAgentImpact(impact)) return <PlaceholderBox title="Assignment Impact" text="Chưa có dữ liệu impact." />;
  return (
    <div className="space-y-4">
      <AssistantSection title="Giảng viên" items={[`Mã: ${impact.lecturer.code}`, `Tên: ${impact.lecturer.name}`, `Vai trò: ${impact.lecturer.role}`]} />
      <AssistantSection title="Chuyên môn" items={[`Hiện tại: ${specList(impact.current_specializations)}`, `Sau thay đổi: ${specList(impact.target_specializations)}`]} />
      <AssistantSection title="Assignment Impact" items={[`Thêm: ${specList(impact.assignment_impact.added_specializations)}`, `Gỡ: ${specList(impact.assignment_impact.removed_specializations)}`, `Giữ nguyên: ${specList(impact.assignment_impact.unchanged_specializations)}`]} />
      <AssistantSection title="Virtual Tree Impact" items={[`Rebuild: ${impact.virtual_tree_impact.rebuild ? "Có" : "Không"}`, `Số node bị ảnh hưởng: ${impact.virtual_tree_impact.affected_nodes}`]} />
      <AssistantSection title="Folder Permission Impact" items={[`Quyền sẽ thu hồi: ${impact.folder_permission_impact.permissions_to_revoke}`, `Quyền sẽ cấp mới: ${impact.folder_permission_impact.permissions_to_grant}`]} />
      <AssistantSection title="Risk Warning" items={blockedReason ? [...impact.risk_warnings, blockedReason] : (impact.risk_warnings.length ? impact.risk_warnings : ["Không có cảnh báo rủi ro."])} />
    </div>
  );
}

function isGovernanceAdvisorImpact(impact?: AssignmentAgentImpact | TimeBasedPermissionImpact | GovernanceAdvisorImpact): impact is GovernanceAdvisorImpact {
  return !!impact && "governance_score" in impact;
}

function formatRiskSummary(summary: Record<string, unknown>) {
  return [
    `Knowledge risk: ${String(summary.knowledge_risk ?? "unknown")}`,
    `Coverage: ${String(summary.document_coverage_percent ?? 0)}%`,
    `Policy compliance: ${String(summary.policy_compliance_percent ?? 0)}%`,
    `Transfer readiness: ${String(summary.transfer_readiness_score ?? 0)}%`,
    `Critical gaps: ${String(summary.critical_gap_count ?? 0)}`,
  ];
}

function GovernanceAdvisorPreview({ impact }: { impact?: AssignmentAgentImpact | TimeBasedPermissionImpact | GovernanceAdvisorImpact }) {
  if (!isGovernanceAdvisorImpact(impact)) return <PlaceholderBox title="Advisor Impact" text="Chua co du lieu advisor." />;
  const risks = impact.high_risk_areas.length
    ? impact.high_risk_areas.map(item => `${item.specialization_name || item.scope_name || "Khu vuc"} - ${item.knowledge_risk || item.risk || "risk"}${item.reason ? `: ${item.reason}` : ""}`)
    : ["Chua co khu vuc rui ro cao."];
  const actions = impact.recommended_actions.length
    ? impact.recommended_actions.map(item => `${item.priority || "normal"} - ${item.title || item.category || "Action"}${item.reason ? `: ${item.reason}` : ""}`)
    : ["Chua co action khuyen nghi."];
  const dependencies = impact.dependency_warnings.length
    ? impact.dependency_warnings.map(item => `${item.specialization_name || "Chuyen nganh"} phu thuoc ${item.lecturer_code || "N/A"} - risk ${item.dependency_risk || "unknown"} (${item.owned_document_count || 0} tai lieu, ${item.owner_concentration_percent || 0}%)`)
    : ["Chua co canh bao phu thuoc giang vien."];
  const gaps = impact.course_gaps.length
    ? impact.course_gaps.map(item => `${item.specialization_name || "Chuyen nganh"} / ${item.course_name || "Hoc phan"} - coverage ${item.coverage_percent || 0}%, thieu: ${(item.missing_types || []).join(", ") || "khong"}`)
    : ["Chua co hoc phan thieu tri thuc."];
  return (
    <div className="space-y-4">
      <AssistantSection title="Governance Score" items={[`${impact.governance_score}/100`]} />
      <AssistantSection title="Risk Summary" items={formatRiskSummary(impact.risk_summary)} />
      <AssistantSection title="High Risk Areas" items={risks} />
      <AssistantSection title="Recommended Actions" items={actions} />
      <AssistantSection title="Dependency Warnings" items={dependencies} />
      <AssistantSection title="Course Gaps" items={gaps} />
    </div>
  );
}

function assistantInterpretation(action: PolicyAssistantAction, summary?: string) {
  return [
    summary || `Hệ thống nhận diện yêu cầu: ${actionLabel(action.action)}.`,
    `Action: ${actionLabel(action.action)}`,
  ];
}

function assistantTreeChanges(action: PolicyAssistantAction) {
  if (action.action === "add_node") return [`Thêm "${action.node}" vào "${action.parent}".`];
  if (action.action === "move_node") return [`Chuyển "${action.node}" sang "${action.new_parent || action.parent}".`];
  if (action.action === "rename_node") return [`Đổi tên "${action.node}" thành "${action.new_name}".`];
  if (action.action === "delete_node") return [`Xóa node "${action.node}" khỏi Master Tree.`];
  return ["Không có thay đổi Master Tree trong lệnh này."];
}

function assistantPermissionChanges(action: PolicyAssistantAction) {
  if (action.action !== "update_permission") return ["Không có thay đổi quyền trong lệnh này."];
  const roles = action.roles?.join(", ") || "chưa xác định";
  return [`${action.document_type || "Tài liệu"} sẽ có visibility "${action.visibility || "confidential"}".`, `Role được xem: ${roles}.`];
}

function PlaceholderBox({ title, text }: { title: string; text: string }) {
  return <div className="rounded-lg border border-dashed border-[var(--border)] p-4"><strong className="block text-xs">{title}</strong><p className="muted mt-1 text-xs">{text}</p></div>;
}

function ImportPolicyTab({ policyFiles, reloadAll }: { policyFiles: PolicyFile[]; reloadAll: () => Promise<void> }) {
  const { request } = useAuth();
  const [policyFile, setPolicyFile] = useState<File | null>(null);
  const [policyTitle, setPolicyTitle] = useState("Policy học liệu khoa CNTT");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [activationPreview, setActivationPreview] = useState<ActivationPreview | null>(null);
  const [activatingPolicy, setActivatingPolicy] = useState<PolicyFile | null>(null);
  const [activationSummary, setActivationSummary] = useState<ActivationPreview | null>(null);
  const activePolicy = policyFiles.find(item => item.status === "active");

  async function uploadPolicy() {
    if (!policyFile) return;
    setBusy(true);
    setMessage("");
    try {
      await request("/api/policies/upload", {
        method: "POST",
        headers: {
          "X-Filename": encodeURIComponent(policyFile.name),
          "X-Title": encodeURIComponent(policyTitle),
          "Content-Type": policyFile.type || "text/plain",
        },
        body: await policyFile.arrayBuffer(),
      });
      setPolicyFile(null);
      setMessage("Đã upload policy. Hãy activate để cập nhật Master Tree.");
      await reloadAll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không upload được policy.");
    } finally {
      setBusy(false);
    }
  }

  async function activatePolicy(policyId: string) {
    setBusy(true);
    setMessage("");
    try {
      await request(`/api/policies/${policyId}/activate`, { method: "POST" });
      setMessage("Policy đã được kích hoạt.");
      await reloadAll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không activate được policy.");
    } finally {
      setBusy(false);
    }
  }

  async function openActivationPreview(policy: PolicyFile) {
    setBusy(true);
    setMessage("");
    try {
      const preview = await request<ActivationPreview>(`/api/policies/${policy.id}/activation-preview`);
      setActivatingPolicy(policy);
      setActivationPreview(preview);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Khong tao duoc activation preview.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmActivatePolicy() {
    if (!activatingPolicy) return;
    setBusy(true);
    setMessage("");
    try {
      const activated = await request<PolicyFile & { activation_summary?: ActivationPreview }>(`/api/policies/${activatingPolicy.id}/activate`, { method: "POST" });
      setActivationSummary(activated.activation_summary || activationPreview);
      setActivationPreview(null);
      setActivatingPolicy(null);
      setMessage("Policy da duoc kich hoat. Activation impact summary da duoc cap nhat.");
      await reloadAll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Khong activate duoc policy.");
    } finally {
      setBusy(false);
    }
  }

  async function deletePolicy(policy: PolicyFile) {
    if (!confirm(`Xóa policy "${policy.title}"?`)) return;
    setBusy(true);
    setMessage("");
    try {
      await request(`/api/policies/${policy.id}`, { method: "DELETE" });
      setMessage("Đã xóa policy.");
      await reloadAll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không xóa được policy.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
    <div className="grid gap-5 xl:grid-cols-[.82fr_1.18fr]">
      <Panel title="Upload Policy" description={activePolicy ? `Active Policy: ${activePolicy.title}` : "Chưa có policy active."}>
        <div className="space-y-4 p-4">
          {message && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">{message}</p>}
          {activationSummary && <ActivationSummaryCard preview={activationSummary} />}
          <label className="block text-xs font-bold">Tiêu đề policy</label>
          <input className="field" value={policyTitle} onChange={event => setPolicyTitle(event.target.value)} />
          <label className="block rounded-xl border-2 border-dashed border-blue-300 p-6 text-center">
            <FileUp className="mx-auto text-blue-600" size={24}/>
            <strong className="mt-3 block text-sm">{policyFile?.name || "Chọn file policy"}</strong>
            <span className="muted mt-1 block text-xs">PDF, DOCX, TXT, JSON, YAML</span>
            <input className="hidden" type="file" accept=".pdf,.docx,.txt,.json,.yaml,.yml" onChange={event => setPolicyFile(event.target.files?.[0] || null)} />
          </label>
          <button className="btn-primary w-full" disabled={!policyFile || busy} onClick={uploadPolicy}>{busy ? <LoaderCircle className="animate-spin" size={15}/> : <UploadCloud size={15}/>}Upload Policy</button>
        </div>
      </Panel>
      <Panel title="Policy List" description="Activate một policy để cập nhật Master Tree.">
        <div className="table-shell">
          <table className="data-table">
            <thead><tr><th>Policy</th><th>Status</th><th>Structure</th><th>Created</th><th></th></tr></thead>
            <tbody>
              {policyFiles.map(policy => (
                <tr key={policy.id}>
                  <td><strong>{policy.title}</strong><span className="muted block text-[10px]">{policy.created_by}</span></td>
                  <td><span className={`badge ${policy.status === "active" ? "badge-green" : "badge-amber"}`}>{policyStatusLabel(policy.status)}</span></td>
                  <td><span className="text-xs">{policy.parsed_json.faculty || "Chưa nhận diện khoa"}</span><span className="muted block text-[10px]">{policy.parsed_json.specializations.length} nhóm chuyên môn</span></td>
                  <td>{formatDate(policy.created_at)}</td>
                  <td>
                    <div className="flex justify-end gap-2">
                      {policy.status !== "active" && <button className="btn-secondary px-2 py-1 text-[11px]" disabled={busy} onClick={() => openActivationPreview(policy)}><Check size={13}/>Activate</button>}
                      <button className="btn-secondary px-2 py-1 text-[11px] text-red-600" disabled={busy || policy.status === "active"} onClick={() => deletePolicy(policy)}><Trash2 size={13}/>Xóa</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!policyFiles.length && <tr><td colSpan={5} className="muted text-center">Chưa có policy.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
    {activationPreview && activatingPolicy && (
      <ActivationPreviewDialog
        policy={activatingPolicy}
        preview={activationPreview}
        busy={busy}
        onClose={() => {
          if (busy) return;
          setActivationPreview(null);
          setActivatingPolicy(null);
        }}
        onConfirm={confirmActivatePolicy}
      />
    )}
    </>
  );
}

function ActivationSummaryCard({ preview }: { preview: ActivationPreview }) {
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
      <p className="mb-2 text-xs font-bold text-blue-900">Activation Audit Summary</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <ImpactMetric label="Added Specializations" value={preview.tree_impact.summary.added} />
        <ImpactMetric label="Removed Specializations" value={preview.tree_impact.summary.removed} />
        <ImpactMetric label="Valid Assignments" value={preview.assignment_impact.valid_assignments} />
        <ImpactMetric label="Needs Resolution" value={preview.assignment_impact.needs_resolution_assignments} />
      </div>
    </div>
  );
}

function ActivationPreviewDialog({ policy, preview, busy, onClose, onConfirm }: { policy: PolicyFile; preview: ActivationPreview; busy: boolean; onClose: () => void; onConfirm: () => void }) {
  const conflicts = preview.assignment_impact.requires_admin_resolution || [];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[88vh] w-full max-w-3xl overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)] shadow-xl">
        <div className="border-b border-[var(--border)] p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Policy Activation Preview</p>
          <h3 className="mt-1 text-lg font-bold">{policy.title}</h3>
          <p className="muted text-xs">Review impact before activating this policy.</p>
        </div>
        <div className="max-h-[62vh] space-y-4 overflow-y-auto p-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <ImpactMetric label="Added Specializations" value={preview.tree_impact.summary.added} />
            <ImpactMetric label="Removed Specializations" value={preview.tree_impact.summary.removed} />
            <ImpactMetric label="Matched Specializations" value={preview.tree_impact.summary.matched} />
            <ImpactMetric label="Virtual Trees" value={preview.virtual_tree_impact.virtual_trees_to_rebuild} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-[var(--border)] p-3">
              <p className="text-xs font-bold">Assignment Impact</p>
              <p className="muted mt-1 text-xs">Valid: {preview.assignment_impact.valid_assignments}</p>
              <p className="muted text-xs">Needs resolution: {preview.assignment_impact.needs_resolution_assignments}</p>
            </div>
            <div className="rounded-lg border border-[var(--border)] p-3">
              <p className="text-xs font-bold">Folder Permission Impact</p>
              <p className="muted mt-1 text-xs">Active permissions to deprecate: {preview.folder_permission_impact.active_permissions_to_deprecate}</p>
              <p className="muted text-xs">Will rebuild permissions: {preview.folder_permission_impact.will_rebuild_permissions ? "Yes" : "No"}</p>
            </div>
          </div>
          {!!preview.tree_impact.added_specializations.length && (
            <ImpactList title="Added" items={preview.tree_impact.added_specializations} />
          )}
          {!!preview.tree_impact.removed_specializations.length && (
            <ImpactList title="Removed" items={preview.tree_impact.removed_specializations} />
          )}
          {!!conflicts.length && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs font-bold text-amber-900">Assignments Need Resolution</p>
              <div className="mt-2 space-y-2">
                {conflicts.slice(0, 5).map(item => (
                  <div key={`${item.assignment_id}-${item.lecturer_code}`} className="rounded-md bg-white p-2 text-xs">
                    <strong>{item.lecturer_code}</strong> - {item.old_specialization || item.old_code || "Unknown"}: {item.reason}
                  </div>
                ))}
                {conflicts.length > 5 && <p className="muted text-xs">+{conflicts.length - 5} more</p>}
              </div>
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-[var(--border)] p-4">
          <button className="btn-secondary" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy} onClick={onConfirm}>{busy ? <LoaderCircle className="animate-spin" size={15}/> : <Check size={15}/>}Confirm Activate</button>
        </div>
      </div>
    </div>
  );
}

function ImpactMetric({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3"><p className="muted text-[11px]">{label}</p><strong className="mt-1 block text-lg">{value}</strong></div>;
}

function ImpactList({ title, items }: { title: string; items: ActivationSpecialization[] }) {
  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <p className="text-xs font-bold">{title}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map(item => <span key={`${item.code || item.key}-${item.name}`} className="badge badge-amber">{item.code ? `${item.code} - ` : ""}{item.name || item.name_en}</span>)}
      </div>
    </div>
  );
}

function KnowledgeTreeTab({ masterTree }: { masterTree: MasterTree }) {
  return (
    <Panel title="Knowledge Tree" description="Master Tree hiện tại, chỉ đọc, dùng dữ liệu backend tree hiện có.">
      <div className="p-4">
        {masterTree.tree ? <TreePreview node={masterTree.tree} /> : <p className="muted text-xs">{masterTree.message || "Chưa có Master Tree active."}</p>}
      </div>
    </Panel>
  );
}

function LecturerAssignmentTab({ assignments, users, canSeeUsers, reloadAll }: { assignments: Assignment[]; users: User[]; canSeeUsers: boolean; reloadAll: () => Promise<void> }) {
  const { request } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<AssignmentPreview | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const activeAssignments = assignments.filter(item => item.status === "active");
  const lecturerUsers = users.filter(item => item.role === "lecturer" || item.role === "new_lecturer");
  const assignedCodes = new Set(activeAssignments.map(item => item.lecturer_code));
  const unassignedCount = canSeeUsers ? lecturerUsers.filter(item => !assignedCodes.has(item.code)).length : null;

  async function previewImport() {
    if (!file) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await request<AssignmentPreview>("/api/lecturer-assignments/import/preview", {
        method: "POST",
        headers: { "X-Filename": file.name, "Content-Type": file.type || "text/csv" },
        body: await file.arrayBuffer(),
      });
      setPreview(result);
      setMessage(result.status === "validated" ? "File hợp lệ, có thể confirm để provision." : "File còn lỗi, vui lòng kiểm tra preview.");
      await reloadAll();
    } catch (err) {
      setPreview(null);
      setMessage(err instanceof Error ? err.message : "Không preview được assignment.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmImport() {
    if (!preview) return;
    setBusy(true);
    setMessage("");
    try {
      await request("/api/lecturer-assignments/import/confirm", {
        method: "POST",
        body: JSON.stringify({ batch_preview_id: preview.batch_preview_id, apply_mode: "replace_for_listed_lecturers" }),
      });
      setMessage("Đã confirm và provision assignment.");
      setPreview(null);
      setFile(null);
      await reloadAll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không confirm được assignment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-3">
        <OverviewItem title="Assigned Lecturers" value={`${assignedCodes.size}`} detail="Giảng viên đã có assignment active" icon={<UserCheck size={18}/>} />
        <OverviewItem title="Unassigned Lecturers" value={unassignedCount === null ? "N/A" : `${unassignedCount}`} detail={canSeeUsers ? "Tính từ danh sách users" : "Head chưa có API danh sách users"} icon={<Users size={18}/>} />
        <OverviewItem title="Active Assignment Count" value={`${activeAssignments.length}`} detail="Số bản ghi assignment active" icon={<History size={18}/>} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[.85fr_1.15fr]">
        <Panel title="Import CSV Assignment" description="Import danh sách phân công, preview trước, confirm sau để provision Virtual Tree và Folder Permission.">
          <div className="space-y-4 p-4">
            {message && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">{message}</p>}
            <label className="block rounded-xl border-2 border-dashed border-blue-300 p-6 text-center">
              <FileUp className="mx-auto text-blue-600" size={24}/>
              <strong className="mt-3 block text-sm">{file?.name || "Chọn file CSV"}</strong>
              <span className="muted mt-1 block text-xs">CSV: lecturer_code, lecturer_name, specialization</span>
              <input className="hidden" type="file" accept=".csv,.json" onChange={event => setFile(event.target.files?.[0] || null)} />
            </label>
            <button className="btn-primary w-full" disabled={!file || busy} onClick={previewImport}>{busy ? <LoaderCircle className="animate-spin" size={15}/> : <Search size={15}/>}Preview</button>
            <button className="btn-secondary w-full" disabled={!preview || preview.summary.error_rows > 0 || busy} onClick={confirmImport}><Check size={15}/>Confirm & Provision</button>
          </div>
        </Panel>
        <AssignmentPreviewPanel preview={preview} />
      </div>

      <Panel title="Assigned Lecturers" description="Danh sách assignment đã được ghi nhận từ API hiện có.">
        <div className="table-shell">
          <table className="data-table">
            <thead><tr><th>Lecturer</th><th>Specialization</th><th>Source</th><th>Status</th><th>Updated</th></tr></thead>
            <tbody>
              {assignments.map(item => (
                <tr key={item.id}>
                  <td><strong>{item.lecturer_code}</strong><span className="muted block text-[10px]">{item.lecturer_name || item.lecturer_name_snapshot || ""}</span></td>
                  <td>{item.specialization_code_snapshot ? `${item.specialization_code_snapshot} - ` : ""}{item.specialization_name || item.specialization_name_snapshot}</td>
                  <td>{sourceLabel(item.source)}</td>
                  <td><span className={`badge ${item.status === "active" ? "badge-green" : "badge-amber"}`}>{assignmentStatusLabel(item.status)}</span></td>
                  <td>{formatDate(item.updated_at || item.created_at)}</td>
                </tr>
              ))}
              {!assignments.length && <tr><td colSpan={5} className="muted text-center">Chưa có assignment.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function AssignmentPreviewPanel({ preview }: { preview: AssignmentPreview | null }) {
  return (
    <Panel title="Preview" description="Kiểm tra lỗi trước khi confirm. Preview chưa provision quyền.">
      <div className="p-4">
        {!preview ? <PlaceholderBox title="Chưa có preview" text="Chọn file CSV rồi bấm Preview." /> : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <SummaryBox label="Total" value={preview.summary.total_rows} />
              <SummaryBox label="Valid" value={preview.summary.valid_rows} />
              <SummaryBox label="Errors" value={preview.summary.error_rows} />
              <SummaryBox label="Warnings" value={preview.summary.warning_rows} />
            </div>
            <div className="table-shell">
              <table className="data-table">
                <thead><tr><th>Row</th><th>Lecturer</th><th>Specialization</th><th>Status</th><th>Message</th></tr></thead>
                <tbody>
                  {preview.assignments.map(item => (
                    <tr key={item.row}>
                      <td>{item.row}</td>
                      <td><strong>{item.lecturer_code}</strong><span className="muted block text-[10px]">{item.lecturer_name}</span></td>
                      <td>{item.specialization_code ? `${item.specialization_code} - ` : ""}{item.specialization_name || item.specialization_input}</td>
                      <td><span className={`badge ${item.status === "valid" ? "badge-green" : "badge-red"}`}>{item.status === "valid" ? "Hợp lệ" : "Lỗi"}</span></td>
                      <td className="text-xs">{[...item.errors, ...item.warnings].join("; ") || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

function SummaryBox({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg border border-[var(--border)] p-3"><span className="muted block text-[10px] font-bold uppercase">{label}</span><strong className="text-lg">{value}</strong></div>;
}

function AuditLogTab({ audits, requests, assignments, reloadAll }: { audits: PolicyAudit[]; requests: PolicyRequest[]; assignments: Assignment[]; reloadAll: () => Promise<void> }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_1fr]">
      <Panel title="Policy Audit" description="Nhật ký policy hiện có.">
        <div className="table-shell">
          <table className="data-table">
            <thead><tr><th>Actor</th><th>Action</th><th>Status</th><th>Time</th></tr></thead>
            <tbody>
              {audits.map(item => <tr key={item.id}><td>{item.actor}</td><td>{actionLabel(item.action)}</td><td>{item.status}</td><td>{formatDate(item.created_at)}</td></tr>)}
              {!audits.length && <tr><td colSpan={4} className="muted text-center">Chưa có policy audit.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Assignment Audit" description="Tận dụng assignment records và workflow requests hiện có.">
        <div className="max-h-[560px] space-y-3 overflow-auto p-4">
          <button className="btn-secondary w-full" onClick={reloadAll}><RefreshCw size={14}/>Làm mới</button>
          {assignments.slice(0, 20).map(item => (
            <div key={item.id} className="rounded-lg border border-[var(--border)] p-3">
              <div className="flex items-center gap-2"><UserCheck size={15} className="text-blue-600"/><strong className="text-xs">{item.lecturer_code}</strong><span className="badge badge-amber ml-auto">{assignmentStatusLabel(item.status)}</span></div>
              <p className="muted mt-2 text-[11px]">{sourceLabel(item.source)} - {formatDate(item.updated_at || item.created_at)}</p>
              <p className="mt-2 text-xs">{item.specialization_code_snapshot ? `${item.specialization_code_snapshot} - ` : ""}{item.specialization_name || item.specialization_name_snapshot}</p>
            </div>
          ))}
          {requests.slice(0, 10).map(item => (
            <div key={item.id} className="rounded-lg border border-[var(--border)] p-3">
              <div className="flex items-center gap-2"><History size={15} className="text-blue-600"/><strong className="text-xs">Policy request</strong><span className="badge badge-amber ml-auto">{item.status}</span></div>
              <p className="muted mt-2 text-[11px]">{item.actor} - {formatDate(item.created_at)}</p>
              <p className="mt-2 text-xs">{item.message}</p>
            </div>
          ))}
          {!assignments.length && !requests.length && <p className="muted text-xs">Chưa có audit hoặc assignment activity.</p>}
        </div>
      </Panel>
    </div>
  );
}

function TreePreview({ node }: { node: FolderNode }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([node.path]));
  const [query, setQuery] = useState("");
  const normalized = query.trim().toLocaleLowerCase("vi");

  function matches(item: FolderNode): boolean {
    return !normalized || item.name.toLocaleLowerCase("vi").includes(normalized) || item.children.some(matches);
  }

  function collectAll(item: FolderNode, acc = new Set<string>()) {
    acc.add(item.path);
    item.children.forEach(child => collectAll(child, acc));
    return acc;
  }

  function render(item: FolderNode, depth = 0): ReactNode {
    if (!matches(item)) return null;
    const open = expanded.has(item.path) || !!normalized;
    return (
      <div key={item.id}>
        <button type="button" className="flex w-full items-center gap-1 rounded-md py-1.5 pr-2 text-left text-xs hover:bg-[var(--soft)]" style={{ paddingLeft: `${6 + depth * 16}px` }} onClick={() => setExpanded(cur => {
          const next = new Set(cur);
          if (next.has(item.path)) next.delete(item.path); else next.add(item.path);
          return next;
        })}>
          {item.children.length ? (open ? <ChevronDown size={14}/> : <ChevronRight size={14}/>) : <span className="w-[14px]"/>}
          {open ? <FolderOpen className="text-amber-500" size={15}/> : <Folder className="text-amber-500" size={15}/>}
          <span className="truncate font-semibold">{item.name}</span>
        </button>
        {open && item.children.map(child => render(child, depth + 1))}
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        <div className="relative min-w-72 flex-1"><Search className="muted absolute left-3 top-2.5" size={14}/><input className="field pl-9" value={query} onChange={event => setQuery(event.target.value)} placeholder="Ví dụ: Chuyển GV001 sang IoT" /></div>
        <button className="btn-secondary" onClick={() => setExpanded(collectAll(node))}>Expand</button>
        <button className="btn-secondary" onClick={() => setExpanded(new Set([node.path]))}>Collapse</button>
      </div>
      <div role="tree" className="max-h-[62vh] overflow-auto rounded-lg border border-[var(--border)] p-2">{render(node)}</div>
    </div>
  );
}

function tabIcon(tab: GovernanceTab) {
  if (tab === "assistant") return <Bot size={15}/>;
  if (tab === "import") return <UploadCloud size={15}/>;
  if (tab === "tree") return <FolderOpen size={15}/>;
  if (tab === "assignment") return <UserCheck size={15}/>;
  return <History size={15}/>;
}

function tabLabel(tab: GovernanceTab) {
  return {
    assistant: "AI Governance Assistant",
    import: "Import Policy",
    tree: "Knowledge Tree",
    assignment: "Lecturer Assignment",
    audit: "Audit Log",
  }[tab];
}

function policyStatusLabel(status: string) {
  if (status === "active") return "Active";
  if (status === "draft") return "Draft";
  if (status === "archived") return "Archived";
  return status;
}

function actionLabel(action: string) {
  const labels: Record<string, string> = {
    add_node: "Thêm node",
    move_node: "Chuyển node",
    rename_node: "Đổi tên node",
    delete_node: "Xóa node",
    update_permission: "Cập nhật quyền",
    "assignment.move": "Chuyển chuyên môn giảng viên",
    "assignment.assign": "Gán thêm chuyên môn",
    "assignment.remove": "Bỏ chuyên môn",
    "permission.time_based_release": "Mở quyền theo thời gian",
    "advisor.risk_analysis": "Phan tich rui ro",
    "advisor.recommendations": "Khuyen nghi governance",
    "advisor.course_gap": "Hoc phan thieu tri thuc",
    "advisor.specialization_risk": "Rui ro chuyen nganh",
  };
  return labels[action] || action;
}

function sourceLabel(source: string) {
  const labels: Record<string, string> = {
    csv_import: "CSV Import",
    json_import: "JSON Import",
    governance_assignment_agent: "Knowledge Governance Agent",
    legacy_self_selected: "Legacy",
    admin_manual: "Admin",
  };
  return labels[source] || source;
}

function assignmentStatusLabel(status: string) {
  if (status === "active") return "Active";
  if (status === "validated") return "Validated";
  if (status === "inactive") return "Inactive";
  if (status === "revoked") return "Revoked";
  return status;
}

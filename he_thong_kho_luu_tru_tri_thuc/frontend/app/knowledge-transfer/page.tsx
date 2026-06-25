"use client";

import type { ReactNode } from "react";
import { AlertTriangle, BarChart3, BookOpenCheck, CheckCircle2, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { PermissionGuard } from "@/components/permission-guard";
import { PageHeader, Panel } from "@/components/ui";
import { useBackendData } from "@/lib/hooks";

type InsightSummary = {
  policy: { id: string; title: string } | null;
  summary: {
    document_coverage_percent: number;
    policy_compliance_percent: number;
    transfer_readiness_score: number;
    knowledge_risk: string;
    critical_gap_count: number;
    course_complete_count: number;
    course_total_count: number;
    single_lecturer_specialization_count: number;
    stale_document_count: number;
  };
  top_risks: Array<{ scope_name: string; risk: string; reason: string }>;
};

type SpecializationInsight = {
  specialization_id: string;
  specialization_name: string;
  document_coverage_percent: number;
  assigned_lecturer_count: number;
  transfer_readiness_score: number;
  knowledge_risk: string;
  missing_required_slots: number;
};

type CourseGap = {
  course_id: string;
  course_name: string;
  specialization_name: string;
  missing_types: string[];
  coverage_percent: number;
  risk: string;
};

type LecturerDependency = {
  lecturer_code: string;
  lecturer_name: string;
  specialization_name: string;
  owned_document_count: number;
  dependency_risk: string;
  owner_concentration_percent: number;
};

type RecommendedAction = {
  priority: "critical" | "high" | "medium" | "low";
  category: string;
  title: string;
  reason: string;
  recommended_actions: string[];
};

type KnowledgeDocument = {
  id: string;
  title: string;
  topic: string;
  doc_type: string;
};

type KnowledgeSummary = {
  summary: string;
  documents: KnowledgeDocument[];
};

type OnboardingCourse = {
  code: string;
  name: string;
  knowledge?: KnowledgeSummary;
};

type TransferSession = {
  id: string;
  course_code: string;
  course_name?: string;
  from_code: string;
  to_code: string;
  deadline: string;
  status: string;
  progress: number;
};

const emptySummary: InsightSummary = {
  policy: null,
  summary: {
    document_coverage_percent: 0,
    policy_compliance_percent: 0,
    transfer_readiness_score: 0,
    knowledge_risk: "critical",
    critical_gap_count: 0,
    course_complete_count: 0,
    course_total_count: 0,
    single_lecturer_specialization_count: 0,
    stale_document_count: 0,
  },
  top_risks: [],
};

export default function KnowledgeTransfer() {
  const { ready, user } = useAuth();
  const permissions = user?.permissions || [];
  const canManageTransfer = permissions.includes("transfer.manage");
  const canViewHandover = permissions.includes("handover.view") || permissions.includes("knowledge.summary");

  if (!ready) {
    return <div className="muted p-6 text-sm">Dang tai phan quyen...</div>;
  }

  if (canManageTransfer) {
    return <KnowledgeTransferDashboard />;
  }

  if (canViewHandover) {
    return <NewLecturerKnowledgeTransfer />;
  }

  return (
    <PermissionGuard permission="transfer.manage">
      <KnowledgeTransferDashboard />
    </PermissionGuard>
  );
}

function NewLecturerKnowledgeTransfer() {
  const { data: courses, reload: reloadCourses, error: coursesError } = useBackendData<OnboardingCourse[]>("/api/onboarding/courses", []);
  const { data: processes, reload: reloadProcesses, error: processesError } = useBackendData<KnowledgeSummary>("/api/onboarding/processes", { summary: "", documents: [] });
  const { data: transfers, reload: reloadTransfers, error: transfersError } = useBackendData<TransferSession[]>("/api/transfers", []);

  async function refreshAll() {
    await Promise.all([reloadCourses(), reloadProcesses(), reloadTransfers()]);
  }

  const transferCount = transfers.length;
  const averageProgress = transferCount ? Math.round(transfers.reduce((total, transfer) => total + Number(transfer.progress || 0), 0) / transferCount) : 0;
  const activeTransfers = transfers.filter(transfer => transfer.status !== "completed").length;
  const errors = [coursesError, processesError, transfersError].filter(Boolean);

  return (
    <div>
      <PageHeader
        eyebrow="Chuyen giao tri thuc"
        title="Tom tat tri thuc"
        description="Khong gian ban giao tri thuc ca nhan cho giang vien moi: tom tat tri thuc, hoc phan lien quan va tien do chuyen giao."
        actions={<button className="btn-secondary" onClick={refreshAll}><RefreshCw size={15} />Lam moi</button>}
      />

      {!!errors.length && (
        <section className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          {errors[0]}
        </section>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <KpiCard title="Tom tat tri thuc" value={`${processes.documents.length}`} detail="Tai lieu quy trinh co the doc" icon={<BookOpenCheck size={18} />} />
        <KpiCard title="Tri thuc hoc phan" value={`${courses.length}`} detail="Hoc phan dang co tri thuc lien quan" icon={<ShieldCheck size={18} />} />
        <KpiCard title="Tien do chuyen giao" value={`${averageProgress}%`} detail={`${activeTransfers}/${transferCount} phien dang thuc hien`} icon={<CheckCircle2 size={18} />} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[.9fr_1.1fr]">
        <Panel title="Tom tat tri thuc" description="Tom tat cac tai lieu quy trinh ma tai khoan hien tai duoc phep doc.">
          <p className="rounded-md bg-slate-50 p-3 text-sm leading-6">{processes.summary || "Chua co du lieu tom tat."}</p>
          <DataTable
            headers={["Document", "Topic", "Type"]}
            empty="Chua co tai lieu quy trinh."
            rows={processes.documents.map(document => [
              <strong key="title">{document.title}</strong>,
              document.topic || "-",
              document.doc_type || "-",
            ])}
          />
        </Panel>

        <Panel title="Tri thuc hoc phan" description="Hoc phan va tai lieu lien quan ma giang vien moi co quyen xem.">
          <DataTable
            headers={["Hoc phan", "Tai lieu lien quan", "Chu de"]}
            empty="Chua co hoc phan lien quan."
            rows={courses.map(course => {
              const documents = course.knowledge?.documents || [];
              const topics = Array.from(new Set(documents.map(document => document.topic).filter(Boolean)));
              return [
                <div key="course"><strong className="block">{course.name}</strong><span className="muted text-[10px]">{course.code}</span></div>,
                `${documents.length}`,
                topics.length ? topics.join(", ") : "-",
              ];
            })}
          />
        </Panel>
      </div>

      <div className="mt-5">
        <Panel title="Tien do chuyen giao" description="Cac phien chuyen giao gan voi tai khoan hien tai.">
          <DataTable
            headers={["Hoc phan", "Ban giao tu", "Ban giao cho", "Tien do", "Han chot", "Trang thai"]}
            empty="Chua co phien chuyen giao."
            rows={transfers.map(transfer => [
              <div key="course"><strong className="block">{transfer.course_name || transfer.course_code}</strong><span className="muted text-[10px]">{transfer.course_code}</span></div>,
              transfer.from_code,
              transfer.to_code,
              `${transfer.progress || 0}%`,
              transfer.deadline || "-",
              <StatusBadge key="status" status={transfer.status} />,
            ])}
          />
        </Panel>
      </div>
    </div>
  );
}

function KnowledgeTransferDashboard() {
  const { data: insight, reload: reloadInsight } = useBackendData<InsightSummary>("/api/knowledge-transfer/insights", emptySummary);
  const { data: actions, reload: reloadActions } = useBackendData<RecommendedAction[]>("/api/knowledge-transfer/actions", []);
  const { data: specializations, reload: reloadSpecs } = useBackendData<{ items: SpecializationInsight[] }>("/api/knowledge-transfer/insights/specializations", { items: [] });
  const { data: courseGaps, reload: reloadCourses } = useBackendData<{ items: CourseGap[] }>("/api/knowledge-transfer/insights/course-gaps", { items: [] });
  const { data: lecturerDependency, reload: reloadLecturers } = useBackendData<{ items: LecturerDependency[] }>("/api/knowledge-transfer/insights/lecturer-dependency", { items: [] });

  async function refreshAll() {
    await Promise.all([reloadInsight(), reloadActions(), reloadSpecs(), reloadCourses(), reloadLecturers()]);
  }

  const summary = insight.summary;

  return (
    <div>
      <PageHeader
        eyebrow="Phan tich chuyen giao tri thuc"
        title="Bang dieu khien chuyen giao tri thuc"
        description="Theo dõi khoảng trống tri thức, độ phủ tài liệu và rủi ro phụ thuộc giảng viên."
        actions={<button className="btn-secondary" onClick={refreshAll}><RefreshCw size={15} />Làm mới</button>}
      />

      <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3 text-xs">
        <span className="muted">Chinh sach dang ap dung: </span>
        <strong>{insight.policy?.title || "Chưa có policy active"}</strong>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard title="Do phu tai lieu" value={`${summary.document_coverage_percent}%`} detail={`${summary.course_complete_count}/${summary.course_total_count} hoc phan du tai lieu`} icon={<BookOpenCheck size={18} />} />
        <KpiCard title="Tuan thu chinh sach" value={`${summary.policy_compliance_percent}%`} detail="Metadata va projection phan quyen theo folder" icon={<ShieldCheck size={18} />} />
        <KpiCard title="Muc san sang chuyen giao" value={`${summary.transfer_readiness_score}/100`} detail={`Muc do rui ro: ${riskLabel(summary.knowledge_risk)}`} icon={<BarChart3 size={18} />} />
        <KpiCard title="Khoang trong nghiem trong" value={`${summary.critical_gap_count}`} detail={`${summary.single_lecturer_specialization_count} chuyen mon phu thuoc 1 GV`} icon={<AlertTriangle size={18} />} tone={summary.critical_gap_count ? "danger" : "normal"} />
      </div>

      <div className="mt-5">
        <Panel title="Hanh dong uu tien" description="Cac viec nen lam tiep theo duoc sinh bang quy tac deterministic tu coverage, assignment va dependency.">
          <DataTable
            headers={["Priority", "Action", "Reason", "Recommended Actions"]}
            empty="Khong co action can xu ly."
            rows={actions.slice(0, 8).map(item => [
              <PriorityBadge key="priority" priority={item.priority} />,
              <div key="title"><strong className="block">{item.title}</strong><span className="muted text-[10px]">{item.category}</span></div>,
              item.reason,
              <div key="actions" className="flex flex-wrap gap-1">{item.recommended_actions.map(action => <span key={action} className="badge badge-blue">{action}</span>)}</div>,
            ])}
          />
        </Panel>
      </div>

      {!!insight.top_risks.length && (
        <section className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="text-xs font-bold text-amber-900">Rui ro tri thuc noi bat</p>
          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            {insight.top_risks.map(item => (
              <div key={`${item.scope_name}-${item.reason}`} className="rounded-md bg-white p-3 text-xs">
                <div className="flex items-center gap-2">
                  <strong>{item.scope_name}</strong>
                  <RiskBadge risk={item.risk} />
                </div>
                <p className="muted mt-1">{item.reason}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
        <Panel title="Bang rui ro chuyen mon" description="Do phu tai lieu, assignment va readiness theo chuyen mon.">
          <DataTable
            headers={["Specialization", "Coverage", "Assigned Lecturers", "Readiness", "Risk"]}
            empty="Chưa có dữ liệu chuyên môn."
            rows={specializations.items.map(item => [
              <strong key="name">{item.specialization_name}</strong>,
              `${item.document_coverage_percent}%`,
              `${item.assigned_lecturer_count}`,
              `${item.transfer_readiness_score}/100`,
              <RiskBadge key="risk" risk={item.knowledge_risk} />,
            ])}
          />
        </Panel>

        <Panel title="Bang thieu tai lieu theo hoc phan" description="Cac hoc phan con thieu tai lieu theo folder template dang active.">
          <DataTable
            headers={["Hoc phan", "Tai lieu con thieu", "Do phu", "Rui ro"]}
            empty="Không có course gap."
            rows={courseGaps.items.filter(item => item.missing_types.length || item.risk !== "low").map(item => [
              <div key="course"><strong className="block">{item.course_name}</strong><span className="muted text-[10px]">{item.specialization_name}</span></div>,
              item.missing_types.length ? item.missing_types.join(", ") : "Đủ tài liệu",
              `${item.coverage_percent}%`,
              <RiskBadge key="risk" risk={item.risk} />,
            ])}
          />
        </Panel>
      </div>

      <div className="mt-5">
        <Panel title="Bang phu thuoc giang vien" description="Phat hien chuyen mon phu thuoc vao mot giang vien hoac mot owner tai lieu.">
          <DataTable
            headers={["Lecturer", "Specialization", "Owned Documents", "Dependency Risk"]}
            empty="Chưa có dữ liệu phụ thuộc giảng viên."
            rows={lecturerDependency.items.map(item => [
              <div key="lecturer" className="flex items-center gap-2"><Users size={15} className="text-blue-600" /><strong>{item.lecturer_code}</strong><span className="muted text-[10px]">{item.lecturer_name}</span></div>,
              item.specialization_name,
              `${item.owned_document_count} (${item.owner_concentration_percent}% concentration)`,
              <RiskBadge key="risk" risk={item.dependency_risk} />,
            ])}
          />
        </Panel>
      </div>
    </div>
  );
}

function KpiCard({ title, value, detail, icon, tone = "normal" }: { title: string; value: string; detail: string; icon: ReactNode; tone?: "normal" | "danger" }) {
  return (
    <section className={`app-card p-4 ${tone === "danger" ? "border-amber-300 bg-amber-50" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="muted text-[10px] font-bold uppercase">{title}</p>
          <strong className="mt-1 block text-2xl">{value}</strong>
          <span className="muted mt-1 block text-[11px]">{detail}</span>
        </div>
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-blue-50 text-blue-600">{icon}</div>
      </div>
    </section>
  );
}

function DataTable({ headers, rows, empty }: { headers: string[]; rows: ReactNode[][]; empty: string }) {
  return (
    <div className="table-shell">
      <table className="data-table">
        <thead><tr>{headers.map(header => <th key={header}>{header}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}
          {!rows.length && <tr><td colSpan={headers.length} className="muted text-center">{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function RiskBadge({ risk }: { risk: string }) {
  const classes: Record<string, string> = {
    critical: "badge-red",
    high: "badge-amber",
    medium: "badge-blue",
    low: "badge-green",
  };
  return <span className={`badge ${classes[risk] || "badge-blue"}`}>{riskLabel(risk)}</span>;
}

function PriorityBadge({ priority }: { priority: string }) {
  const classes: Record<string, string> = {
    critical: "badge-red",
    high: "badge-amber",
    medium: "badge-blue",
    low: "badge-green",
  };
  return <span className={`badge ${classes[priority] || "badge-blue"}`}>{riskLabel(priority)}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const done = status === "completed";
  return <span className={`badge ${done ? "badge-green" : "badge-blue"}`}>{done ? "Hoan thanh" : "Dang thuc hien"}</span>;
}

function riskLabel(risk: string) {
  if (risk === "critical") return "Nghiem trong";
  if (risk === "high") return "Cao";
  if (risk === "medium") return "Trung binh";
  if (risk === "low") return "Thap";
  return risk || "Khong ro";
}

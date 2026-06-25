"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { BookOpenCheck, FileText, GraduationCap, LoaderCircle, Search, ShieldCheck, UserCog } from "lucide-react";
import { EmptyState, PageHeader, Panel } from "@/components/ui";
import { DocumentDetail, formatDate } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type GlobalResult = {
  type: string;
  title: string;
  description: string;
  source: string;
  updated_time?: string | null;
  id?: string;
  href?: string;
};

type GlobalSearchResponse = {
  query: string;
  documents: GlobalResult[];
  courses: GlobalResult[];
  specializations: GlobalResult[];
  lecturers: GlobalResult[];
  rules: GlobalResult[];
  policy: GlobalResult[];
  audit: GlobalResult[];
  assignments: GlobalResult[];
};

type HydratedDocument = GlobalResult & {
  detail?: DocumentDetail;
};

const emptyResponse: GlobalSearchResponse = {
  query: "",
  documents: [],
  courses: [],
  specializations: [],
  lecturers: [],
  rules: [],
  policy: [],
  audit: [],
  assignments: [],
};

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="muted p-6 text-sm">Đang tải trang tìm kiếm...</div>}>
      <GlobalSearchPage />
    </Suspense>
  );
}

function GlobalSearchPage() {
  const params = useSearchParams();
  const initialQuery = params.get("q") || "";
  const { request } = useAuth();
  const [query, setQuery] = useState(initialQuery);
  const [searchedQuery, setSearchedQuery] = useState("");
  const [data, setData] = useState<GlobalSearchResponse>(emptyResponse);
  const [documents, setDocuments] = useState<HydratedDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runSearch(nextQuery = query) {
    const q = nextQuery.trim();
    setQuery(nextQuery);
    setSearchedQuery(q);
    setError("");
    setDocuments([]);
    if (!q) {
      setData(emptyResponse);
      return;
    }
    setLoading(true);
    try {
      const result = await request<GlobalSearchResponse>(`/api/search/global?q=${encodeURIComponent(q)}`);
      setData(result);
      const hydrated = await Promise.all(result.documents.map(async item => {
        if (!item.id) return item;
        try {
          const detail = await request<DocumentDetail>(`/api/documents/${item.id}`);
          return { ...item, detail };
        } catch {
          return item;
        }
      }));
      setDocuments(hydrated);
    } catch (err) {
      setData(emptyResponse);
      setError(err instanceof Error ? err.message : "Không thể tìm kiếm dữ liệu.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setQuery(initialQuery);
    if (initialQuery.trim()) void runSearch(initialQuery);
  }, [initialQuery]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runSearch(query);
  }

  const secondaryGroups = useMemo(() => [
    { title: "Học phần", icon: <GraduationCap size={16} />, items: data.courses },
    { title: "Nhóm chuyên môn", icon: <BookOpenCheck size={16} />, items: data.specializations },
    { title: "Giảng viên", icon: <UserCog size={16} />, items: data.lecturers },
    { title: "Quản trị tri thức", icon: <ShieldCheck size={16} />, items: [...data.rules, ...data.policy, ...data.assignments] },
  ].filter(group => group.items.length > 0), [data]);

  const totalResults = documents.length + secondaryGroups.reduce((total, group) => total + group.items.length, 0);
  const hasSearched = !!searchedQuery;

  return (
    <div>
      <PageHeader
        eyebrow="Tìm kiếm"
        title="Tìm kiếm toàn hệ thống"
        description="Tra cứu tài liệu, học phần, giảng viên và các thông tin quản trị trong phạm vi bạn được phép xem."
      />

      <form onSubmit={submit} className="mb-5 flex flex-col gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 md:flex-row">
        <div className="relative flex-1">
          <Search className="muted absolute left-3 top-3" size={17} />
          <input
            className="field h-11 pl-10"
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="Tìm tài liệu, học phần, giảng viên..."
          />
        </div>
        <button className="btn-primary h-11 justify-center" disabled={loading || !query.trim()}>
          {loading ? <LoaderCircle className="animate-spin" size={15} /> : <Search size={15} />}Tìm kiếm
        </button>
      </form>

      {error && <p className="mb-4 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}
      {loading && <p className="mb-4 rounded-lg bg-blue-50 p-3 text-xs text-blue-800">Đang tìm kiếm...</p>}

      <Panel title="Kết quả" description={hasSearched ? `${totalResults} kết quả cho "${searchedQuery}"` : "Nhập từ khóa để bắt đầu tìm kiếm."}>
        <div className="space-y-5 p-4">
          {documents.length > 0 && (
            <section>
              <h2 className="section-title mb-3">Tài liệu</h2>
              <div className="grid gap-3">
                {documents.map(item => <DocumentResult key={item.id || item.title} item={item} />)}
              </div>
            </section>
          )}

          {secondaryGroups.map(group => (
            <section key={group.title}>
              <h2 className="section-title mb-3 flex items-center gap-2">{group.icon}{group.title}</h2>
              <div className="grid gap-3 lg:grid-cols-2">
                {group.items.map(item => <GenericResult key={`${item.source}:${item.id || item.title}`} item={item} />)}
              </div>
            </section>
          ))}

          {!loading && hasSearched && totalResults === 0 && (
            <EmptyState title="Không tìm thấy kết quả phù hợp." description="Hãy thử từ khóa khác hoặc kiểm tra phạm vi quyền truy cập của bạn." />
          )}

          {!hasSearched && (
            <EmptyState title="Nhập từ khóa tìm kiếm" description="Bạn có thể tìm theo tên tài liệu, học phần, chủ đề hoặc giảng viên." />
          )}
        </div>
      </Panel>
    </div>
  );
}

function DocumentResult({ item }: { item: HydratedDocument }) {
  const detail = item.detail;
  const href = item.href || (item.id ? `/documents/${item.id}` : "");
  const title = detail?.title || item.title;
  const topic = detail?.topic || parseDescription(item.description)[0] || "Chưa có dữ liệu";
  const docType = detail?.doc_type || parseDescription(item.description)[1] || "Chưa có dữ liệu";
  const visibility = detail?.visibility || parseDescription(item.description)[2] || "";
  const owner = detail?.owner_code || "Chưa có dữ liệu";
  const version = detail?.current_version ? `v${detail.current_version}` : "Chưa có dữ liệu";

  const body = (
    <article className="rounded-lg border border-[var(--border)] p-4 transition hover:border-blue-300 hover:bg-blue-50/40">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-600"><FileText size={18} /></div>
        <div className="min-w-0 flex-1">
          <strong className="block text-sm">{title}</strong>
          <p className="muted mt-1 text-xs">{item.description || "Không có trích dẫn ngắn."}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            <Meta label="Chủ đề" value={topic} />
            <Meta label="Chủ sở hữu" value={owner} />
            <Meta label="Loại tài liệu" value={docType} />
            <Meta label="Phiên bản" value={version} />
            <Meta label="Phạm vi truy cập" value={visibility ? visibilityLabel(visibility) : "Chưa có dữ liệu"} />
          </div>
          {item.updated_time && <p className="muted mt-3 text-[10px]">Cập nhật: {formatDate(item.updated_time)}</p>}
        </div>
      </div>
    </article>
  );

  return href ? <Link href={href}>{body}</Link> : body;
}

function GenericResult({ item }: { item: GlobalResult }) {
  const content = (
    <article className="rounded-lg border border-[var(--border)] p-4 transition hover:border-blue-300 hover:bg-blue-50/40">
      <strong className="block text-sm">{item.title}</strong>
      <p className="muted mt-1 text-xs">{item.description || "Không có mô tả."}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <span className="badge badge-blue">{typeLabel(item.type)}</span>
        <span className="badge badge-amber">{sourceLabel(item.source)}</span>
        {item.updated_time && <span className="badge badge-green">{formatDate(item.updated_time)}</span>}
      </div>
    </article>
  );
  return item.href ? <Link href={item.href}>{content}</Link> : content;
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-[var(--soft)] px-3 py-2">
      <span className="muted block text-[10px] font-bold uppercase">{label}</span>
      <strong className="mt-1 block text-xs">{value}</strong>
    </div>
  );
}

function parseDescription(value: string) {
  return value.split(" - ").map(item => item.trim()).filter(Boolean);
}

function visibilityLabel(value: string) {
  if (value === "public") return "Công khai";
  if (value === "private") return "Riêng tư";
  return value;
}

function typeLabel(value: string) {
  const labels: Record<string, string> = {
    Course: "Học phần",
    Specialization: "Nhóm chuyên môn",
    Lecturer: "Giảng viên",
    "Governance Rule": "Quy tắc quản trị",
    Policy: "Ch?nh s?ch",
    "Policy Item": "Mục policy",
    Assignment: "Phân công",
    Audit: "Nhật ký",
  };
  return labels[value] || value;
}

function sourceLabel(value: string) {
  const labels: Record<string, string> = {
    documents: "Tài liệu",
    folder_nodes: "Cây thư mục",
    courses: "Học phần",
    specializations: "Nhóm chuyên môn",
    users: "Người dùng",
    policy_rules: "Quy tắc",
    policy_files: "Ch?nh s?ch",
    lecturer_assignments: "Phân công",
    audit_logs: "Nhật ký",
  };
  return labels[value] || value;
}

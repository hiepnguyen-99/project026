"use client";

import Link from "next/link";
import { ArchiveRestore, FileText, LoaderCircle, RefreshCw, ShieldAlert, Trash2 } from "lucide-react";
import { useState } from "react";
import { EmptyState, PageHeader, Panel } from "@/components/ui";
import { useAuth } from "@/components/auth-provider";
import { formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";

type DeletedDocument = {
  id: string;
  title: string;
  doc_type?: string;
  topic?: string;
  owner_code: string;
  visibility?: "public" | "private" | string;
  status?: string;
  current_version?: number;
  deleted_at?: string;
  updated_at?: string;
};

export default function TrashPage() {
  const { user, request } = useAuth();
  const { data: documents, loading, error, reload } = useBackendData<DeletedDocument[]>("/api/trash", []);
  const [busyId, setBusyId] = useState("");
  const [message, setMessage] = useState("");

  const isAdmin = user?.role === "admin";

  async function restore(document: DeletedDocument) {
    setBusyId(document.id);
    setMessage("");
    try {
      await request(`/api/trash/${document.id}/restore`, { method: "POST" });
      await reload();
      setMessage(`Đã khôi phục "${document.title}".`);
    } catch (err) {
      setMessage(errorMessage(err, "Không thể khôi phục tài liệu."));
    } finally {
      setBusyId("");
    }
  }

  async function permanentlyDelete(document: DeletedDocument) {
    if (!confirm(`Xóa vĩnh viễn "${document.title}"? Thao tác này không thể hoàn tác.`)) return;
    setBusyId(document.id);
    setMessage("");
    try {
      await request(`/api/trash/${document.id}`, { method: "DELETE" });
      await reload();
      setMessage(`Đã xóa vĩnh viễn "${document.title}".`);
    } catch (err) {
      setMessage(errorMessage(err, "Không thể xóa vĩnh viễn tài liệu."));
    } finally {
      setBusyId("");
    }
  }

  function canRestore(document: DeletedDocument) {
    return isAdmin || document.owner_code === user?.code;
  }

  return (
    <div>
      <PageHeader
        eyebrow="Vòng đời tài liệu"
        title="Thùng rác"
        description="Quản lý các tài liệu đã xóa mềm trước khi khôi phục hoặc xóa vĩnh viễn."
        actions={<button className="btn-secondary" onClick={reload} disabled={loading}><RefreshCw size={15} />Làm mới</button>}
      />

      {(error || message) && (
        <p className={`mb-4 rounded-lg p-3 text-xs ${error ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-800"}`}>
          {error || message}
        </p>
      )}

      <Panel title="Tài liệu đã xóa" description={loading ? "Đang tải dữ liệu thùng rác..." : `${documents.length} tài liệu trong thùng rác`}>
        {documents.length ? (
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tên tài liệu</th>
                  <th>Chủ sở hữu</th>
                  <th>Ngày xóa</th>
                  <th>Phiên bản hiện tại</th>
                  <th>Trạng thái</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {documents.map(document => {
                  const busy = busyId === document.id;
                  return (
                    <tr key={document.id}>
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-red-50 text-red-600"><FileText size={16} /></div>
                          <div className="min-w-0">
                            <strong className="block truncate">{document.title}</strong>
                            <span className="muted block text-[10px]">{[document.topic, document.doc_type].filter(Boolean).join(" · ") || "Chưa có phân loại"}</span>
                          </div>
                        </div>
                      </td>
                      <td>{document.owner_code}</td>
                      <td>{document.deleted_at ? formatDate(document.deleted_at) : "Chưa có dữ liệu"}</td>
                      <td>v{document.current_version ?? "?"}</td>
                      <td>
                        <div className="flex flex-wrap gap-1">
                          {document.visibility && <span className={`badge ${document.visibility === "public" ? "badge-green" : "badge-amber"}`}>{visibilityLabel(document.visibility)}</span>}
                          {document.status && <span className="badge badge-blue">{statusLabel(document.status)}</span>}
                          {!document.visibility && !document.status && <span className="muted text-xs">Chưa có dữ liệu</span>}
                        </div>
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-2">
                          {canRestore(document) && (
                            <button className="btn-secondary px-2 py-1 text-[11px]" onClick={() => restore(document)} disabled={busy}>
                              {busy ? <LoaderCircle className="animate-spin" size={13} /> : <ArchiveRestore size={13} />}Khôi phục
                            </button>
                          )}
                          {isAdmin && (
                            <button className="btn-secondary px-2 py-1 text-[11px] text-red-600" onClick={() => permanentlyDelete(document)} disabled={busy}>
                              {busy ? <LoaderCircle className="animate-spin" size={13} /> : <Trash2 size={13} />}Xóa vĩnh viễn
                            </button>
                          )}
                          {!canRestore(document) && !isAdmin && <span className="muted text-xs">Không có thao tác khả dụng</span>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Thùng rác đang trống." description="Không có tài liệu đã xóa trong phạm vi quyền của bạn." />
        )}
      </Panel>

      <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
        <div className="flex items-start gap-2">
          <ShieldAlert size={16} className="mt-0.5 shrink-0" />
          <p>
            Xóa vĩnh viễn chỉ dành cho quản trị viên. Khôi phục phụ thuộc quyền sở hữu tài liệu; nếu backend từ chối quyền, thông báo lỗi sẽ hiển thị tại trang này.
          </p>
        </div>
      </div>

      <div className="mt-5">
        <Link href="/repository" className="btn-secondary">Quay lại kho tài liệu</Link>
      </div>
    </div>
  );
}

function visibilityLabel(value: string) {
  if (value === "public") return "Công khai";
  if (value === "private") return "Riêng tư";
  return value;
}

function statusLabel(value: string) {
  if (value === "INDEXED") return "Đã lập chỉ mục";
  if (value === "PROCESSING") return "Đang xử lý";
  if (value === "UPLOADED") return "Đã tải lên";
  if (value === "FAILED") return "Xử lý thất bại";
  return value;
}

function errorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

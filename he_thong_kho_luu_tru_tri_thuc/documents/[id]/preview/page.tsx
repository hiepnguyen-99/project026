"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, Download, ExternalLink, FileText, LoaderCircle, ScanText } from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { PageHeader, Panel } from "@/components/ui";
import { API_URL, Document, DocumentDetail, formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";

type Provenance = {
  document: Document;
  versions: { id: string; version_no: number; created_by: string; created_at: string }[];
  sync_history: { id: string; status: string; detail: string; created_at: string }[];
  files: { id: string; version_no: number; original_name: string; mime_type: string; size: number; created_at: string }[];
  access: { type: "public" | "owner" | "approved_request"; request_id: string | null };
};

const emptyProvenance: Provenance = {
  document: {
    id: "",
    title: "",
    doc_type: "",
    topic: "",
    owner_code: "",
    visibility: "public",
    current_version: 0,
    created_at: "",
    updated_at: "",
    folder_path: "",
  },
  versions: [],
  sync_history: [],
  files: [],
  access: { type: "public", request_id: null },
};

const emptyDetail: DocumentDetail = {
  id: "",
  title: "",
  doc_type: "",
  topic: "",
  owner_code: "",
  visibility: "public",
  current_version: 0,
  created_at: "",
  updated_at: "",
  folder_path: "",
  content: "",
};

function isPdf(mime?: string, name?: string) {
  const m = (mime || "").toLowerCase();
  const n = (name || "").toLowerCase();
  return m.includes("pdf") || n.endsWith(".pdf");
}

function isImage(mime?: string, name?: string) {
  const m = (mime || "").toLowerCase();
  const n = (name || "").toLowerCase();
  return m.startsWith("image/") || n.endsWith(".png") || n.endsWith(".jpg") || n.endsWith(".jpeg") || n.endsWith(".webp");
}

export default function DocumentPreviewPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();

  const doc = useBackendData<DocumentDetail>(`/api/documents/${id}`, emptyDetail);
  const prov = useBackendData<Provenance>(`/api/documents/${id}/provenance`, emptyProvenance);

  const selectedFile = useMemo(() => {
    const files = prov.data.files || [];
    if (!files.length) return null;
    return [...files].sort((a, b) => b.version_no - a.version_no)[0];
  }, [prov.data.files]);

  const [previewUrl, setPreviewUrl] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");

  // Load file -> create blob: URL to preview in <iframe>/<img>.
  useEffect(() => {
    let objectUrl = "";

    async function load() {
      setPreviewError("");
      setPreviewUrl("");

      if (!selectedFile?.id) return;
      if (!token) {
        setPreviewError("Bạn chưa đăng nhập hoặc phiên đăng nhập đã hết hạn.");
        return;
      }

      setPreviewLoading(true);
      try {
        const r = await fetch(`${API_URL}/api/files/${selectedFile.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (!r.ok) {
          setPreviewError(`Không thể tải tệp gốc (HTTP ${r.status}).`);
          return;
        }

        const blob = await r.blob();
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
      } catch (e) {
        setPreviewError(e instanceof Error ? e.message : "Không thể tải tệp gốc.");
      } finally {
        setPreviewLoading(false);
      }
    }

    void load();

    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selectedFile?.id, token]);

  async function downloadOriginal() {
    if (!selectedFile?.id || !token) return;

    const r = await fetch(`${API_URL}/api/files/${selectedFile.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) return;

    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = selectedFile.original_name;
    a.click();
    URL.revokeObjectURL(url);
  }

  const anyError = doc.error || prov.error;

  if (anyError) {
    return (
      <div>
        <PageHeader
          eyebrow="Preview tài liệu"
          title="Không thể mở tài liệu"
          description="Bạn cần được chủ sở hữu phê duyệt trước khi xem nội dung hoặc tải tài liệu riêng tư."
          actions={
            <Link className="btn-secondary" href="/permissions">
              <ChevronLeft size={15} />
              Gửi yêu cầu truy cập
            </Link>
          }
        />
        <p className="rounded bg-red-50 p-4 text-sm text-red-700">{anyError}</p>
      </div>
    );
  }

  const loading = doc.loading || prov.loading;

  return (
    <div>
      <PageHeader
        eyebrow="Preview tài liệu (file gốc + bản số hoá)"
        title={prov.data.document.title || doc.data.title || "Đang tải..."}
        description={`${prov.data.document.doc_type || doc.data.doc_type} · v${
          prov.data.document.current_version || doc.data.current_version || 0
        } · ${prov.data.document.owner_code || doc.data.owner_code}`}
        actions={
          <>
            <Link className="btn-secondary" href="/assistant">
              <ChevronLeft size={15} />
              Quay lại Trợ lý
            </Link>

            <Link className="btn-secondary" href={`/documents/${id}`}>
              <FileText size={15} />
              Trang chi tiết
            </Link>

            {selectedFile && (
              <>
                <button className="btn-secondary" onClick={downloadOriginal} title="Tải xuống file gốc">
                  <Download size={15} />
                  Tải xuống
                </button>

                {previewUrl && (
                  <a className="btn-primary" href={previewUrl} target="_blank" rel="noreferrer" title="Mở file gốc">
                    <ExternalLink size={15} />
                    Mở file
                  </a>
                )}
              </>
            )}
          </>
        }
      />

      {prov.data.access.type === "approved_request" && (
        <p className="mb-4 rounded bg-blue-50 p-3 text-xs text-blue-800">
          Bạn đang xem tài liệu riêng tư này nhờ yêu cầu truy cập đã được phê duyệt.
        </p>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        {/* LEFT: original file preview */}
        <Panel
          title="Preview tệp gốc"
          description={selectedFile ? `${selectedFile.original_name} · ${Math.ceil(selectedFile.size / 1024)} KB` : "Không có tệp gốc"}
        >
          <div className="p-4">
            {loading ? (
              <div className="muted flex items-center gap-2 text-sm">
                <LoaderCircle className="animate-spin" size={16} />
                Đang tải…
              </div>
            ) : !selectedFile ? (
              <p className="muted text-sm">Tài liệu này chưa có tệp gốc.</p>
            ) : previewError ? (
              <p className="rounded bg-red-50 p-3 text-sm text-red-700">{previewError}</p>
            ) : previewLoading ? (
              <div className="muted flex items-center gap-2 text-sm">
                <LoaderCircle className="animate-spin" size={16} />
                Đang tải preview tệp gốc…
              </div>
            ) : !previewUrl ? (
              <p className="muted text-sm">Chưa có preview.</p>
            ) : isPdf(selectedFile.mime_type, selectedFile.original_name) ? (
              <iframe
                src={previewUrl}
                className="h-[70vh] w-full rounded-lg border border-[var(--border)] bg-white"
                title="PDF preview"
              />
            ) : isImage(selectedFile.mime_type, selectedFile.original_name) ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={previewUrl}
                alt={selectedFile.original_name}
                className="max-h-[70vh] w-full rounded-lg border border-[var(--border)] object-contain bg-white"
              />
            ) : (
              <div className="rounded-lg border border-[var(--border)] bg-[var(--soft)] p-4">
                <p className="text-sm">
                  Định dạng <strong>{selectedFile.mime_type || "không rõ"}</strong> hiện chưa hỗ trợ preview trực tiếp.
                </p>
                <p className="muted mt-1 text-xs">Bạn vẫn có thể bấm “Tải xuống” hoặc “Mở file”.</p>
              </div>
            )}

            {selectedFile && (
              <p className="muted mt-3 text-xs">
                Upload lúc: <strong>{formatDate(selectedFile.created_at)}</strong>
              </p>
            )}
          </div>
        </Panel>

        {/* RIGHT: digitized/OCR text */}
        <Panel title="Bản số hoá (extract/OCR text)" description="Text hệ thống dùng để tìm kiếm / RAG">
          <div className="p-4">
            {loading ? (
              <div className="muted flex items-center gap-2 text-sm">
                <LoaderCircle className="animate-spin" size={16} />
                Đang tải…
              </div>
            ) : (
              <>
                <div className="muted mb-3 flex items-center gap-2 text-xs">
                  <ScanText size={15} />
                  Nội dung trong field <code>content</code> của <code>/api/documents/{`{id}`}</code>
                </div>

                <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-white p-4 text-sm leading-6">
                  {doc.data.content?.trim() ? doc.data.content : "Chưa có nội dung số hoá."}
                </pre>
              </>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
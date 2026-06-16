"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, ExternalLink, LoaderCircle, ScanText } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { Panel } from "@/components/ui";
import { API_URL, formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";

type FileAsset = {
  id: string;
  version_no: number;
  original_name: string;
  mime_type: string;
  size: number;
  created_at: string;
};

type DocDetail = {
  content?: string;
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

export default function DocumentInlinePreview({
  documentId,
  files,
}: {
  documentId: string;
  files: FileAsset[];
}) {
  const { token } = useAuth();

  const { data: doc, error: docError } = useBackendData<DocDetail>(`/api/documents/${documentId}`, { content: "" });

  const sortedFiles = useMemo(() => {
    return [...(files || [])].sort((a, b) => {
      const byVersion = (b.version_no || 0) - (a.version_no || 0);
      if (byVersion) return byVersion;
      return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
    });
  }, [files]);

  const [selectedId, setSelectedId] = useState<string>("");

  useEffect(() => {
    if (!selectedId && sortedFiles[0]?.id) setSelectedId(sortedFiles[0].id);
  }, [sortedFiles, selectedId]);

  const selectedFile = useMemo(() => {
    return sortedFiles.find((f) => f.id === selectedId) || sortedFiles[0];
  }, [sortedFiles, selectedId]);

  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");

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
          throw new Error("Không thể tải tệp gốc.");
        }

        objectUrl = URL.createObjectURL(await r.blob());
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

  return (
    <div id="document-preview" className="mt-6">
      <h3 className="section-title mb-3">Xem trước tài liệu</h3>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Panel
          title="Preview tệp gốc"
          description={
            selectedFile
              ? `${selectedFile.original_name} · ${Math.ceil((selectedFile.size || 0) / 1024)} KB`
              : "Không có tệp gốc"
          }
        >
          <div className="p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <select
                className="h-9 rounded-md border border-[var(--border)] bg-white px-3 text-xs"
                value={selectedFile?.id || ""}
                onChange={(e) => setSelectedId(e.target.value)}
                disabled={!sortedFiles.length}
                title="Chọn tệp để xem trước"
              >
                {sortedFiles.map((f) => (
                  <option key={f.id} value={f.id}>
                    v{f.version_no} · {f.original_name}
                  </option>
                ))}
              </select>

              <button
                className="btn-secondary"
                onClick={downloadOriginal}
                disabled={!selectedFile}
                title="Tải xuống file gốc"
              >
                <Download size={15} />
                Tải xuống
              </button>

              {previewUrl && (
                <a className="btn-primary" href={previewUrl} target="_blank" rel="noreferrer" title="Mở file gốc">
                  <ExternalLink size={15} />
                  Mở file
                </a>
              )}
            </div>

            {!sortedFiles.length ? (
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
            ) : isPdf(selectedFile?.mime_type, selectedFile?.original_name) ? (
              <iframe
                src={previewUrl}
                className="h-[70vh] w-full rounded-lg border border-[var(--border)] bg-white"
                title="PDF preview"
              />
            ) : isImage(selectedFile?.mime_type, selectedFile?.original_name) ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={previewUrl}
                alt={selectedFile?.original_name || "preview"}
                className="max-h-[70vh] w-full rounded-lg border border-[var(--border)] object-contain bg-white"
              />
            ) : (
              <div className="rounded-lg border border-[var(--border)] bg-[var(--soft)] p-4">
                <p className="text-sm">
                  Định dạng <strong>{selectedFile?.mime_type || "không rõ"}</strong> hiện chưa hỗ trợ preview trực tiếp.
                </p>
                <p className="muted mt-1 text-xs">Bạn vẫn có thể bấm “Tải xuống” hoặc “Mở file”.</p>
              </div>
            )}

            {selectedFile?.created_at && (
              <p className="muted mt-3 text-xs">
                Upload lúc: <strong>{formatDate(selectedFile.created_at)}</strong>
              </p>
            )}
          </div>
        </Panel>

        <Panel title="Bản số hoá (extract/OCR text)" description="Text hệ thống dùng để tìm kiếm / RAG">
          <div className="p-4">
            <div className="muted mb-3 flex items-center gap-2 text-xs">
              <ScanText size={15} />
              Nội dung trong field <code>content</code> của <code>/api/documents/{documentId}</code>
            </div>

            {docError ? (
              <p className="rounded bg-red-50 p-3 text-sm text-red-700">{docError}</p>
            ) : (
              <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-white p-4 text-sm leading-6">
                {doc?.content?.trim() ? doc.content : "Chưa có nội dung số hoá."}
              </pre>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
"use client";

import { useEffect, useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { API_URL } from "@/lib/api";

type FileAsset = {
  id: string;
  version_no: number;
  original_name: string;
  mime_type: string;
  size: number;
  created_at: string;
};

function isPdf(mime?: string, name?: string) {
  const m = (mime || "").toLowerCase();
  const n = (name || "").toLowerCase();
  return m.includes("pdf") || n.endsWith(".pdf");
}

export default function DocumentInlinePreview({
  documentId, // giữ prop để không phá interface nơi khác đang truyền vào
  files,
}: {
  documentId: string;
  files: FileAsset[];
}) {
  const { token } = useAuth();

  const sortedFiles = useMemo(() => {
    return [...(files || [])].sort((a, b) => {
      const byVersion = (b.version_no || 0) - (a.version_no || 0);
      if (byVersion) return byVersion;
      return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
    });
  }, [files]);

  // Chỉ chọn PDF (mới nhất) để preview
  const selectedFile = useMemo(() => {
    if (!sortedFiles.length) return null;
    return sortedFiles.find((f) => isPdf(f.mime_type, f.original_name)) || null;
  }, [sortedFiles]);

  const [previewUrl, setPreviewUrl] = useState("");
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

        if (!r.ok) throw new Error("Không thể tải tệp PDF.");

        objectUrl = URL.createObjectURL(await r.blob());
        setPreviewUrl(objectUrl);
      } catch (e) {
        setPreviewError(e instanceof Error ? e.message : "Không thể tải tệp PDF.");
      } finally {
        setPreviewLoading(false);
      }
    }

    void load();

    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selectedFile?.id, token]);

  // Không có file
  if (!sortedFiles.length) {
    return <div className="mt-6 text-sm muted">Tài liệu này chưa có tệp gốc.</div>;
  }

  // Có file nhưng không có PDF
  if (!selectedFile) {
    return <div className="mt-6 text-sm muted">Tài liệu này chưa có tệp PDF để xem trực tiếp.</div>;
  }

  // Loading
  if (previewLoading) {
    return (
      <div className="mt-6 flex w-full items-center gap-2 text-sm muted">
        <LoaderCircle className="animate-spin" size={16} />
        Đang tải PDF…
      </div>
    );
  }

  // Error
  if (previewError) {
    return <div className="mt-6 rounded bg-red-50 p-3 text-sm text-red-700">{previewError}</div>;
  }

  if (!previewUrl) return null;

  // PDF-only view
  return (
    <iframe
      src={previewUrl}
      className="mt-6 h-[80vh] w-full rounded-lg border border-[var(--border)] bg-white"
      title={selectedFile.original_name || "PDF preview"}
    />
  );
}
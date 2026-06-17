"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronUp, LoaderCircle, RefreshCw, Trash2, UploadCloud, XCircle } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { api, API_URL } from "@/lib/api";

export type UploadMetadata = {
  title: string;
  topic: string;
  doc_type: string;
  visibility: "public" | "private";
  folder_path?: string;
  folder_node_id?: string;
  existing_document_id?: string;
  ai_metadata?: {
    title: string;
    topic: string;
    doc_type: string;
    summary?: string;
    keywords?: string[];
  };
  applied_metadata?: {
    title: string;
    topic: string;
    doc_type: string;
    visibility: "public" | "private";
    folder_path: string;
  };
  quick_suggestion?: {
    specialization?: string;
    course?: string;
    confidence?: number;
    folder_path?: string;
  };
  classification_ticket?: {
    id: string;
    filename: string;
    suggested_specialization_id?: string;
    suggested_specialization?: string;
    suggested_course_id?: string;
    suggested_course?: string;
    suggested_document_type?: string;
    suggested_visibility: "public" | "private";
    confidence: number;
    reasoning: string;
    suggestions: { specialization_id: string; specialization: string; course_id: string; course: string; confidence: number }[];
    status: "PENDING_CONFIRMATION" | "CONFIRMED";
    document_id?: string;
  };
};

export type UploadTask = {
  id: string;
  filename: string;
  mime_type: string;
  total_bytes: number;
  uploaded_bytes: number;
  status: "uploading" | "uploaded" | "analyzing" | "saving_metadata" | "pending_confirmation" | "processing" | "completed" | "failed";
  metadata: UploadMetadata;
  document_id?: string;
  error?: string;
  created_at: string;
  updated_at: string;
};

type UploadContextValue = {
  tasks: UploadTask[];
  startUpload: (file: File, metadata: UploadMetadata) => Promise<string>;
  retryUpload: (taskId: string) => Promise<void>;
  removeTask: (taskId: string, skipConfirm?: boolean) => Promise<void>;
};

const UploadContext = createContext<UploadContextValue | null>(null);
const CHUNK_SIZE = 5 * 1024 * 1024;

const statusLabels: Record<UploadTask["status"], string> = {
  uploading: "Đang tải lên",
  uploaded: "Đã tải file gốc",
  analyzing: "Đang AI phân tích",
  saving_metadata: "Đang lưu metadata",
  pending_confirmation: "Chờ xác nhận phân loại",
  processing: "Đã lưu, AI đang xử lý",
  completed: "Đã lưu, AI xử lý nền",
  failed: "Thất bại",
};

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function UploadTaskProvider({ children }: { children: React.ReactNode }) {
  const { token, user } = useAuth();
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const [open, setOpen] = useState(true);
  const files = useRef(new Map<string, File>());

  const mergeTask = useCallback((incoming: UploadTask) => {
    setTasks(current => {
      const existing = current.find(task => task.id === incoming.id);
      const next = existing?.status === "failed" && incoming.status === "uploading"
        ? existing
        : existing && existing.status === "uploading"
        ? { ...incoming, uploaded_bytes: Math.max(existing.uploaded_bytes, incoming.uploaded_bytes) }
        : incoming;
      return [next, ...current.filter(task => task.id !== incoming.id)].slice(0, 20);
    });
  }, []);

  useEffect(() => {
    if (!token || !user) {
      setTasks([]);
      files.current.clear();
      return;
    }
    let active = true;
    async function refresh() {
      try {
        const result = await api<UploadTask[]>("/api/uploads", {}, token);
        if (active) result.reverse().forEach(mergeTask);
      } catch {}
    }
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [mergeTask, token, user]);

  function uploadChunk(taskId: string, file: File, offset: number, chunk: Blob) {
    return new Promise<UploadTask>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_URL}/api/uploads/${taskId}/file`);
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.setRequestHeader("X-Upload-Offset", String(offset));
      xhr.upload.onprogress = event => {
        const uploaded = Math.min(file.size, offset + event.loaded);
        setTasks(current => current.map(task => task.id === taskId ? { ...task, uploaded_bytes: uploaded, status: "uploading" } : task));
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText) as UploadTask);
        else {
          try {
            reject(new Error(JSON.parse(xhr.responseText).detail || `Upload thất bại HTTP ${xhr.status}.`));
          } catch {
            reject(new Error(`Upload thất bại HTTP ${xhr.status}.`));
          }
        }
      };
      xhr.onerror = () => reject(new Error("Mất kết nối khi đang tải file."));
      xhr.send(chunk);
    });
  }

  const continueUpload = useCallback(async (task: UploadTask, file: File) => {
    try {
      let offset = task.uploaded_bytes;
      while (offset < file.size) {
        const updated = await uploadChunk(task.id, file, offset, file.slice(offset, Math.min(file.size, offset + CHUNK_SIZE)));
        offset = updated.uploaded_bytes;
        mergeTask(updated);
      }
      const analyzing = await api<UploadTask>(`/api/uploads/${task.id}/analyze`, { method: "POST" }, token);
      mergeTask(analyzing);
    } catch (error) {
      setTasks(current => current.map(item => item.id === task.id ? {
        ...item,
        status: "failed",
        error: error instanceof Error ? error.message : "Upload thất bại.",
      } : item));
    }
  }, [mergeTask, token]);

  async function startUpload(file: File, metadata: UploadMetadata) {
    const task = await api<UploadTask>("/api/uploads/init", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        mime_type: file.type || "application/octet-stream",
        total_bytes: file.size,
        ...metadata,
      }),
    }, token);
    files.current.set(task.id, file);
    mergeTask(task);
    setOpen(true);
    void continueUpload(task, file);
    return task.id;
  }

  async function retryUpload(taskId: string) {
    const task = tasks.find(item => item.id === taskId);
    if (!task) return;
    if (task.uploaded_bytes >= task.total_bytes) {
      try {
        mergeTask(await api<UploadTask>(`/api/uploads/${task.id}/analyze`, { method: "POST" }, token));
      } catch (error) {
        setTasks(current => current.map(item => item.id === task.id ? { ...item, error: error instanceof Error ? error.message : "Không thể thử lại." } : item));
      }
      return;
    }
    const file = files.current.get(task.id);
    if (file) {
      const retrying = { ...task, status: "uploading" as const, error: "" };
      mergeTask(retrying);
      void continueUpload(retrying, file);
    }
    else setTasks(current => current.map(item => item.id === task.id ? { ...item, error: "Hãy chọn lại file để thử tải lên từ đầu." } : item));
  }

  async function removeTask(taskId: string, skipConfirm = false) {
    const task = tasks.find(item => item.id === taskId);
    const message = task?.document_id || task?.status === "completed"
      ? "Xóa tác vụ này khỏi danh sách Upload gần đây?"
      : "Bạn có chắc muốn hủy file upload này không?";
    if (!skipConfirm && !window.confirm(message)) return;
    try {
      await api(`/api/uploads/${taskId}`, { method: "DELETE" }, token);
      files.current.delete(taskId);
      setTasks(current => current.filter(item => item.id !== taskId));
    } catch (error) {
      setTasks(current => current.map(item => item.id === taskId ? {
        ...item,
        error: error instanceof Error ? error.message : "Không thể xóa tác vụ upload.",
      } : item));
    }
  }

  return <UploadContext.Provider value={{ tasks, startUpload, retryUpload, removeTask }}>
    {children}
    <div className="fixed bottom-4 right-4 z-[80] w-[min(390px,calc(100vw-2rem))] app-card overflow-hidden shadow-xl">
      <button className="flex w-full items-center gap-2 border-b border-[var(--border)] px-4 py-3 text-left" onClick={() => setOpen(value => !value)}>
        <UploadCloud className="text-blue-600" size={17}/>
        <strong className="text-sm">Upload gần đây</strong>
        <span className="badge badge-blue ml-auto">{tasks.filter(task => !["completed", "failed"].includes(task.status)).length}</span>
        {open ? <ChevronDown size={16}/> : <ChevronUp size={16}/>}
      </button>
      {open && <div className="max-h-[430px] space-y-2 overflow-y-auto p-3">
        {!tasks.length && <p className="muted p-3 text-center text-xs">Chưa có tác vụ upload. Bạn có thể tiếp tục làm việc khi file đang được xử lý.</p>}
        {tasks.slice(0, 8).map(task => {
          const progress = Math.round(task.uploaded_bytes / task.total_bytes * 100);
          const active = !["completed", "failed"].includes(task.status);
          const canCancel = ["pending_confirmation", "failed"].includes(task.status);
          return <div key={task.id} className="rounded-xl border border-[var(--border)] p-3">
            <div className="flex items-start gap-2">
              {task.status === "completed" ? <CheckCircle2 className="mt-0.5 text-green-600" size={16}/> : task.status === "failed" ? <XCircle className="mt-0.5 text-red-600" size={16}/> : <LoaderCircle className="mt-0.5 animate-spin text-blue-600" size={16}/>}
              <div className="min-w-0 flex-1"><strong className="block truncate text-xs">{task.filename}</strong><span className="muted text-[10px]">{statusLabels[task.status]}</span></div>
              {task.status === "failed" && <button className="btn-secondary px-2 py-1 text-[10px]" onClick={() => retryUpload(task.id)}><RefreshCw size={11}/>Thử lại</button>}
              {canCancel && <button className="btn-secondary px-2 py-1 text-[10px] text-red-600" onClick={() => removeTask(task.id)}><Trash2 size={11}/>Hủy upload</button>}
              {!active && !canCancel && <button className="icon-btn h-7 w-7" aria-label="Xóa tác vụ" onClick={() => removeTask(task.id)}><Trash2 size={12}/></button>}
            </div>
            <div className="progress mt-3"><i style={{ width: `${active ? progress : 100}%` }} className={task.status === "failed" ? "!bg-red-500" : task.status === "completed" ? "!bg-green-500" : ""}/></div>
            <div className="muted mt-1 flex justify-between text-[10px]"><span>{formatBytes(task.uploaded_bytes)} / {formatBytes(task.total_bytes)}</span><span>{progress}%</span></div>
            {task.metadata.ai_metadata && <div className="mt-2 rounded-lg bg-[var(--soft)] p-2 text-[10px]">
              <strong className="block text-blue-700">Nhãn AI đã gán</strong>
              <span className="muted">{task.metadata.ai_metadata.topic} · {task.metadata.ai_metadata.doc_type}</span>
            </div>}
            {task.error && <p className="mt-2 text-[10px] text-red-600">{task.error}</p>}
          </div>;
        })}
      </div>}
    </div>
  </UploadContext.Provider>;
}

export function useUploadTasks() {
  const value = useContext(UploadContext);
  if (!value) throw new Error("useUploadTasks must be used inside UploadTaskProvider");
  return value;
}

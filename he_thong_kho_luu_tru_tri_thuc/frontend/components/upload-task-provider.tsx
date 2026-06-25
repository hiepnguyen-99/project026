"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
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

export function UploadTaskProvider({ children }: { children: React.ReactNode }) {
  const { token, user } = useAuth();
  const [tasks, setTasks] = useState<UploadTask[]>([]);
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
      ? "Xóa thông báo upload này?"
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
  </UploadContext.Provider>;
}

export function useUploadTasks() {
  const value = useContext(UploadContext);
  if (!value) throw new Error("useUploadTasks must be used inside UploadTaskProvider");
  return value;
}

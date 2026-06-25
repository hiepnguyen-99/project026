// Same-origin requests are proxied by Next.js. Set NEXT_PUBLIC_API_URL only
// when the browser intentionally calls an API exposed on a separate domain.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

export type User = {
  code: string;
  name: string;
  role: "lecturer" | "new_lecturer" | "head" | "admin";
  department: string;
  permissions: string[];
};

export type Document = {
  id: string;
  title: string;
  doc_type: string;
  topic: string;
  status?: "UPLOADED" | "PROCESSING" | "INDEXED" | "FAILED";
  owner_code: string;
  visibility: "public" | "private";
  current_version: number;
  created_at: string;
  updated_at: string;
  folder_path: string;
  folder_node_id?: string;
  owner_anonymous?: boolean;
  v2_state?: {
    classification: string;
    lifecycle_status: string;
    scan_status: string;
    extraction_status: string;
    indexing_status: string;
    publish_after?: string;
  };
};

export type V2Status = {
  architecture: string;
  database: string;
  ready: boolean;
  scope: string;
  capacity_target_gb: number;
  rpo_target_minutes: number;
  rto_target_hours: number;
  services: Record<string, { provider: string; configured: boolean; available: boolean; detail?: string }>;
  objects: { provider: string; count: number; size: number }[];
  outbox: { status: string; count: number }[];
};

export type FolderNode = {
  id: string;
  name: string;
  parent_id?: string;
  type: "faculty" | "department" | "specialization" | "course" | "standard_folder" | "folder";
  policy_id: string;
  path: string;
  status: "active" | "deprecated";
  children: FolderNode[];
};

export type ParsedPolicyTree = {
  faculty: string;
  faculty_code?: string;
  specializations: {
    name: string;
    description?: string;
    courses: { name: string; code?: string; description?: string; standard_folders: string[] }[];
  }[];
  standard_folders?: string[];
};

export type PolicyFile = {
  id: string;
  title: string;
  file_path: string;
  status: "draft" | "active" | "archived";
  raw_text: string;
  parsed_json: ParsedPolicyTree;
  created_by: string;
  created_at: string;
  activated_at?: string;
};

export type MyFolderTree = {
  policy: PolicyFile | null;
  name: string;
  children: FolderNode[];
  message?: string;
};

export type Specialization = {
  id: string;
  name: string;
  description: string;
  policy_id?: string;
  folder_node_id?: string;
  courses_count?: number;
};

export type LecturerFolderNode = {
  id: string;
  name: string;
  type: "root" | "specialization" | "course" | "folder" | "standard_folder";
  children: LecturerFolderNode[];
};

export type ProfileSpecializations = {
  policy: PolicyFile | null;
  available: Specialization[];
  selected_ids: string[];
  folder_tree?: LecturerFolderNode;
  message?: string;
};

export type DocumentDetail = Document & {
  content: string;
};

export type DashboardData = {
  user: User;
  stats: { documents: number; private: number; topics: number };
  documents: Document[];
  requests: AccessRequest[];
  backups: Backup[];
  audit: Audit[];
};

export type AccessRequest = {
  id: string;
  document_id: string;
  requester_code: string;
  owner_code: string;
  status: string;
  created_at: string;
};

export type Backup = {
  id: string;
  storage_path: string;
  status: string;
  created_by: string;
  created_at: string;
  manifest?: BackupManifest | null;
};

export type BackupManifest = {
  backup_id: string;
  created_at: string;
  created_by: string;
  checksum_file?: string;
  documents_count: number;
  versions_count: number;
  chunks_count: number;
  file_assets_count: number;
  object_refs_count: number;
  local_storage_size_bytes: number;
  local_storage_files_count: number;
  qdrant_collections_count: number;
  qdrant_vectors_count: number;
  minio_objects_count: number;
  minio_size_bytes: number;
  database_snapshot?: { included: boolean; file: string; size_bytes: number };
  local_storage?: { included: boolean; files_count: number; size_bytes: number };
  qdrant?: { included: boolean; error?: string; collections?: { name: string; vector_count: number; snapshot_size_bytes: number }[] };
  minio?: { included: boolean; error?: string; objects_count: number; size_bytes: number };
  checksum?: { file: string; entries_count: number };
  included_components: { key: string; label: string; included: boolean; error?: string }[];
  sample_documents: { id: string; title: string; topic: string; doc_type: string; owner_code: string; current_version: number; visibility: string; file_name?: string }[];
  sample_files: { document_id: string; version_no: number; original_name: string; mime_type: string; size: number; created_at: string }[];
  restore_scope: Record<string, boolean>;
};

export type Audit = {
  id: number;
  actor_code: string;
  action: string;
  resource_type: string;
  resource_id?: string;
  detail?: Record<string, unknown>;
  created_at: string;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `Máy chủ trả về lỗi HTTP ${response.status}.`;
    try {
      const data = await response.json();
      message = data.detail || data.error || message;
    } catch {}
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export function formatDate(value?: string) {
  if (!value) return "Chưa cập nhật";
  return new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

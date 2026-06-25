"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, ChevronRight, Cloud, FileUp, Folder, FolderOpen, Save, Search, Shield, ShieldCheck, Trash2 } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { useBackendData } from "@/lib/hooks";
import { FolderNode, PolicyFile, ProfileSpecializations } from "@/lib/api";
import { PageHeader, Panel } from "@/components/ui";

type Policy = { key: string; value: Record<string, unknown>; updated_at: string };
type Storage = { id: string; name: string; provider: string; location: string; last_status: string };
type MasterTree = { policy: PolicyFile | null; tree: FolderNode | null; message?: string };

const emptyProfile: ProfileSpecializations = { policy: null, available: [], selected_ids: [] };
const emptyMaster: MasterTree = { policy: null, tree: null };

export default function Settings() {
  const { request, user } = useAuth();
  const { data: policies, error } = useBackendData<Policy[]>("/api/admin/policies", []);
  const { data: storages } = useBackendData<Storage[]>("/api/admin/storages", []);
  const { data: policyFiles, reload: reloadPolicyFiles } = useBackendData<PolicyFile[]>("/api/policies", []);
  const { data: masterTree, reload: reloadMasterTree } = useBackendData<MasterTree>("/api/admin/master-tree", emptyMaster);
  const { data: profile, reload: reloadProfile } = useBackendData<ProfileSpecializations>("/api/profile/specializations", emptyProfile);
  const [policyFile, setPolicyFile] = useState<File | null>(null);
  const [policyTitle, setPolicyTitle] = useState("Policy học liệu khoa CNTT");
  const [message, setMessage] = useState("");
  const permission = policies.find(x => x.key === "permission_rules");
  const assignedSpecializations = profile.available.filter(spec => profile.selected_ids.includes(spec.id));

  async function uploadPolicy() {
    if (!policyFile) return;
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
      await reloadPolicyFiles();
      setMessage("Đã upload policy. Hãy activate policy để cập nhật Master Folder Tree.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không upload được policy.");
    }
  }

  async function activatePolicy(policyId: string) {
    setMessage("");
    try {
      await request(`/api/policies/${policyId}/activate`, { method: "POST" });
      await Promise.all([reloadPolicyFiles(), reloadMasterTree(), reloadProfile()]);
      setMessage("Master Folder Tree đã được cập nhật theo policy active mới.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không activate được policy.");
    }
  }

  async function deletePolicy(policy: PolicyFile) {
    if (!confirm(`Xóa policy "${policy.title}"?`)) return;
    setMessage("");
    try {
      await request(`/api/policies/${policy.id}`, { method: "DELETE" });
      await Promise.all([reloadPolicyFiles(), reloadMasterTree(), reloadProfile()]);
      setMessage("Đã xóa policy.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không xóa được policy.");
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Cài đặt hệ thống"
        title="Cấu hình EduVault"
        description="Quản lý policy, Master Folder Tree và các cấu hình hệ thống."
        actions={<button className="btn-primary"><Save size={15}/>Đã kết nối</button>}
      />
      {(error || message) && (
        <p className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">
          {message || `Chỉ quản trị viên truy cập được một số cấu hình: ${error}`}
        </p>
      )}
      <div className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
        <Panel title="Policy Upload và Master Folder Tree" description="Admin upload policy, activate một bản duy nhất, hệ thống sinh cây chuẩn toàn khoa.">
          <div className="space-y-4 p-4">
            {user?.role === "admin" && (
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
                  <input className="field" value={policyTitle} onChange={event => setPolicyTitle(event.target.value)} placeholder="Tiêu đề policy"/>
                  <label className="btn-secondary cursor-pointer">
                    <FileUp size={15}/>{policyFile?.name || "Chọn file"}
                    <input className="hidden" type="file" accept=".pdf,.docx,.txt,.json,.yaml,.yml" onChange={event => setPolicyFile(event.target.files?.[0] || null)}/>
                  </label>
                </div>
                <button className="btn-primary mt-3" disabled={!policyFile} onClick={uploadPolicy}>Upload policy</button>
              </div>
            )}
            <div className="space-y-2">
              {policyFiles.map(policy => (
                <div key={policy.id} className="rounded-lg border border-[var(--border)] p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Shield size={15} className="text-blue-600"/>
                    <strong className="text-xs">{policy.title}</strong>
                    <span className={`badge ${policy.status === "active" ? "badge-green" : "badge-amber"}`}>{policy.status}</span>
                    {user?.role === "admin" && (
                      <span className="ml-auto flex gap-2">
                        {policy.status !== "active" && <button className="btn-secondary px-2 py-1 text-[11px]" onClick={() => activatePolicy(policy.id)}>Activate</button>}
                        <button className="btn-secondary px-2 py-1 text-[11px] text-red-600" disabled={policy.status === "active"} onClick={() => deletePolicy(policy)}>
                          <Trash2 size={13}/>Xóa
                        </button>
                      </span>
                    )}
                  </div>
                  <p className="muted mt-2 text-[10px]">{policy.parsed_json.faculty || "Chưa nhận diện khoa"} - {policy.parsed_json.specializations.length} nhóm chuyên môn</p>
                </div>
              ))}
            </div>
            {!policyFiles.length && <p className="muted text-xs">Chưa có policy file. Admin hãy upload file policy để sinh Master Folder Tree.</p>}
          </div>
        </Panel>

        <Panel title="Nhóm chuyên môn được phân công" description="Virtual Folder View được sinh từ phân công của Admin/Trưởng bộ môn.">
          <div className="space-y-3 p-4">
            {!profile.policy && <p className="rounded bg-amber-50 p-3 text-xs text-amber-800">Hệ thống chưa có policy active. Vui lòng liên hệ Admin.</p>}
            {assignedSpecializations.map(spec => (
              <div key={spec.id} className="rounded-lg border border-[var(--border)] p-3 text-sm">
                <strong className="block">{spec.name}</strong>
                <span className="muted text-[10px]">Nhóm chuyên môn này được phân công qua Lecturer Assignment Policy.</span>
              </div>
            ))}
            {profile.policy && !assignedSpecializations.length && <p className="rounded bg-slate-50 p-3 text-xs text-slate-700">Bạn chưa được phân công nhóm chuyên môn.</p>}
            <p className="muted text-[11px]">Không thể tự tick chuyên môn trong Settings.</p>
          </div>
        </Panel>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Panel title="Master Tree active">
          <div className="p-4">
            {masterTree.tree ? <TreePreview node={masterTree.tree}/> : <p className="muted text-xs">{masterTree.message || "Chưa có Master Tree active."}</p>}
          </div>
        </Panel>
        <Panel title="Kho lưu trữ ngoài">
          <div className="space-y-3 p-4">
            {storages.map(storage => (
              <div key={storage.id} className="rounded-lg border border-[var(--border)] p-3">
                <div className="flex items-center gap-2">
                  <Cloud size={15} className="text-blue-600"/>
                  <strong className="text-xs">{storage.name}</strong>
                  <span className="badge badge-green ml-auto">{storage.last_status}</span>
                </div>
                <p className="muted mt-2 text-[10px]">{storage.provider} - {storage.location}</p>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {permission && (
        <Panel title="Quyền tài liệu riêng tư" className="mt-5">
          <div className="flex items-center justify-between gap-4 p-5">
            <div>
              <strong className="text-sm">Chủ sở hữu phải phê duyệt</strong>
              <p className="muted text-xs">Mọi người khác phải được chủ sở hữu duyệt trước khi xem hoặc tải tài liệu riêng tư.</p>
            </div>
            <span className="badge badge-green"><ShieldCheck size={14}/>Luôn bật</span>
          </div>
        </Panel>
      )}
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

  function toggle(path: string) {
    setExpanded(current => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }

  function render(item: FolderNode, depth = 0): ReactNode {
    if (!matches(item)) return null;
    const isExpanded = expanded.has(item.path) || !!normalized;
    return (
      <div key={item.id}>
        <button type="button" className="flex w-full items-center gap-1 rounded-md py-1.5 pr-2 text-left text-xs hover:bg-[var(--soft)]" style={{ paddingLeft: `${6 + depth * 16}px` }} onClick={() => toggle(item.path)}>
          {item.children.length ? (isExpanded ? <ChevronDown size={14}/> : <ChevronRight size={14}/>) : <span className="w-[14px]"/>}
          {isExpanded ? <FolderOpen className="text-amber-500" size={15}/> : <Folder className="text-amber-500" size={15}/>}
          <span className="truncate font-semibold">{item.name}</span>
        </button>
        {isExpanded && item.children.map(child => render(child, depth + 1))}
      </div>
    );
  }

  return (
    <div>
      <div className="relative mb-3">
        <Search className="muted absolute left-3 top-2.5" size={14}/>
        <input className="field pl-9" value={query} onChange={event => setQuery(event.target.value)} placeholder="Tìm node trong Master Tree..."/>
      </div>
      <div role="tree" className="max-h-[50vh] overflow-auto">{render(node)}</div>
    </div>
  );
}

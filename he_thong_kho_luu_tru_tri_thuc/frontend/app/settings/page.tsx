"use client";
import { Cloud, Save, Shield, ShieldCheck } from "lucide-react";
import { useBackendData } from "@/lib/hooks";
import { PageHeader, Panel } from "@/components/ui";
type Policy={key:string;value:Record<string,unknown>;updated_at:string};type Storage={id:string;name:string;provider:string;location:string;last_status:string};
export default function Settings() {
  const {data:policies,error}=useBackendData<Policy[]>("/api/admin/policies",[]);const {data:storages}=useBackendData<Storage[]>("/api/admin/storages",[]);
  const permission=policies.find(x=>x.key==="permission_rules");
  return <div><PageHeader eyebrow="Cài đặt hệ thống" title="Cấu hình hệ thống" description="Quản lý chính sách và kho lưu trữ của hệ thống." actions={<button className="btn-primary"><Save size={15}/>Đã kết nối</button>}/>
    {error&&<p className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">Chỉ quản trị viên truy cập được cấu hình: {error}</p>}
    <div className="grid gap-5 xl:grid-cols-2"><Panel title="Chính sách hệ thống"><div className="p-4 space-y-3">{policies.map(x=><div key={x.key} className="rounded-lg border border-[var(--border)] p-3"><div className="flex items-center gap-2"><Shield size={15} className="text-blue-600"/><strong className="text-xs">{x.key}</strong></div><pre className="muted mt-2 whitespace-pre-wrap text-[10px]">{JSON.stringify(x.value,null,2)}</pre></div>)}</div></Panel><Panel title="Kho lưu trữ ngoài"><div className="p-4 space-y-3">{storages.map(x=><div key={x.id} className="rounded-lg border border-[var(--border)] p-3"><div className="flex items-center gap-2"><Cloud size={15} className="text-blue-600"/><strong className="text-xs">{x.name}</strong><span className="badge badge-green ml-auto">{x.last_status}</span></div><p className="muted mt-2 text-[10px]">{x.provider} · {x.location}</p></div>)}</div></Panel></div>
    {permission&&<Panel title="Quyền tài liệu riêng tư" className="mt-5"><div className="p-5 flex items-center justify-between gap-4"><div><strong className="text-sm">Chủ sở hữu phải phê duyệt</strong><p className="muted text-xs">Quy tắc bắt buộc: mọi người khác, kể cả quản trị viên, phải được chủ sở hữu duyệt trước khi xem hoặc tải tài liệu riêng tư.</p></div><span className="badge badge-green"><ShieldCheck size={14}/>Luôn bật</span></div></Panel>}
  </div>
}

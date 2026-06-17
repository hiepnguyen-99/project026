"use client";

import Link from "next/link";
import { Activity, BookOpen, Boxes, Database, FileText, GraduationCap, ServerCog, Upload, Users } from "lucide-react";
import { DashboardData, formatDate, V2Status } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { Bars, Metric, PageHeader, Panel } from "@/components/ui";

const empty: DashboardData = { user: { code:"",name:"",role:"lecturer",department:"",permissions:[] }, stats:{documents:0,private:0,topics:0}, documents:[], requests:[], backups:[], audit:[] };
const emptyV2: V2Status = { architecture:"v2-hybrid",database:"",ready:false,scope:"single-faculty",capacity_target_gb:100,rpo_target_minutes:60,rto_target_hours:4,services:{},objects:[],outbox:[] };

export default function Dashboard() {
  const { data, loading, error } = useBackendData("/api/dashboard", empty);
  const { data:v2 } = useBackendData("/api/v2/status", emptyV2);
  return <div>
    <PageHeader eyebrow="Tổng quan khoa" title={`Chào ${data.user.name || "bạn"}`} description="Tổng hợp dữ liệu mới nhất trong hệ thống EduVault."
      actions={<Link href="/repository" className="btn-primary"><Upload size={15}/>Tải tài liệu</Link>}/>
    {error && <p className="mb-4 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <Metric label="Tài liệu có quyền xem" value={loading?"...":String(data.stats.documents)} detail={`${data.stats.private} tài liệu private`} icon={<FileText size={18}/>}/>
      <Metric label="Chủ đề" value={loading?"...":String(data.stats.topics)} detail="Trong phạm vi truy cập" icon={<BookOpen size={18}/>}/>
      <Metric label="Yêu cầu liên quan" value={loading?"...":String(data.requests.length)} detail={`${data.requests.filter(x=>x.status==="pending").length} đang chờ`} icon={<Users size={18}/>}/>
      <Metric label="Bản backup" value={loading?"...":String(data.backups.length)} detail="Lịch sử gần nhất" icon={<Database size={18}/>}/>
      <Metric label="Audit gần đây" value={loading?"...":String(data.audit.length)} detail={data.user.role==="admin"?"Dành cho quản trị viên":"Theo phân quyền"} icon={<Activity size={18}/>}/>
    </div>
    <div className="mt-5 grid gap-5 xl:grid-cols-[1.55fr_.9fr]">
      <Panel title="Hoạt động kho tri thức" description="Biểu đồ tổng quan từ dữ liệu đang khả dụng"><div className="p-5"><Bars values={[35,52,41,68,58,75,62,84,72,65,91,78,88,96]}/></div></Panel>
      <Panel title="Trạng thái phiên làm việc"><div className="p-5 space-y-3">{[["Người dùng",data.user.name],["Vai trò",data.user.role],["Đơn vị",data.user.department],["Mã tài khoản",data.user.code]].map(x=><div key={x[0]} className="flex justify-between border-b border-[var(--border)] pb-2 text-xs"><span className="muted">{x[0]}</span><strong>{x[1]}</strong></div>)}</div></Panel>
    </div>
    <Panel title="Hạ tầng EduVault V2" description="Hybrid cho một khoa, tự chuyển sang fallback khi dịch vụ tùy chọn chưa bật." className="mt-5">
      <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-5">
        <V2Service label="Database" provider={v2.database||"đang kiểm tra"} available={true}/>
        {Object.entries(v2.services).map(([key,item])=><V2Service key={key} label={key.replaceAll("_"," ")} provider={item.provider} available={item.available}/>)}
        <div className="rounded-xl border border-[var(--border)] p-4"><Boxes size={18} className="text-blue-600"/><strong className="mt-3 block text-xs">Mục tiêu vận hành</strong><span className="muted mt-1 block text-[11px]">100 GB · RPO &lt; 1h · RTO &lt; 4h</span></div>
      </div>
    </Panel>
    <div className="mt-5 grid gap-5 xl:grid-cols-[1.35fr_.9fr]">
      <Panel title="Tài liệu cập nhật gần đây" action={<Link href="/repository" className="btn-secondary">Xem repository</Link>}><div className="table-shell"><table className="data-table"><thead><tr><th>Tài liệu</th><th>Chủ sở hữu</th><th>Phiên bản</th><th>Quyền</th></tr></thead><tbody>{data.documents.slice(0,6).map(d=><tr key={d.id}><td><strong>{d.title}</strong><span className="muted block text-[11px]">{d.topic} · {d.doc_type}</span></td><td>{d.owner_code}</td><td>v{d.current_version}</td><td><span className={`badge ${d.visibility==="public"?"badge-green":"badge-amber"}`}>{d.visibility}</span></td></tr>)}</tbody></table></div></Panel>
      <Panel title="Hoạt động gần đây"><div className="p-2">{data.audit.slice(0,6).map(a=><div className="rounded-lg p-3 hover:bg-[var(--bg)]" key={a.id}><strong className="block text-[12px]">{a.action}</strong><span className="muted text-[11px]">{a.actor_code} · {formatDate(a.created_at)}</span></div>)}{!data.audit.length&&<p className="muted p-4 text-xs">Audit log chỉ hiển thị cho quản trị viên.</p>}</div></Panel>
    </div>
    <div className="mt-5 app-card p-4 flex flex-col gap-3 md:flex-row md:items-center"><div className="h-10 w-10 rounded-lg bg-blue-600 text-white grid place-items-center"><GraduationCap size={20}/></div><div className="flex-1"><strong className="text-sm">Tiếp tục khai thác kho tri thức</strong><p className="muted text-xs">Hỏi AI hoặc mở quy trình chuyển giao học phần.</p></div><Link href="/assistant" className="btn-primary">Mở trợ lý AI</Link></div>
  </div>
}

function V2Service({label,provider,available}:{label:string;provider:string;available:boolean}) {
  return <div className="rounded-xl border border-[var(--border)] p-4"><ServerCog size={18} className={available?"text-emerald-600":"text-amber-600"}/><strong className="mt-3 block text-xs capitalize">{label}</strong><span className="muted mt-1 block text-[11px]">{provider}</span><span className={`badge mt-3 ${available?"badge-green":"badge-amber"}`}>{available?"Sẵn sàng":"Không khả dụng"}</span></div>;
}

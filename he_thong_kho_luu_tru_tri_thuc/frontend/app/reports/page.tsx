"use client";
import { Activity, Database, Download, Search, Users } from "lucide-react";
import { Document } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { Bars, Metric, PageHeader, Panel } from "@/components/ui";
type Usage={actions:{action:string;count:number}[];documents:number;users:number;queries:number;transfers:number};
type Quality={stale:Document[];duplicates:string[][];missing_course_documents:{course:string;missing:string[]}[]};
const eu:Usage={actions:[],documents:0,users:0,queries:0,transfers:0};const eq:Quality={stale:[],duplicates:[],missing_course_documents:[]};
export default function Reports() {
  const {data:u,error}=useBackendData("/api/reports/usage",eu);const {data:q}=useBackendData("/api/quality",eq);
  return <div><PageHeader eyebrow="Báo cáo và phân tích" title="Báo cáo kho tri thức" description="Theo dõi mức độ sử dụng và chất lượng kho tri thức." actions={<button className="btn-primary"><Download size={15}/>Xuất báo cáo</button>}/>
    {error&&<p className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">Vai trò hiện tại không có quyền xem báo cáo: {error}</p>}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Lượt hỏi đáp" value={String(u.queries)} detail="Nhật ký hỏi đáp" icon={<Search size={18}/>}/><Metric label="Tổng tài liệu" value={String(u.documents)} detail="Trong cơ sở dữ liệu" icon={<Database size={18}/>}/><Metric label="Người dùng hoạt động" value={String(u.users)} detail="Tài khoản đang hoạt động" icon={<Users size={18}/>}/><Metric label="Phiên chuyển giao" value={String(u.transfers)} detail="Toàn hệ thống" icon={<Activity size={18}/>}/></div>
    <div className="mt-5 grid gap-5 xl:grid-cols-2"><Panel title="Hoạt động theo loại" description="Từ audit log"><div className="p-5"><Bars values={(u.actions.slice(0,12).map(x=>Math.max(8,Math.min(100,x.count*10))).concat([10,20,30])).slice(0,12)}/></div></Panel><Panel title="Chất lượng kho tri thức"><div className="p-5 space-y-4">{[["Tài liệu lỗi thời",q.stale.length],["Nhóm trùng lặp",q.duplicates.length],["Học phần thiếu tài liệu",q.missing_course_documents.length]].map(x=><div key={x[0]} className="flex justify-between rounded-lg border border-[var(--border)] p-3 text-xs"><strong>{x[0]}</strong><span className="badge badge-amber">{x[1]}</span></div>)}</div></Panel></div>
    <Panel title="Thống kê hành động" className="mt-5"><div className="table-shell"><table className="data-table"><thead><tr><th>Hành động</th><th>Số lượt</th></tr></thead><tbody>{u.actions.map(x=><tr key={x.action}><td><strong>{x.action}</strong></td><td>{x.count}</td></tr>)}</tbody></table></div></Panel>
  </div>
}

"use client";
import { Activity, Database, Download, Search, Users } from "lucide-react";
import { Document, formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { Bars, Metric, PageHeader, Panel } from "@/components/ui";
type Usage={actions:{action:string;count:number}[];action_events:{action:string;actor_code:string;created_at:string}[];documents:number;users:number;queries:number;transfers:number};
type Quality={stale:Document[];duplicates:string[][];missing_course_documents:{course:string;missing:string[]}[]};
const eu:Usage={actions:[],action_events:[],documents:0,users:0,queries:0,transfers:0};const eq:Quality={stale:[],duplicates:[],missing_course_documents:[]};
export default function Reports() {
  const {data:u,error}=useBackendData("/api/reports/usage",eu);const {data:q}=useBackendData("/api/quality",eq);
  function exportReport(){
    const report={generated_at:new Date().toISOString(),usage:u,quality:{stale_count:q.stale.length,duplicate_groups:q.duplicates.length,missing_course_documents:q.missing_course_documents.length,stale_documents:q.stale.map(d=>d.title),duplicates:q.duplicates}};
    const blob=new Blob([JSON.stringify(report,null,2)],{type:"application/json"});
    const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=`eduvault-report-${new Date().toISOString().slice(0,10)}.json`;a.click();URL.revokeObjectURL(url);
  }
  return <div><PageHeader eyebrow="Báo cáo và phân tích" title="Báo cáo kho tri thức" description="Theo dõi mức độ sử dụng và chất lượng kho tri thức." actions={<button className="btn-primary" onClick={exportReport}><Download size={15}/>Xuất báo cáo</button>}/>
    {error&&<p className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">Vai trò hiện tại không có quyền xem báo cáo: {error}</p>}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Lượt hỏi đáp" value={String(u.queries)} detail="Nhật ký hỏi đáp" icon={<Search size={18}/>}/><Metric label="Tổng tài liệu" value={String(u.documents)} detail="Trong cơ sở dữ liệu" icon={<Database size={18}/>}/><Metric label="Người dùng hoạt động" value={String(u.users)} detail="Tài khoản đang hoạt động" icon={<Users size={18}/>}/><Metric label="Phiên chuyển giao" value={String(u.transfers)} detail="Toàn hệ thống" icon={<Activity size={18}/>}/></div>
    <div className="mt-5 grid gap-5 xl:grid-cols-2"><Panel title="Hoạt động theo loại" description="Từ audit log"><div className="p-5"><Bars values={(u.actions.slice(0,12).map(x=>Math.max(8,Math.min(100,x.count*10))).concat([10,20,30])).slice(0,12)}/></div></Panel><Panel title="Chất lượng kho tri thức"><div className="p-5 space-y-4">{[["Tài liệu lỗi thời",q.stale.length],["Nhóm trùng lặp",q.duplicates.length],["Học phần thiếu tài liệu",q.missing_course_documents.length]].map(x=><div key={x[0]} className="flex justify-between rounded-lg border border-[var(--border)] p-3 text-xs"><strong>{x[0]}</strong><span className="badge badge-amber">{x[1]}</span></div>)}</div></Panel></div>
    <Panel title="Thống kê hành động" className="mt-5"><div className="table-shell"><table className="data-table"><thead><tr><th>Hành động</th><th>Mã nhân viên</th><th>Thời gian</th></tr></thead><tbody>{u.action_events.map((x,index)=><tr key={`${x.created_at}-${x.actor_code}-${index}`}><td><strong>{x.action}</strong></td><td>{x.actor_code}</td><td>{formatDate(x.created_at)}</td></tr>)}</tbody></table></div></Panel>
  </div>
}

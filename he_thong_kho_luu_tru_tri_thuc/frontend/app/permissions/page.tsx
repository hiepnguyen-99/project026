"use client";
import { KeyRound, LockKeyhole, ShieldCheck, UserCog, Users } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { DashboardData, Document } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { Metric, PageHeader, Panel } from "@/components/ui";
type PermissionData={readable:Document[];editable:Document[];restricted:Document[]};
const emptyP:PermissionData={readable:[],editable:[],restricted:[]};
const emptyD:DashboardData={user:{code:"",name:"",role:"lecturer",department:""},stats:{documents:0,private:0,topics:0},documents:[],requests:[],backups:[],audit:[]};
export default function Permissions() {
  const {request,user}=useAuth();const {data:p,reload}=useBackendData("/api/permissions",emptyP);const {data:d,reload:reloadD}=useBackendData("/api/dashboard",emptyD);
  async function ask(id:string){await request(`/api/access-requests/${id}`,{method:"POST"});await reload();await reloadD();}
  async function decide(id:string,decision:string){await request(`/api/access-requests/${id}/${decision}`,{method:"POST"});await reloadD();}
  async function revoke(id:string){await request(`/api/access-requests/${id}/revoke`,{method:"POST"});await reload();await reloadD();}
  return <div><PageHeader eyebrow="Phân quyền" title="Quản lý quyền truy cập" description="Theo dõi quyền đọc, chỉnh sửa và các yêu cầu truy cập."/>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Được phép đọc" value={String(p.readable.length)} detail="Tài liệu" icon={<Users size={18}/>}/><Metric label="Được phép sửa" value={String(p.editable.length)} detail="Tài liệu" icon={<UserCog size={18}/>}/><Metric label="Bị hạn chế" value={String(p.restricted.length)} detail="Có thể xin quyền" icon={<LockKeyhole size={18}/>}/><Metric label="Yêu cầu đang chờ" value={String(d.requests.filter(x=>x.status==="pending").length)} detail="Liên quan tài khoản" icon={<KeyRound size={18}/>}/></div>
    <Panel title="Tài liệu bị hạn chế" className="mt-5"><div className="table-shell"><table className="data-table"><thead><tr><th>Tài liệu</th><th>Chủ đề</th><th>Chủ sở hữu</th><th>Hành động</th></tr></thead><tbody>{p.restricted.map(x=><tr key={x.id}><td><strong>{x.title}</strong></td><td>{x.topic}</td><td>{x.owner_code}</td><td><button className="btn-primary" onClick={()=>ask(x.id)}>Xin quyền</button></td></tr>)}</tbody></table></div></Panel>
    <Panel title="Yêu cầu truy cập liên quan" className="mt-5"><div className="table-shell"><table className="data-table"><thead><tr><th>Tài liệu</th><th>Người yêu cầu</th><th>Chủ sở hữu</th><th>Trạng thái</th><th></th></tr></thead><tbody>{d.requests.map(x=><tr key={x.id}><td>{x.document_id}</td><td>{x.requester_code}</td><td>{x.owner_code}</td><td><span className="badge badge-gray">{x.status}</span></td><td>{x.owner_code===user?.code&&x.status==="pending"&&<div className="flex gap-2"><button className="btn-primary" onClick={()=>decide(x.id,"approved")}>Duyệt</button><button className="btn-secondary" onClick={()=>decide(x.id,"denied")}>Từ chối</button></div>}{x.owner_code===user?.code&&x.status==="approved"&&<button className="btn-secondary" onClick={()=>revoke(x.id)}>Thu hồi quyền</button>}</td></tr>)}</tbody></table></div></Panel>
  </div>
}

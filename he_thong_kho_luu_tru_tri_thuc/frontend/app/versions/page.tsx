"use client";

import { Check, Clock3, GitCompareArrows, Plus, RotateCcw, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { DashboardData, Document, formatDate } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { useBackendData } from "@/lib/hooks";
import { PageHeader, Panel } from "@/components/ui";

type Version={id:string;version_no:number;created_by:string;created_at:string};
type Comparison={
  base_version:number;
  target_version:number;
  stats:{added:number;removed:number;unchanged:number};
  changes:{kind:"added"|"removed"|"unchanged";content:string}[];
};

const empty:DashboardData={user:{code:"",name:"",role:"lecturer",department:"",permissions:[]},stats:{documents:0,private:0,topics:0},documents:[],requests:[],backups:[],audit:[]};
const emptyComparison:Comparison={base_version:0,target_version:0,stats:{added:0,removed:0,unchanged:0},changes:[]};

export default function Versions(){
  const {data}=useBackendData("/api/dashboard",empty);
  const [selected,setSelected]=useState<Document|null>(null);
  const document=selected||data.documents[0]||null;

  return <div>
    <PageHeader eyebrow="Quản lý phiên bản" title="Lịch sử và so sánh phiên bản" description="Mỗi lần cập nhật tạo một phiên bản mới; bản cũ vẫn được lưu để so sánh, tải xuống và backup."/>
    <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
      <Panel title="Tài liệu"><div className="max-h-[75vh] overflow-auto p-2">{data.documents.map(item=><button key={item.id} onClick={()=>setSelected(item)} className={`block w-full rounded-lg p-3 text-left text-xs hover:bg-[var(--soft)] ${document?.id===item.id?"bg-blue-50 text-blue-700":""}`}><strong>{item.title}</strong><span className="muted block">v{item.current_version} · {item.owner_code}</span></button>)}</div></Panel>
      {document?<VersionWorkspace key={document.id} document={document}/>:<Panel title="Chưa có tài liệu"><p className="muted p-5 text-xs">Kho tài liệu đang trống.</p></Panel>}
    </div>
  </div>;
}

function VersionWorkspace({document}:{document:Document}){
  const {request}=useAuth();
  const {data:versions,reload}=useBackendData<Version[]>(`/api/documents/${document.id}/versions`,[]);
  const [baseVersion,setBaseVersion]=useState(0);
  const [targetVersion,setTargetVersion]=useState(0);

  useEffect(()=>{
    if(!versions.length)return;
    setTargetVersion(versions[0].version_no);
    setBaseVersion(versions[1]?.version_no||versions[0].version_no);
  },[versions]);

  async function rollback(version:number){
    if(confirm(`Khôi phục ${document.title} về v${version}? Một phiên bản mới sẽ được tạo từ nội dung này.`)){
      await request(`/api/documents/${document.id}/rollback/${version}`,{method:"POST"});
      await reload();
    }
  }

  return <div className="space-y-5">
    <Panel title={document.title} description={`${versions.length} phiên bản được lưu trữ`}>
      <div className="p-5">{versions.map((version,index)=><div className="relative flex gap-4 pb-7 last:pb-0" key={version.id}>{index<versions.length-1&&<i className="absolute left-[15px] top-8 h-[calc(100%-20px)] w-px bg-[var(--border)]"/>}<div className={`relative z-10 h-8 w-8 rounded-full grid place-items-center ${index===0?"bg-blue-600 text-white":"bg-[var(--bg)] border border-[var(--border)]"}`}>{index===0?<Check size={14}/>:<Clock3 size={14}/>}</div><div className="flex-1"><div className="flex justify-between gap-3"><strong className="text-sm">Phiên bản v{version.version_no}</strong><span className="muted text-[10px]">{formatDate(version.created_at)}</span></div><span className="muted text-[10px]">Tạo bởi {version.created_by}</span>{index>0&&<button className="btn-secondary mt-2" onClick={()=>rollback(version.version_no)}><RotateCcw size={13}/>Khôi phục thành phiên bản mới</button>}</div></div>)}</div>
    </Panel>
    {versions.length>1?<VersionComparison documentId={document.id} versions={versions} baseVersion={baseVersion} targetVersion={targetVersion} setBaseVersion={setBaseVersion} setTargetVersion={setTargetVersion}/>:<Panel title="So sánh thay đổi"><p className="muted p-5 text-xs">Cập nhật tài liệu thêm một lần để bắt đầu so sánh phiên bản.</p></Panel>}
  </div>;
}

function VersionComparison({documentId,versions,baseVersion,targetVersion,setBaseVersion,setTargetVersion}:{documentId:string;versions:Version[];baseVersion:number;targetVersion:number;setBaseVersion:(value:number)=>void;setTargetVersion:(value:number)=>void}){
  const effectiveBase=baseVersion||versions[1].version_no;
  const effectiveTarget=targetVersion||versions[0].version_no;
  const path=`/api/documents/${documentId}/versions/compare?base_version=${effectiveBase}&target_version=${effectiveTarget}`;
  const {data,error}=useBackendData<Comparison>(path,emptyComparison);

  return <Panel title="So sánh toàn bộ nội dung" description={`v${effectiveBase} → v${effectiveTarget}`}>
    <div className="border-b border-[var(--border)] p-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
        <select className="field" value={effectiveBase} onChange={event=>setBaseVersion(Number(event.target.value))}>{versions.map(version=><option key={version.id} value={version.version_no}>Bản cũ v{version.version_no}</option>)}</select>
        <GitCompareArrows className="mx-auto text-blue-600" size={18}/>
        <select className="field" value={effectiveTarget} onChange={event=>setTargetVersion(Number(event.target.value))}>{versions.map(version=><option key={version.id} value={version.version_no}>Bản mới v{version.version_no}</option>)}</select>
      </div>
      <div className="mt-3 flex flex-wrap gap-2"><span className="badge badge-green"><Plus size={11}/>{data.stats.added} dòng thêm</span><span className="badge badge-amber"><Undo2 size={11}/>{data.stats.removed} dòng xóa</span><span className="badge badge-gray">{data.stats.unchanged} dòng giữ nguyên</span></div>
    </div>
    {error?<p className="p-5 text-xs text-red-600">{error}</p>:<div className="max-h-[65vh] overflow-auto bg-slate-950 p-3 font-mono text-[11px] leading-5">{data.changes.map((line,index)=><div key={index} className={`grid grid-cols-[30px_1fr] gap-2 rounded px-2 ${line.kind==="added"?"bg-green-950 text-green-200":line.kind==="removed"?"bg-red-950 text-red-200":"text-slate-300"}`}><span className="select-none text-slate-500">{line.kind==="added"?"+":line.kind==="removed"?"-":" "}</span><span className="whitespace-pre-wrap break-words">{line.content||" "}</span></div>)}</div>}
  </Panel>;
}

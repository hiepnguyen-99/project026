"use client";
import { ArrowRight, BookOpen, CheckCircle2, Clock, Lightbulb, MessageCircleQuestion } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { useBackendData } from "@/lib/hooks";
import { PageHeader, Panel } from "@/components/ui";

type Transfer={id:string;course_code:string;course_name:string;from_code:string;to_code:string;deadline:string;progress:number;status:string};
type Course={code:string;name:string;knowledge:{summary:string;documents:{id:string;title:string}[]}};

export default function KnowledgeTransfer() {
  const {user}=useAuth();
  const {data:transfers,reload}=useBackendData<Transfer[]>("/api/transfers",[]);
  const {data:courses}=useBackendData<Course[]>("/api/onboarding/courses",[]);
  const {request}=useAuth();
  async function progress(x:Transfer){await request(`/api/transfers/${x.id}/progress`,{method:"PUT",body:JSON.stringify({progress:Math.min(100,x.progress+25)})});await reload();}
  return <div><PageHeader eyebrow="Chuyển giao tri thức" title="Chuyển giao tri thức" description="Theo dõi các phiên chuyển giao và học phần trong hệ thống."/>
    <div className="grid gap-4 md:grid-cols-3">{transfers.map(t=><div className="app-card p-4" key={t.id}><div className="flex justify-between"><span className="badge badge-blue">{t.course_code}</span><span className="muted text-[11px]">Hạn {t.deadline}</span></div><h2 className="mt-4 text-base font-bold">{t.course_name}</h2><p className="muted mt-1 text-xs">{t.from_code} <ArrowRight className="inline" size={12}/> {t.to_code}</p><div className="mt-5 flex justify-between text-xs"><span>Tiến độ</span><strong>{t.progress}%</strong></div><div className="progress mt-2"><i style={{width:`${t.progress}%`}}/></div><button className="btn-secondary mt-4 w-full" onClick={()=>progress(t)}>Cập nhật +25%</button></div>)}{!transfers.length&&<div className="app-card p-6 muted text-sm">Chưa có phiên chuyển giao phù hợp với tài khoản {user?.code}.</div>}</div>
    <div className="mt-5 grid gap-5 xl:grid-cols-[1.3fr_.8fr]"><Panel title="Kho tri thức học phần" description={`${courses.length} học phần`}><div className="p-4 space-y-2">{courses.map((x,i)=><div key={x.code} className="flex items-center gap-3 rounded-lg border border-[var(--border)] p-3"><div className="h-8 w-8 rounded-lg bg-[var(--soft)] text-blue-600 grid place-items-center">{i%2?<Clock size={16}/>:<BookOpen size={16}/>}</div><div className="flex-1"><strong className="block text-xs">{x.code} · {x.name}</strong><span className="muted text-[10px]">{x.knowledge.documents.length} tài liệu</span></div><span className="badge badge-green">Sẵn sàng</span></div>)}</div></Panel><Panel title="Lộ trình tiếp nhận"><div className="p-4 space-y-2">{[{title:"Tổng quan học phần",icon:<BookOpen size={16}/>},{title:"Kinh nghiệm giảng dạy",icon:<Lightbulb size={16}/>},{title:"Câu hỏi thường gặp",icon:<MessageCircleQuestion size={16}/>},{title:"Xác nhận chuyển giao",icon:<CheckCircle2 size={16}/>}].map(x=><div key={x.title} className="flex items-center gap-3 rounded-lg border border-[var(--border)] p-3"><div className="text-blue-600">{x.icon}</div><strong className="text-xs">{x.title}</strong></div>)}</div></Panel></div>
  </div>
}

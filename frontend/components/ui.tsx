import { ArrowDownRight, ArrowUpRight, MoreHorizontal } from "lucide-react";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: React.ReactNode }) {
  return <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between"><div><p className="eyebrow mb-1">{eyebrow}</p><h1 className="page-title">{title}</h1><p className="muted mt-1 max-w-2xl text-[13px]">{description}</p></div>{actions&&<div className="flex flex-wrap gap-2">{actions}</div>}</div>
}

export function Metric({ label, value, detail, trend = "up", icon }: { label:string; value:string; detail:string; trend?: "up"|"down"; icon:React.ReactNode }) {
  return <div className="app-card p-4"><div className="flex items-start justify-between"><div className="h-9 w-9 rounded-lg bg-[var(--soft)] text-blue-600 grid place-items-center">{icon}</div><button className="muted"><MoreHorizontal size={17}/></button></div><p className="muted mt-4 text-[11px] font-bold uppercase tracking-wider">{label}</p><strong className="mt-1 block text-2xl tracking-tight">{value}</strong><p className={`mt-2 flex items-center gap-1 text-[11px] font-semibold ${trend==="up"?"text-green-600":"text-red-600"}`}>{trend==="up"?<ArrowUpRight size={13}/>:<ArrowDownRight size={13}/>} {detail}</p></div>
}

export function Panel({ title, description, action, children, className="" }: { title:string; description?:string; action?:React.ReactNode; children:React.ReactNode; className?:string }) {
  return <section className={`app-card ${className}`}><div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3"><div><h2 className="section-title">{title}</h2>{description&&<p className="muted mt-0.5 text-[11px]">{description}</p>}</div>{action}</div>{children}</section>
}

export function EmptyState({ title, description }: { title:string; description:string }) {
  return <div className="py-10 text-center"><div className="mx-auto mb-3 h-10 w-10 rounded-full bg-[var(--soft)]"/><strong className="block text-sm">{title}</strong><p className="muted mt-1 text-xs">{description}</p></div>
}

export function Bars({ values, color="bg-blue-500" }: { values:number[]; color?:string }) {
  return <div className="h-44 flex items-end gap-2">{values.map((v,i)=><div key={i} className="flex-1 h-full flex items-end"><i className={`${color} block w-full rounded-t-sm opacity-80`} style={{height:`${v}%`}}/></div>)}</div>
}

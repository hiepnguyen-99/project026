"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Bell, BookOpenCheck, Bot, ChartNoAxesCombined, ClipboardCheck, DatabaseBackup, FileClock, FilePlus2, FolderKanban, GraduationCap, KeyRound, LogOut, Menu, Moon, ScrollText, Search, Settings, Sun, UserCog, Users, X } from "lucide-react";
import { AuthProvider, useAuth } from "@/components/auth-provider";
import { LoginScreen } from "@/components/login-screen";
import { UploadTaskProvider } from "@/components/upload-task-provider";
import { canAccessPath, ROLE_LABELS, ROLE_MENUS, toAppRole } from "@/src/config/role-menu";

const icons = {
  dashboard: ChartNoAxesCombined,
  repository: FolderKanban,
  upload: FilePlus2,
  policy: Settings,
  users: Users,
  permissions: KeyRound,
  backup: DatabaseBackup,
  reports: ChartNoAxesCombined,
  audit: ScrollText,
  transfer: GraduationCap,
  quality: ClipboardCheck,
  versions: FileClock,
  chatbot: Bot,
  profile: UserCog,
  handover: GraduationCap,
  summary: BookOpenCheck,
};

export function AppShell({ children }: { children: React.ReactNode }) {
  return <AuthProvider><UploadTaskProvider><AuthenticatedShell>{children}</AuthenticatedShell></UploadTaskProvider></AuthProvider>;
}

function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { user, ready, logout } = useAuth();
  const [dark, setDark] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  useEffect(() => {
    if (!ready || !user) return;
    if (!canAccessPath(path, user.permissions || [])) router.replace("/");
  }, [path, ready, router, user]);

  if (!ready) return <div className="min-h-screen grid place-items-center text-sm muted">Đang kết nối tới máy chủ...</div>;
  if (!user) return <LoginScreen />;
  if (!canAccessPath(path, user.permissions || [])) return null;

  const appRole = toAppRole(user.role);
  const menuItems = ROLE_MENUS[appRole].filter(item => user.permissions.includes(item.permission));

  const sidebar = (
    <aside className="h-full w-[304px] max-w-[calc(100vw-32px)] bg-[var(--sidebar)] text-white flex flex-col">
      <div className="h-[84px] px-6 flex items-center gap-3 border-b border-white/10">
        <div className="h-11 w-11 shrink-0 rounded-xl bg-blue-500 grid place-items-center"><BookOpenCheck size={22}/></div>
        <div className="min-w-0 whitespace-nowrap"><strong className="block text-[17px] font-extrabold leading-5 tracking-normal">EduVault</strong><span className="mt-1 block text-[12px] font-semibold leading-4 text-blue-100/75">Kho tri thức khoa CNTT</span></div>
      </div>
      <nav className="flex flex-1 flex-col gap-1 px-4 py-5" aria-label="Điều hướng chính">
        <p className="px-3 pb-2 text-[10px] font-bold uppercase tracking-[.16em] text-blue-200/60">Không gian làm việc</p>
        {menuItems.map((item) => {
          const Icon = icons[item.icon];
          const active = path === item.href.split("?")[0];
          return <Link key={`${item.permission}:${item.href}`} href={item.href} onClick={()=>setMobile(false)} className={`flex h-12 w-full items-center gap-3 rounded-xl px-3 text-[13px] font-semibold transition-colors duration-150 ${active ? "bg-blue-500 text-white shadow-lg shadow-blue-950/20" : "bg-transparent text-blue-100/75 hover:bg-white/10 hover:text-white"}`}><Icon className="shrink-0" size={18}/><span className="truncate whitespace-nowrap">{item.label}</span></Link>
        })}
      </nav>
      <div className="m-3 rounded-xl border border-white/10 bg-white/5 p-3">
        <div className="flex justify-between text-xs font-bold"><span>Dung lượng demo V2</span><span>100 GB</span></div>
        <div className="mt-2 h-1.5 rounded-full bg-white/10"><div className="h-full w-[12%] rounded-full bg-blue-400"/></div>
        <p className="mt-2 text-[10px] text-blue-100/60">MySQL metadata · MinIO file gốc</p>
      </div>
    </aside>
  );

  return (
    <div className="min-h-screen">
      <div className="desktop-sidebar fixed inset-y-0 left-0 z-30">{sidebar}</div>
      {mobile && <div className="fixed inset-0 z-50 flex lg:hidden"><div className="absolute inset-0 bg-slate-950/60" onClick={()=>setMobile(false)}/><div className="relative">{sidebar}<button aria-label="Đóng menu" className="absolute right-3 top-4 text-white" onClick={()=>setMobile(false)}><X/></button></div></div>}
      <div className="main-offset ml-[304px]">
        <header className="sticky top-0 z-20 h-[72px] bg-[color:var(--card)]/92 backdrop-blur border-b border-[var(--border)] px-4 md:px-7 flex items-center gap-3">
          <button className="icon-btn sidebar-toggle" aria-label="Mở menu" onClick={()=>setMobile(true)}><Menu size={18}/></button>
          <button onClick={()=>setSearchOpen(true)} className="h-10 max-w-xl flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 flex items-center gap-2 text-left text-sm text-[var(--muted)]"><Search size={17}/><span className="truncate">Tìm tài liệu, học phần, giảng viên...</span><kbd className="ml-auto hidden sm:block rounded border border-[var(--border)] bg-[var(--card)] px-1.5 py-0.5 text-[10px]">⌘ K</kbd></button>
          <button className="icon-btn" aria-label="Đổi giao diện" onClick={()=>setDark(!dark)}>{dark?<Sun size={17}/>:<Moon size={17}/>}</button>
          <button className="icon-btn relative" aria-label="Thông báo"><Bell size={17}/><i className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-red-500"/></button>
          <div className="hidden sm:flex items-center gap-2 border-l border-[var(--border)] pl-3"><div className="h-9 w-9 rounded-full bg-gradient-to-br from-blue-600 to-indigo-800 text-white grid place-items-center text-xs font-bold">{user.code.slice(0,2)}</div><div><strong className="block text-xs">{user.name}</strong><span className="muted text-[10px]">{ROLE_LABELS[appRole]} · {user.code}</span></div><button className="icon-btn ml-1" aria-label="Đăng xuất" onClick={logout}><LogOut size={15}/></button></div>
        </header>
        <main className="p-4 md:p-7 max-w-[1680px] mx-auto">{children}</main>
      </div>
      {searchOpen && <div className="fixed inset-0 z-[70] bg-slate-950/55 p-4 flex items-start justify-center pt-[12vh]" onClick={()=>setSearchOpen(false)}><div className="app-card w-full max-w-2xl overflow-hidden" onClick={e=>e.stopPropagation()}><div className="p-4 flex gap-3 border-b border-[var(--border)]"><Search className="muted"/><input autoFocus className="w-full bg-transparent outline-none text-sm" placeholder="Tìm kiếm trong toàn bộ kho tri thức..."/><button onClick={()=>setSearchOpen(false)}><X size={18}/></button></div><div className="p-4"><p className="eyebrow mb-3">Gợi ý nhanh</p>{["Đề cương Trí tuệ nhân tạo","Quy trình xây dựng đề thi","Giảng viên Nguyễn Minh Anh"].map(x=><div key={x} className="rounded-lg px-3 py-2.5 hover:bg-[var(--soft)] text-sm flex gap-3"><Search size={15} className="muted"/>{x}</div>)}</div></div></div>}
    </div>
  );
}

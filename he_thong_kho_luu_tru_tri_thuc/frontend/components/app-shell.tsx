"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  Bell,
  BookOpenCheck,
  Bot,
  ChartNoAxesCombined,
  CheckCircle2,
  ChevronsLeft,
  ChevronsRight,
  ClipboardCheck,
  DatabaseBackup,
  FileClock,
  FilePlus2,
  FolderKanban,
  GraduationCap,
  KeyRound,
  LoaderCircle,
  LogOut,
  Menu,
  Moon,
  RefreshCw,
  ScrollText,
  Search,
  Settings,
  Sun,
  Trash2,
  UploadCloud,
  UserCog,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { AuthProvider, useAuth } from "@/components/auth-provider";
import { LoginScreen } from "@/components/login-screen";
import { UploadTask, UploadTaskProvider, useUploadTasks } from "@/components/upload-task-provider";
import { canAccessPath, permissionsForRole, ROLE_LABELS, ROLE_MENUS, toAppRole } from "@/src/config/role-menu";

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
  search: Search,
  trash: Trash2,
};

const SIDEBAR_COLLAPSED_KEY = "eduvault.sidebar.collapsed";
const SIDEBAR_EXPANDED_WIDTH = 304;
const SIDEBAR_COLLAPSED_WIDTH = 72;

export function AppShell({ children }: { children: React.ReactNode }) {
  return <AuthProvider><UploadTaskProvider><AuthenticatedShell>{children}</AuthenticatedShell></UploadTaskProvider></AuthProvider>;
}

const uploadStatusLabels: Record<UploadTask["status"], string> = {
  uploading: "Đang tải lên",
  uploaded: "Đã tải file gốc",
  analyzing: "Đang AI phân tích",
  saving_metadata: "Đang lưu metadata",
  pending_confirmation: "Chờ xác nhận phân loại",
  processing: "Đã lưu, AI đang xử lý",
  completed: "Đã lưu, AI xử lý nền",
  failed: "Thất bại",
};

function formatUploadBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function UploadNotificationMenu() {
  const { tasks, retryUpload, removeTask } = useUploadTasks();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const activeCount = tasks.filter(task => !["completed", "failed"].includes(task.status)).length;
  const failedCount = tasks.filter(task => task.status === "failed").length;
  const badgeCount = activeCount || failedCount;

  useEffect(() => {
    if (!open) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  return (
    <div className="relative" ref={menuRef}>
      <button className="icon-btn relative" aria-label="Thông báo" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <Bell size={17}/>
        {badgeCount > 0 && <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-red-500 px-1 text-[10px] font-bold leading-none text-white">{badgeCount}</span>}
      </button>
      {open && <div className="app-card absolute right-0 top-12 z-[80] w-[min(420px,calc(100vw-1.5rem))] overflow-hidden shadow-xl">
        <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
          <UploadCloud className="text-blue-600" size={17}/>
          <div>
            <strong className="block text-sm">Thông báo tải lên</strong>
            <span className="muted text-[11px]">Theo dõi upload và xử lý tài liệu</span>
          </div>
          {activeCount > 0 && <span className="badge badge-blue ml-auto">{activeCount} đang chạy</span>}
        </div>
        <div className="max-h-[min(68vh,520px)] space-y-2 overflow-y-auto p-3">
          {!tasks.length && <p className="muted p-3 text-center text-xs">Chưa có thông báo upload. Bạn có thể tiếp tục làm việc khi file đang được xử lý.</p>}
          {tasks.slice(0, 8).map(task => {
            const progress = task.total_bytes > 0 ? Math.round(task.uploaded_bytes / task.total_bytes * 100) : 0;
            const active = !["completed", "failed"].includes(task.status);
            const canCancel = ["pending_confirmation", "failed"].includes(task.status);
            return <div key={task.id} className="rounded-lg border border-[var(--border)] p-3">
              <div className="flex items-start gap-2">
                {task.status === "completed" ? <CheckCircle2 className="mt-0.5 text-green-600" size={16}/> : task.status === "failed" ? <XCircle className="mt-0.5 text-red-600" size={16}/> : <LoaderCircle className="mt-0.5 animate-spin text-blue-600" size={16}/>}
                <div className="min-w-0 flex-1">
                  <strong className="block truncate text-xs">{task.filename}</strong>
                  <span className="muted text-[11px]">{uploadStatusLabels[task.status]}</span>
                </div>
                {task.status === "failed" && <button className="btn-secondary px-2 py-1 text-[10px]" onClick={() => retryUpload(task.id)}><RefreshCw size={11}/>Thử lại</button>}
                {canCancel && <button className="btn-secondary px-2 py-1 text-[10px] text-red-600" onClick={() => removeTask(task.id)}><Trash2 size={11}/>Hủy</button>}
                {!active && !canCancel && <button className="icon-btn h-7 w-7" aria-label="Xóa tác vụ" onClick={() => removeTask(task.id)}><Trash2 size={12}/></button>}
              </div>
              <div className="progress mt-3"><i style={{ width: `${active ? progress : 100}%` }} className={task.status === "failed" ? "!bg-red-500" : task.status === "completed" ? "!bg-green-500" : ""}/></div>
              <div className="muted mt-1 flex justify-between text-[10px]"><span>{formatUploadBytes(task.uploaded_bytes)} / {formatUploadBytes(task.total_bytes)}</span><span>{progress}%</span></div>
              {task.metadata.ai_metadata && <div className="mt-2 rounded-lg bg-[var(--soft)] p-2 text-[10px]">
                <strong className="block text-blue-700">Nhãn AI đã gán</strong>
                <span className="muted">{task.metadata.ai_metadata.topic} · {task.metadata.ai_metadata.doc_type}</span>
              </div>}
              {task.error && <p className="mt-2 text-[10px] text-red-600">{task.error}</p>}
            </div>;
          })}
        </div>
      </div>}
    </div>
  );
}

function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { user, ready, logout } = useAuth();
  const [dark, setDark] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [headerQuery, setHeaderQuery] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarReady, setSidebarReady] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  useEffect(() => {
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (stored === "true" || stored === "false") {
      setSidebarCollapsed(stored === "true");
    } else {
      setSidebarCollapsed(window.matchMedia("(max-width: 1279px)").matches);
    }
    setSidebarReady(true);
  }, []);

  useEffect(() => {
    if (!sidebarReady) return;
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(sidebarCollapsed));
  }, [sidebarCollapsed, sidebarReady]);

  useEffect(() => {
    if (!ready || !user) return;
    const permissions = Array.from(new Set([...(user.permissions || []), ...permissionsForRole(user.role)]));
    if (!canAccessPath(path, permissions)) router.replace("/");
  }, [path, ready, router, user]);

  if (!ready) return <div className="grid min-h-screen place-items-center text-sm muted">Đang kết nối tới máy chủ...</div>;
  if (!user) return <LoginScreen />;
  const effectivePermissions = Array.from(new Set([...(user.permissions || []), ...permissionsForRole(user.role)]));
  if (!canAccessPath(path, effectivePermissions)) return null;

  const appRole = toAppRole(user.role);
  const menuItems = ROLE_MENUS[appRole].filter(item => effectivePermissions.includes(item.permission));
  const sidebarWidth = sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH;

  function submitHeaderSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = headerQuery.trim();
    router.push(q ? `/search?q=${encodeURIComponent(q)}` : "/search");
  }

  function renderSidebar(collapsed: boolean) {
    return (
      <aside
        className={`flex h-full max-w-[calc(100vw-32px)] flex-col bg-[var(--sidebar)] text-white transition-[width] duration-200 ease-out ${collapsed ? "w-[72px]" : "w-[304px]"}`}
        aria-label="Điều hướng EduVault"
      >
        <div className={`flex h-[84px] items-center border-b border-white/10 transition-all duration-200 ${collapsed ? "justify-center px-2" : "gap-3 px-6"}`}>
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-blue-500"><BookOpenCheck size={22}/></div>
          {!collapsed && <div className="min-w-0 whitespace-nowrap"><strong className="block text-[17px] font-extrabold leading-5 tracking-normal">EduVault</strong><span className="mt-1 block text-[12px] font-semibold leading-4 text-blue-100/75">Kho tri thức khoa CNTT</span></div>}
        </div>
        <nav className={`flex flex-1 flex-col gap-1 py-5 transition-all duration-200 ${collapsed ? "px-2" : "px-4"}`} aria-label="Điều hướng chính">
          {!collapsed && <p className="px-3 pb-2 text-[10px] font-bold uppercase tracking-[.14em] text-blue-200/60">Không gian làm việc</p>}
          {menuItems.map((item) => {
            const Icon = icons[item.icon];
            const active = path === item.href.split("?")[0];
            return (
              <Link
                key={`${item.permission}:${item.href}`}
                href={item.href}
                title={collapsed ? item.label : undefined}
                aria-label={item.label}
                onClick={() => setMobile(false)}
                className={`flex h-12 w-full items-center rounded-xl text-[13px] font-semibold transition-colors duration-150 ${collapsed ? "justify-center px-0" : "gap-3 px-3"} ${active ? "bg-blue-500 text-white shadow-lg shadow-blue-950/20" : "bg-transparent text-blue-100/75 hover:bg-white/10 hover:text-white"}`}
              >
                <Icon className="shrink-0" size={18}/>
                {!collapsed && <span className="truncate whitespace-nowrap">{item.label}</span>}
              </Link>
            );
          })}
        </nav>
      </aside>
    );
  }

  return (
    <div className="min-h-screen">
      <div className="desktop-sidebar fixed inset-y-0 left-0 z-30 transition-[width] duration-200 ease-out" style={{ width: sidebarWidth }}>{renderSidebar(sidebarCollapsed)}</div>
      {mobile && <div className="fixed inset-0 z-50 flex lg:hidden"><div className="absolute inset-0 bg-slate-950/60" onClick={() => setMobile(false)}/><div className="relative">{renderSidebar(false)}<button aria-label="Đóng menu" className="absolute right-3 top-4 text-white" onClick={() => setMobile(false)}><X/></button></div></div>}
      <div className="main-offset transition-[margin] duration-200 ease-out" style={{ marginLeft: sidebarWidth }}>
        <header className="sticky top-0 z-20 flex h-[72px] items-center gap-3 border-b border-[var(--border)] bg-[color:var(--card)]/92 px-4 backdrop-blur md:px-7">
          <button className="icon-btn sidebar-toggle" aria-label="Mở menu" onClick={() => setMobile(true)}><Menu size={18}/></button>
          <button className="icon-btn hidden xl:inline-flex" aria-label={sidebarCollapsed ? "Mở rộng thanh điều hướng" : "Thu gọn thanh điều hướng"} title={sidebarCollapsed ? "Mở rộng thanh điều hướng" : "Thu gọn thanh điều hướng"} onClick={() => setSidebarCollapsed(value => !value)}>
            {sidebarCollapsed ? <ChevronsRight size={17}/> : <ChevronsLeft size={17}/>}
          </button>
          <form onSubmit={submitHeaderSearch} className="flex h-10 max-w-xl flex-1 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-left text-sm text-[var(--muted)] focus-within:border-blue-300 focus-within:text-blue-700"><Search size={17}/><input className="min-w-0 flex-1 bg-transparent text-sm outline-none" value={headerQuery} onChange={event => setHeaderQuery(event.target.value)} placeholder="Tìm tài liệu, học phần, giảng viên..." /></form>
          <button className="icon-btn" aria-label="Đổi giao diện" onClick={() => setDark(!dark)}>{dark ? <Sun size={17}/> : <Moon size={17}/>}</button>
          <UploadNotificationMenu />
          <div className="hidden items-center gap-2 border-l border-[var(--border)] pl-3 sm:flex"><div className="grid h-9 w-9 place-items-center rounded-full bg-blue-600 text-xs font-bold text-white">{user.code.slice(0, 2)}</div><div><strong className="block text-xs">{user.name}</strong><span className="muted text-[10px]">{ROLE_LABELS[appRole]} · {user.code}</span></div><button className="icon-btn ml-1" aria-label="Đăng xuất" onClick={logout}><LogOut size={15}/></button></div>
        </header>
        <main className="mx-auto max-w-[1680px] p-4 md:p-7">{children}</main>
      </div>
    </div>
  );
}

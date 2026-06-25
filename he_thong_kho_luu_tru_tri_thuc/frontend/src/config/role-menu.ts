export type AppRole = "ADMIN" | "HEAD_OF_DEPARTMENT" | "LECTURER" | "NEW_LECTURER";

export type BackendRole = "admin" | "head" | "lecturer" | "new_lecturer";

export type Permission =
  | "dashboard.view"
  | "repository.view"
  | "repository.own"
  | "repository.upload"
  | "policy.manage"
  | "users.manage"
  | "permissions.manage"
  | "backup.manage"
  | "cloud.sync"
  | "reports.view"
  | "audit.view"
  | "transfer.manage"
  | "quality.view"
  | "versions.view"
  | "chatbot.use"
  | "profile.manage"
  | "handover.view"
  | "knowledge.summary";

export type MenuItem = {
  label: string;
  href: string;
  permission: Permission;
  icon:
    | "dashboard"
    | "repository"
    | "upload"
    | "policy"
    | "users"
    | "permissions"
    | "backup"
    | "reports"
    | "audit"
    | "transfer"
    | "quality"
    | "versions"
    | "chatbot"
    | "profile"
    | "handover"
    | "summary"
    | "search"
    | "trash";
};

export const ROLE_LABELS: Record<AppRole, string> = {
  ADMIN: "Quản trị viên",
  HEAD_OF_DEPARTMENT: "Trưởng bộ môn",
  LECTURER: "Giảng viên",
  NEW_LECTURER: "Giảng viên mới",
};

export const ROLE_ALIASES: Record<BackendRole, AppRole> = {
  admin: "ADMIN",
  head: "HEAD_OF_DEPARTMENT",
  lecturer: "LECTURER",
  new_lecturer: "NEW_LECTURER",
};

export const ROLE_PERMISSIONS: Record<AppRole, Permission[]> = {
  ADMIN: [
    "dashboard.view",
    "repository.view",
    "policy.manage",
    "users.manage",
    "permissions.manage",
    "backup.manage",
    "cloud.sync",
    "reports.view",
    "audit.view",
    "transfer.manage",
  ],
  HEAD_OF_DEPARTMENT: [
    "dashboard.view",
    "repository.view",
    "policy.manage",
    "cloud.sync",
    "transfer.manage",
    "quality.view",
    "reports.view",
  ],
  LECTURER: [
    "dashboard.view",
    "repository.own",
    "repository.upload",
    "cloud.sync",
    "versions.view",
    "chatbot.use",
    "profile.manage",
  ],
  NEW_LECTURER: [
    "dashboard.view",
    "cloud.sync",
    "handover.view",
    "knowledge.summary",
    "chatbot.use",
    "profile.manage",
  ],
};

export const ROLE_MENUS: Record<AppRole, MenuItem[]> = {
  ADMIN: [
    { label: "Vận hành", href: "/operations", permission: "audit.view", icon: "audit" },
    { label: "Tổng quan", href: "/", permission: "dashboard.view", icon: "dashboard" },
    { label: "Tìm kiếm", href: "/search", permission: "dashboard.view", icon: "search" },
    { label: "Kho tri thức", href: "/repository", permission: "repository.view", icon: "repository" },
    { label: "Quản trị tri thức", href: "/policy", permission: "policy.manage", icon: "policy" },
    { label: "Quy tắc quản trị", href: "/governance-rules", permission: "policy.manage", icon: "policy" },
    { label: "Người dùng", href: "/users", permission: "users.manage", icon: "users" },
    { label: "Phân quyền", href: "/permissions", permission: "permissions.manage", icon: "permissions" },
    { label: "Sao lưu", href: "/backup", permission: "backup.manage", icon: "backup" },
    { label: "Báo cáo", href: "/reports", permission: "reports.view", icon: "reports" },
    { label: "Nhật ký hệ thống", href: "/audit-logs", permission: "audit.view", icon: "audit" },
  ],
  HEAD_OF_DEPARTMENT: [
    { label: "Tổng quan", href: "/", permission: "dashboard.view", icon: "dashboard" },
    { label: "Tìm kiếm", href: "/search", permission: "dashboard.view", icon: "search" },
    { label: "Kho tri thức", href: "/repository", permission: "repository.view", icon: "repository" },
    { label: "Quản trị tri thức", href: "/policy", permission: "policy.manage", icon: "policy" },
    { label: "Quy tắc quản trị", href: "/governance-rules", permission: "policy.manage", icon: "policy" },
    { label: "Đồng bộ", href: "/backup", permission: "cloud.sync", icon: "backup" },
    { label: "Chuyển giao tri thức", href: "/knowledge-transfer", permission: "transfer.manage", icon: "transfer" },
    { label: "Báo cáo", href: "/reports", permission: "reports.view", icon: "reports" },
  ],
  LECTURER: [
    { label: "Tổng quan", href: "/", permission: "dashboard.view", icon: "dashboard" },
    { label: "Tìm kiếm", href: "/search", permission: "dashboard.view", icon: "search" },
    { label: "Kho tri thức", href: "/repository", permission: "repository.own", icon: "repository" },
    { label: "Đồng bộ", href: "/backup", permission: "cloud.sync", icon: "backup" },
    { label: "Phiên bản", href: "/versions", permission: "versions.view", icon: "versions" },
    { label: "Trợ lý AI", href: "/assistant", permission: "chatbot.use", icon: "chatbot" },
    { label: "Hồ sơ", href: "/profile", permission: "profile.manage", icon: "profile" },
  ],
  NEW_LECTURER: [
    { label: "Tổng quan", href: "/", permission: "dashboard.view", icon: "dashboard" },
    { label: "Tìm kiếm", href: "/search", permission: "dashboard.view", icon: "search" },
    { label: "Chuyển giao tri thức", href: "/knowledge-transfer", permission: "handover.view", icon: "handover" },
    { label: "Đồng bộ", href: "/backup", permission: "cloud.sync", icon: "backup" },
    { label: "Trợ lý AI", href: "/assistant", permission: "chatbot.use", icon: "chatbot" },
    { label: "Hồ sơ", href: "/profile", permission: "profile.manage", icon: "profile" },
  ],
};

export const ROUTE_PERMISSIONS: Array<{ pattern: RegExp; permission: Permission }> = [
  { pattern: /^\/$/, permission: "dashboard.view" },
  { pattern: /^\/search(?:\/.*)?$/, permission: "dashboard.view" },
  { pattern: /^\/repository(?:\/.*)?$/, permission: "repository.view" },
  { pattern: /^\/repository(?:\/.*)?$/, permission: "repository.own" },
  { pattern: /^\/trash(?:\/.*)?$/, permission: "repository.view" },
  { pattern: /^\/trash(?:\/.*)?$/, permission: "repository.own" },
  { pattern: /^\/documents(?:\/.*)?$/, permission: "repository.view" },
  { pattern: /^\/documents(?:\/.*)?$/, permission: "repository.own" },
  { pattern: /^\/assistant(?:\/.*)?$/, permission: "chatbot.use" },
  { pattern: /^\/knowledge-transfer(?:\/.*)?$/, permission: "transfer.manage" },
  { pattern: /^\/knowledge-transfer(?:\/.*)?$/, permission: "handover.view" },
  { pattern: /^\/knowledge-transfer(?:\/.*)?$/, permission: "knowledge.summary" },
  { pattern: /^\/versions(?:\/.*)?$/, permission: "versions.view" },
  { pattern: /^\/backup(?:\/.*)?$/, permission: "backup.manage" },
  { pattern: /^\/backup(?:\/.*)?$/, permission: "cloud.sync" },
  { pattern: /^\/permissions(?:\/.*)?$/, permission: "permissions.manage" },
  { pattern: /^\/reports(?:\/.*)?$/, permission: "reports.view" },
  { pattern: /^\/reports(?:\/.*)?$/, permission: "quality.view" },
  { pattern: /^\/settings(?:\/.*)?$/, permission: "policy.manage" },
  { pattern: /^\/settings(?:\/.*)?$/, permission: "profile.manage" },
  { pattern: /^\/policy(?:\/.*)?$/, permission: "policy.manage" },
  { pattern: /^\/governance-rules(?:\/.*)?$/, permission: "policy.manage" },
  { pattern: /^\/profile(?:\/.*)?$/, permission: "profile.manage" },
  { pattern: /^\/users(?:\/.*)?$/, permission: "users.manage" },
  { pattern: /^\/audit-logs(?:\/.*)?$/, permission: "audit.view" },
  { pattern: /^\/operations(?:\/.*)?$/, permission: "audit.view" },
];

export function toAppRole(role: BackendRole): AppRole {
  return ROLE_ALIASES[role];
}

export function permissionsForRole(role: BackendRole): Permission[] {
  return ROLE_PERMISSIONS[toAppRole(role)];
}

export function canAccessPath(pathname: string, permissions: string[]): boolean {
  const required = ROUTE_PERMISSIONS.filter(route => route.pattern.test(pathname));
  if (!required.length) return true;
  return required.some(route => permissions.includes(route.permission));
}

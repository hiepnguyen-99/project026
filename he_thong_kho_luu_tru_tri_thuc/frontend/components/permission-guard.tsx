"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Permission } from "@/src/config/role-menu";
import { useAuth } from "@/components/auth-provider";

type PermissionGuardProps = {
  permission: Permission;
  children: React.ReactNode;
  fallback?: React.ReactNode;
  redirectTo?: string;
};

export function PermissionGuard({ permission, children, fallback = null, redirectTo = "/" }: PermissionGuardProps) {
  const router = useRouter();
  const { user, ready } = useAuth();
  const allowed = !!user?.permissions?.includes(permission);

  useEffect(() => {
    if (ready && user && !allowed) router.replace(redirectTo);
  }, [allowed, ready, redirectTo, router, user]);

  if (!ready || !user) return null;
  if (!allowed) return <>{fallback}</>;
  return <>{children}</>;
}

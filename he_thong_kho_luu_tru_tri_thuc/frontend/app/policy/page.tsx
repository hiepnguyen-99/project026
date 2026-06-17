"use client";

import Settings from "@/app/settings/page";
import { PermissionGuard } from "@/components/permission-guard";

export default function PolicyPage() {
  return <PermissionGuard permission="policy.manage"><Settings /></PermissionGuard>;
}

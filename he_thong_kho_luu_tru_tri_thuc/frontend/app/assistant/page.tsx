"use client";

import { AssistantChat } from "@/components/assistant-chat";
import { PageHeader } from "@/components/ui";

export default function Assistant() {
  return <div>
    <PageHeader
      eyebrow="Trợ lý tri thức AI"
      title="Hỏi đáp trên kho tri thức"
      description="Hỏi tự nhiên trên các tài liệu bạn được phép xem trong EduVault."
    />
    <AssistantChat variant="page"/>
  </div>;
}

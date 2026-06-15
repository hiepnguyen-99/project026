"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <div className="app-card mx-auto mt-16 max-w-lg p-10 text-center">
      <AlertTriangle className="mx-auto text-amber-500" size={36} />
      <h1 className="page-title mt-4">Không thể tải dữ liệu</h1>
      <p className="muted mt-2 text-sm">Đã có lỗi xảy ra khi kết nối với kho tri thức. Vui lòng thử lại.</p>
      <button className="btn-primary mt-5" onClick={reset}><RotateCcw size={15}/>Thử lại</button>
    </div>
  );
}

import Link from "next/link";
import { SearchX } from "lucide-react";

export default function NotFound() {
  return (
    <div className="app-card mx-auto mt-16 max-w-lg p-10 text-center">
      <SearchX className="mx-auto text-blue-600" size={36} />
      <h1 className="page-title mt-4">Không tìm thấy nội dung</h1>
      <p className="muted mt-2 text-sm">Tài liệu hoặc trang bạn yêu cầu không tồn tại hoặc đã được di chuyển.</p>
      <Link className="btn-primary mt-5" href="/">Về trang tổng quan</Link>
    </div>
  );
}

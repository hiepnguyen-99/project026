export const documents = [
  { name: "Đề cương Trí tuệ nhân tạo 2026", type: "PDF", category: "Đề cương", owner: "Nguyễn Minh Anh", updated: "10 phút trước", size: "2.4 MB", status: "Đã duyệt", views: 1842 },
  { name: "Hướng dẫn xây dựng hệ thống RAG", type: "DOCX", category: "Học liệu", owner: "Trần Hoàng Nam", updated: "2 giờ trước", size: "8.1 MB", status: "Đã lập chỉ mục", views: 1260 },
  { name: "Quy trình xây dựng đề thi cuối kỳ", type: "PDF", category: "Quy trình", owner: "Phòng Khảo thí", updated: "Hôm qua", size: "1.7 MB", status: "Riêng tư", views: 967 },
  { name: "Rubric đồ án Lập trình Python", type: "XLSX", category: "Đánh giá", owner: "Lê Thu Hà", updated: "08/06/2026", size: "840 KB", status: "Đã duyệt", views: 812 },
  { name: "Biên bản họp bộ môn tháng 6", type: "DOCX", category: "Biên bản", owner: "Trần Hoàng Nam", updated: "06/06/2026", size: "920 KB", status: "Riêng tư", views: 321 },
];

export const activities = [
  { title: "Đề cương AI được cập nhật", meta: "Nguyễn Minh Anh · 10 phút trước", tone: "blue" },
  { title: "Google Drive đồng bộ thành công", meta: "Automation · 18 phút trước", tone: "green" },
  { title: "Yêu cầu quyền truy cập mới", meta: "Lê Thu Hà · 1 giờ trước", tone: "amber" },
  { title: "Khôi phục phiên bản v3", meta: "Trần Hoàng Nam · 3 giờ trước", tone: "blue" },
];

export const transfers = [
  { course: "Trí tuệ nhân tạo", code: "AI101", owner: "Nguyễn Minh Anh", recipient: "Lê Thu Hà", progress: 78, due: "30/06/2026" },
  { course: "Lập trình Python", code: "PY101", owner: "Phạm Đức Long", recipient: "Hoàng Mai", progress: 46, due: "15/07/2026" },
  { course: "Cơ sở dữ liệu", code: "DB201", owner: "Trần Hoàng Nam", recipient: "Vũ Anh", progress: 92, due: "20/06/2026" },
];

export const navItems = [
  ["Tổng quan", "/", null],
  ["Kho tài liệu", "/repository", null],
  ["Trợ lý tri thức", "/assistant", null],
  ["Chuyển giao tri thức", "/knowledge-transfer", null],
  ["Quản lý phiên bản", "/versions", null],
  ["Sao lưu & phục hồi", "/backup", null],
  ["Phân quyền", "/permissions", null],
  ["Báo cáo", "/reports", null],
  ["Quản lý tài khoản", "/users", "admin"],
  ["Cài đặt", "/settings", null],
] as const;

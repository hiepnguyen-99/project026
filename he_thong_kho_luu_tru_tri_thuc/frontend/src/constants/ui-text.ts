export const UI_TEXT = {
  dashboard: "Tổng quan",
  repository: "Kho tri thức",
  documentRepository: "Kho tài liệu",
  search: "Tìm kiếm",
  upload: "Tải lên",
  version: "Phiên bản",
  versions: "Các phiên bản",
  owner: "Chủ sở hữu",
  topic: "Chủ đề",
  documentType: "Loại tài liệu",
  visibility: "Phạm vi truy cập",
  policy: "Chính sách",
  governance: "Quản trị",
  governanceRules: "Quy tắc quản trị",
  knowledgeGovernance: "Quản trị tri thức",
  knowledgeTransfer: "Chuyển giao tri thức",
  assistant: "Trợ lý AI",
  backup: "Sao lưu",
  restore: "Khôi phục",
  verifyRestore: "Kiểm tra khả năng khôi phục",
  chunk: "Mảnh tri thức",
  storage: "Kho lưu trữ",
  objectStorage: "Kho đối tượng",
  health: "Trạng thái",
  status: "Trạng thái",
  auditLog: "Nhật ký hệ thống",
  masterTree: "Cây tri thức chuẩn",
  virtualTree: "Cây thư mục cá nhân",
  assignment: "Phân công",
  lecturerAssignment: "Phân công giảng viên",
  preview: "Xem trước",
  confirm: "Xác nhận",
  impact: "Tác động",
  risk: "Rủi ro",
};

export const STATUS_LABELS: Record<string, string> = {
  success: "Thành công",
  failed: "Thất bại",
  failure: "Thất bại",
  error: "Lỗi",
  pending: "Đang chờ",
  processing: "Đang xử lý",
  completed: "Hoàn thành",
  approved: "Đã duyệt",
  denied: "Từ chối",
  rejected: "Bị từ chối",
  active: "Đang áp dụng",
  inactive: "Ngừng áp dụng",
  draft: "Bản nháp",
  archived: "Đã lưu trữ",
  validated: "Hợp lệ",
  valid: "Hợp lệ",
  invalid: "Không hợp lệ",
  revoked: "Đã thu hồi",
  uploaded: "Đã tải lên",
  uploading: "Đang tải lên",
  analyzing: "Đang phân tích",
  saving_metadata: "Đang lưu thông tin",
  pending_confirmation: "Chờ xác nhận",
};

export const ROLE_TEXT: Record<string, string> = {
  admin: "Quản trị viên",
  head: "Trưởng bộ môn",
  lecturer: "Giảng viên",
  new_lecturer: "Giảng viên mới",
  ADMIN: "Quản trị viên",
  HEAD_OF_DEPARTMENT: "Trưởng bộ môn",
  LECTURER: "Giảng viên",
  NEW_LECTURER: "Giảng viên mới",
};

export function statusLabel(status?: string | null): string {
  if (!status) return "Chưa có dữ liệu";
  return STATUS_LABELS[status] || status;
}

export function yesNoLabel(value: boolean): string {
  return value ? "Có" : "Không";
}

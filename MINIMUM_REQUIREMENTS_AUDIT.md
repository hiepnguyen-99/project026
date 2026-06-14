# Kiểm tra yêu cầu tối thiểu

## Kết luận

Hệ thống đáp ứng đầy đủ bốn yêu cầu tối thiểu trong phạm vi MVP chạy cục bộ.

## 1. Policy lưu trữ, backup và phân quyền

- Quản trị viên cấu hình policy bằng form thân thiện.
- Storage policy điều khiển trực tiếp cây thư mục được đề xuất và tạo.
- Backup policy điều khiển trực tiếp ngưỡng đánh giá tuân thủ.
- Permission policy điều khiển trực tiếp việc tài liệu Private có cần chủ sở hữu phê duyệt hay không.
- AI prompt policy điều khiển prompt phân loại metadata và prompt hỏi đáp.

## 2. Trợ lý import tài liệu

Luồng đầy đủ:

```text
Chọn file
→ parser đọc TXT/MD/CSV/JSON/PDF/DOCX
→ AI phân tích metadata
→ đọc storage policy
→ đề xuất folder
→ giảng viên xác nhận/chỉnh sửa
→ lưu file gốc vào cây folder
→ tạo version, embedding và đồng bộ backup
```

## 3. Trợ lý hỏi đáp tài liệu

- Semantic retrieval bằng embedding.
- OpenAI Responses API khi có key; local fallback khi không có key.
- Lọc quyền trước retrieval.
- Trả citation theo tài liệu và phiên bản.
- Prompt hỏi đáp được cấu hình bằng policy.

## 4. Rollback

- Xem lịch sử phiên bản trên giao diện.
- Chủ sở hữu hoặc quản trị viên chọn phiên bản cần khôi phục.
- Rollback tạo phiên bản mới, giữ nguyên toàn bộ lịch sử cũ.
- Thao tác được ghi audit log.

## Xác minh

Bộ kiểm thử hành vi xác minh:

- Policy thay đổi quyền truy cập Private.
- Policy thay đổi kết quả compliance backup.
- DOCX được parser và AI import đọc trước khi lưu.
- Upload file gốc, folder policy và tải xuống.
- Versioning và rollback.
- RAG, access control, backup và restore.


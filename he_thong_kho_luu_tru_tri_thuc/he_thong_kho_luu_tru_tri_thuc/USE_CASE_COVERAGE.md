# Ma trận coverage Use Case EduVault

| Use case | Trạng thái MVP | API / chức năng |
| --- | --- | --- |
| UC00 Đăng nhập, xác thực | Hoàn chỉnh MVP | `/api/auth/login`, `/api/auth/logout`, bearer token |
| UC01 Lưu trữ tài liệu | Hoàn chỉnh MVP | AI phân tích metadata, đề xuất/xác nhận folder policy, lưu file, version, đồng bộ kho ngoài |
| UC02 Tìm kiếm, nguồn gốc | Hoàn chỉnh MVP | Danh sách/lọc tài liệu, `/api/documents/{id}/provenance` |
| UC03 Hỏi đáp, nguồn tham khảo | Hoàn chỉnh MVP | `/api/search`, citation theo tài liệu và phiên bản |
| UC04 Lịch sử, rollback | Hoàn chỉnh MVP | Versions API và rollback |
| UC05 Tiếp nhận học phần | Hoàn chỉnh MVP | `/api/onboarding/courses`, AI summary cục bộ |
| UC06 Tiếp nhận quy trình | Hoàn chỉnh MVP | `/api/onboarding/processes` |
| UC07 Quản lý phân quyền | Hoàn chỉnh MVP | RBAC, Public/Private, yêu cầu và phê duyệt |
| UC08 Khởi tạo chuyển giao | Hoàn chỉnh MVP | `POST /api/transfers` |
| UC09 Theo dõi chuyển giao | Hoàn chỉnh MVP | Danh sách và cập nhật tiến độ |
| UC10 Giám sát chất lượng | Hoàn chỉnh MVP | Lỗi thời, trùng lặp, học phần thiếu tài liệu |
| UC11 Báo cáo sử dụng | Hoàn chỉnh MVP | `/api/reports/usage` từ audit log |
| UC12 Quản lý policy | Hoàn chỉnh MVP | Xem/cập nhật policy lưu trữ, tự tạo cây folder, quyền, backup |
| UC13 Quản lý backup | Hoàn chỉnh MVP | Tạo snapshot, cấu hình kho ngoài, trạng thái đồng bộ và restore có safety backup |
| UC14 Quản lý người dùng | Hoàn chỉnh MVP | Tạo, cập nhật, khóa và gán vai trò qua API |
| UC15 Kiểm tra 3-2-1 | Hoàn chỉnh MVP | Báo cáo compliance từ trạng thái kho thật |
| UC16 Xem quyền truy cập | Hoàn chỉnh MVP | `/api/permissions` |

## Giới hạn tích hợp

- Google Drive, OneDrive và SharePoint hiện dùng adapter thư mục cục bộ để kiểm thử luồng đồng bộ an toàn.
- AI chạy fallback cục bộ khi chưa có key và tự chuyển sang OpenAI Responses API khi cấu hình `OPENAI_API_KEY`.
- PDF có text và DOCX được parser trực tiếp; PDF scan/ảnh vẫn cần OCR trong giai đoạn production hóa.
- PostgreSQL và MinIO thuộc giai đoạn production hóa.

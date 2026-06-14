# Hướng dẫn sử dụng EduVault

## 1. Khởi động hệ thống

Mở PowerShell tại thư mục dự án và chạy:

```powershell
python run_mvp.py
```

Truy cập:

- Giao diện: `http://127.0.0.1:8080`
- API documentation: `http://127.0.0.1:8080/docs`

## 2. Tài khoản thử nghiệm

Mật khẩu mặc định giống mã người dùng.

| Mã đăng nhập | Vai trò | Mật khẩu |
| --- | --- | --- |
| `GV001` | Giảng viên | `GV001` |
| `GVNEW` | Giảng viên mới | `GVNEW` |
| `TBM01` | Trưởng bộ môn | `TBM01` |
| `ADMIN` | Quản trị viên | `ADMIN` |

## 3. Upload và lưu trữ tài liệu

1. Chọn **Tải tài liệu**.
2. Chọn file hoặc kéo-thả file vào vùng upload.
3. Chọn **AI phân tích & đề xuất nơi lưu**.
4. Kiểm tra metadata AI đề xuất:
   - Tiêu đề
   - Chủ đề
   - Loại tài liệu
   - Quyền truy cập Public/Private
5. Kiểm tra hoặc chỉnh sửa **Thư mục lưu theo Policy**.
6. Chọn **Xác nhận và lưu**.

File gốc được lưu theo cây thư mục policy, ví dụ:

```text
Công nghệ thông tin/Học máy/Học liệu/Public/
```

Giới hạn file của MVP là 25 MB.

## 4. Quản lý tài liệu

Trong màn hình **Kho tài liệu**:

- Tìm tài liệu bằng tên, chủ đề hoặc chủ sở hữu.
- Chọn **File gốc** để tải file xuống.
- Chọn **Cập nhật** để tạo phiên bản mới.
- Chọn **Cây thư mục** để xem cấu trúc do policy tạo.

Mỗi lần cập nhật sẽ tạo phiên bản mới, không ghi đè lịch sử cũ.

### Xóa và khôi phục tài liệu

- Chủ sở hữu hoặc quản trị viên chọn **Xóa** để chuyển tài liệu vào **Thùng rác**.
- Tài liệu trong thùng rác không xuất hiện trong Kho tài liệu, tìm kiếm hoặc hỏi đáp AI.
- Chủ sở hữu có thể chọn **Khôi phục**.
- Chỉ quản trị viên được phép **Xóa vĩnh viễn**.

## 5. Hỏi đáp AI

1. Mở **Hỏi đáp AI**.
2. Nhập câu hỏi liên quan đến tài liệu trong kho.
3. AI sử dụng semantic retrieval để tìm nội dung liên quan.
4. Câu trả lời hiển thị kèm nguồn tham khảo.

AI chỉ truy xuất những tài liệu tài khoản hiện tại được phép xem.

Phạm vi chatbot được giới hạn chặt hơn giao diện xem tài liệu: chatbot chỉ sử dụng tài liệu **Public** và tài liệu **do chính người hỏi sở hữu**. Tài liệu Private của người khác không được đưa vào chatbot, kể cả đã được duyệt quyền xem.

Chủ sở hữu của tài liệu Private được hiển thị là **Ẩn danh** đối với người dùng khác.

## 6. Quyền truy cập tài liệu

### Public

Mọi người dùng hợp lệ có thể xem và sử dụng trong hỏi đáp AI.

### Private

Chỉ chủ sở hữu, quản trị viên hoặc người đã được phê duyệt mới có thể truy cập.

Để xin quyền:

1. Mở **Quyền truy cập**.
2. Tìm tài liệu bị hạn chế.
3. Chọn **Xin quyền truy cập**.
4. Chủ sở hữu mở cùng màn hình để duyệt hoặc từ chối.

## 7. Tiếp nhận tri thức

Màn hình **Tiếp nhận tri thức** hỗ trợ giảng viên mới:

- Xem tài liệu theo học phần.
- Nhận nội dung tổng hợp từ AI.
- Xem các quy trình công tác liên quan.

## 8. Chuyển giao học phần

Trưởng bộ môn hoặc quản trị viên có thể:

1. Mở **Chuyển giao học phần**.
2. Chọn **Khởi tạo**.
3. Nhập học phần, giảng viên bàn giao, người tiếp nhận và thời hạn.
4. Theo dõi và cập nhật phần trăm tiến độ.

## 9. Chất lượng và báo cáo

Trưởng bộ môn và quản trị viên có thể xem:

- Tài liệu lỗi thời.
- Tài liệu trùng lặp.
- Học phần thiếu tài liệu.
- Số lượt hỏi đáp AI.
- Số người dùng và phiên chuyển giao.
- Trạng thái tuân thủ backup 3-2-1.

## 10. Chức năng quản trị

Đăng nhập bằng `ADMIN` để sử dụng:

- Tạo, sửa hoặc khóa người dùng.
- Gán vai trò người dùng.
- Xem và cập nhật policy.
- Thêm và đồng bộ kho lưu trữ ngoài.
- Tạo backup hệ thống.
- Khôi phục từ backup.
- Xem audit log.

Khi khôi phục, hệ thống tự tạo safety backup trước khi restore.

### Quản lý người dùng

Trong **Quản trị → Quản lý người dùng**:

1. Chọn **Tạo người dùng** để mở form tạo tài khoản.
2. Nhập mã người dùng, họ tên, đơn vị, vai trò và mật khẩu ban đầu.
3. Chọn **Chỉnh sửa** trên tài khoản để đổi thông tin, vai trò hoặc khóa/mở tài khoản.

Form hiển thị mô tả quyền tương ứng khi chọn vai trò.

### Cấu hình Policy

Trong **Quản trị → Policy**, chọn **Cấu hình** tại quy tắc cần thay đổi.

- **Sao lưu an toàn 3-2-1:** nhập số bản sao, số loại kho và số bản ngoài hệ thống.
- **Quyền tài liệu riêng tư:** bật hoặc tắt yêu cầu chủ sở hữu phê duyệt.
- **Cấu trúc lưu trữ tài liệu:** chọn thứ tự thư mục và thời gian lưu tối thiểu.

Giao diện hiển thị kết quả hoặc đường dẫn ví dụ trước khi lưu. Người dùng không cần chỉnh sửa JSON trực tiếp.

## 11. Cấu hình AI OpenAI

Thiết lập trong file `.env`:

```text
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-5.4-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_BASE_URL=https://api.openai.com/v1
```

Sau khi thay đổi `.env`, cần khởi động lại hệ thống.

Kiểm tra trạng thái AI tại:

```text
http://127.0.0.1:8080/api/ai/status
```

Nếu OpenAI không khả dụng, hệ thống tự chuyển sang AI local fallback.

## 12. Dữ liệu hệ thống

```text
data/mvp/eduvault.db          Cơ sở dữ liệu SQLite
data/mvp/storage/             Nội dung và phiên bản tài liệu
data/mvp/storage/repository/  File gốc theo cây thư mục policy
data/mvp/backups/             Các bản backup
```

## 13. Xử lý lỗi thường gặp

### Không truy cập được trang web

Kiểm tra terminal đang chạy `python run_mvp.py` và truy cập đúng cổng `8080`.

### Thay đổi `.env` nhưng AI chưa nhận cấu hình

Dừng và khởi động lại server.

### Không thể xem tài liệu Private

Gửi yêu cầu truy cập và chờ chủ sở hữu phê duyệt.

### PDF hoặc DOCX không xuất hiện nội dung trong chatbot

MVP hiện lưu file gốc nhưng chưa tích hợp parser/OCR cho các định dạng này.

### Chạy kiểm thử hệ thống

```powershell
python -m pytest -q
```
# Kết nối Google Drive và OneDrive cá nhân

Mỗi giảng viên có thể tự kết nối kho cloud của mình tại menu **Kho cloud của tôi**. Hệ thống dùng OAuth; giảng viên đăng nhập trên trang chính thức của Google/Microsoft và EduVault không lưu mật khẩu cloud.

Quản trị viên cần đăng ký ứng dụng OAuth rồi cấu hình `.env`:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8080/api/cloud/callback/google_drive

MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_REDIRECT_URI=http://127.0.0.1:8080/api/cloud/callback/onedrive

TOKEN_ENCRYPTION_KEY=mot-chuoi-bi-mat-dai-va-ngau-nhien
```

Sau khi kết nối, file mới được giảng viên upload sẽ tự đồng bộ lên các kho cá nhân đang kết nối. Nút **Đồng bộ tài liệu của tôi** sẽ đồng bộ lại toàn bộ tài liệu hiện tại thuộc chính giảng viên đó. Token OAuth được mã hóa trong SQLite bằng `TOKEN_ENCRYPTION_KEY`.

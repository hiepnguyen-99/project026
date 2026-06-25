# UI Language Audit - EduVault

Ngay audit: 2026-06-24

Pham vi:
- `frontend/app/**`
- `frontend/components/**`
- `frontend/src/**`
- `frontend/lib/**`

Nguyen tac audit:
- Chi ghi nhan text co kha nang hien thi ra UI hoac anh huong truc tiep den UI.
- Bo qua ten bien, type, enum, API path, permission key, import, class CSS, code ky thuat khong hien thi.
- File bao cao nay khong sua code UI.

## Tom tat dieu hanh

EduVault chua dat chuan ngon ngu giao dien production cho san pham giao duc Viet Nam.

Van de lon nhat:
1. Sidebar/menu dang bi mojibake trong `frontend/src/config/role-menu.ts`, lam anh huong toan bo dieu huong.
2. Trang `policy/page.tsx` con rat nhieu English UI, mojibake va tieng Viet khong dau trong cac workflow quan trong.
3. Trang `knowledge-transfer/page.tsx` con nhieu text khong dau va header bang tieng Anh.
4. Trang `users/page.tsx`, `login-screen.tsx`, `audit-logs/page.tsx` con nhieu tieng Viet khong dau.
5. Mot so status tu backend dang hien thi raw value nhu `success`, `active`, `pending`, `approved`, `denied`.

Danh gia muc do dong nhat ngon ngu: **54/100**

Ly do cham diem:
- Sidebar la diem vao chinh nhung bi loi encoding: tru nang.
- Cac module moi khoi phuc nhu Backup, Operations, Search, Trash tuong doi tot hon.
- Policy/Governance va Knowledge Transfer la module demo quan trong nhung ngon ngu chua dong nhat.
- Con nhieu cum English chua duoc chuyen ngu: Policy, Master Tree, Assignment, Preview, Confirm, Impact, Risk, Action, Status.

## Nhom loi A - English UI

| File | Line | Current text | Recommended Vietnamese text |
|---|---:|---|---|
| `frontend/components/assistant-chat.tsx` | 343 | `EduVault Assistant` | `Trợ lý AI EduVault` |
| `frontend/components/assistant-chat.tsx` | 398 | `Nhập câu hỏi cho EduVault Assistant...` | `Nhập câu hỏi cho Trợ lý AI EduVault...` |
| `frontend/app/page.tsx` | 23 | `Bản backup` | `Bản sao lưu` |
| `frontend/app/page.tsx` | 24 | `Audit gần đây` | `Nhật ký gần đây` |
| `frontend/app/page.tsx` | 39 | `Audit log chỉ hiển thị cho quản trị viên.` | `Nhật ký hệ thống chỉ hiển thị cho quản trị viên.` |
| `frontend/app/backup/page.tsx` | 172 | `Vector Qdrant` | `Chỉ mục tìm kiếm Qdrant` |
| `frontend/app/backup/page.tsx` | 173 | `Object MinIO` | `Đối tượng MinIO` |
| `frontend/app/search/page.tsx` | 252 | `Policy` | `Chính sách` hoặc `Quy tắc` |
| `frontend/app/search/page.tsx` | 253 | `Mục policy` | `Mục chính sách` |
| `frontend/app/search/page.tsx` | 255 | `Audit` | `Nhật ký` |
| `frontend/app/search/page.tsx` | 268 | `Policy` | `Chính sách` |
| `frontend/app/repository/page.tsx` | 101 | `Manual Selection` | `Chọn thủ công` |
| `frontend/app/repository/page.tsx` | 110 | `Manual Selection` | `Chọn thủ công` |
| `frontend/app/repository/page.tsx` | 115 | `AI Applied` | `Theo gợi ý AI` |
| `frontend/app/repository/page.tsx` | 263 | `Policy active: ...` | `Chính sách đang áp dụng: ...` |
| `frontend/app/repository/page.tsx` | 263 | `Fallback theo folder_path hiện có` | `Dùng đường dẫn thư mục hiện có` |
| `frontend/app/repository/page.tsx` | 274 | `tải theo chunk` | `tải theo từng phần` |
| `frontend/app/repository/page.tsx` | 274 | `backup` | `sao lưu` |
| `frontend/app/settings/page.tsx` | 46 | `Đã upload policy. Hãy activate policy để cập nhật Master Folder Tree.` | `Đã tải chính sách lên. Hãy kích hoạt chính sách để cập nhật cây thư mục chuẩn.` |
| `frontend/app/settings/page.tsx` | 57 | `Master Folder Tree đã được cập nhật theo policy active mới.` | `Cây thư mục chuẩn đã được cập nhật theo chính sách đang áp dụng.` |
| `frontend/app/settings/page.tsx` | 80 | `Quản lý policy, Master Folder Tree và các cấu hình hệ thống.` | `Quản lý chính sách, cây thư mục chuẩn và cấu hình hệ thống.` |
| `frontend/app/settings/page.tsx` | 89 | `Policy Upload và Master Folder Tree` | `Tải chính sách và cây thư mục chuẩn` |
| `frontend/app/settings/page.tsx` | 89 | `Admin upload policy, activate...` | `Quản trị viên tải chính sách lên, kích hoạt một bản duy nhất...` |
| `frontend/app/settings/page.tsx` | 94 | `Tiêu đề policy` | `Tiêu đề chính sách` |
| `frontend/app/settings/page.tsx` | 100 | `Upload policy` | `Tải chính sách lên` |
| `frontend/app/settings/page.tsx` | 109 | `{policy.status}` | `map active/draft/archived sang tiếng Việt` |
| `frontend/app/settings/page.tsx` | 112 | `Activate` | `Kích hoạt` |
| `frontend/app/settings/page.tsx` | 123 | `Chưa có policy file. Admin hãy upload file policy...` | `Chưa có tệp chính sách. Quản trị viên hãy tải tệp chính sách...` |
| `frontend/app/settings/page.tsx` | 127 | `Virtual Folder View` | `Cây thư mục cá nhân` |
| `frontend/app/settings/page.tsx` | 133 | `Lecturer Assignment Policy` | `chính sách phân công giảng viên` |
| `frontend/app/settings/page.tsx` | 137 | `Settings` | `Cài đặt` |
| `frontend/app/settings/page.tsx` | 143 | `Master Tree active` | `Cây tri thức đang áp dụng` |
| `frontend/app/settings/page.tsx` | 145 | `Chưa có Master Tree active.` | `Chưa có cây tri thức đang áp dụng.` |
| `frontend/app/settings/page.tsx` | 215 | `Tìm node trong Master Tree...` | `Tìm nhánh trong cây tri thức...` |
| `frontend/app/policy/page.tsx` | 236 | `Knowledge Governance Center` | `Trung tâm quản trị tri thức` |
| `frontend/app/policy/page.tsx` | 237 | `policy`, `governance` | `chính sách`, `quản trị` |
| `frontend/app/policy/page.tsx` | 274 | `Active Policy` | `Chính sách đang áp dụng` |
| `frontend/app/policy/page.tsx` | 274 | `Admin cần activate policy` | `Quản trị viên cần kích hoạt chính sách` |
| `frontend/app/policy/page.tsx` | 275 | `Master Tree` | `Cây tri thức chuẩn` |
| `frontend/app/policy/page.tsx` | 275 | `Chưa có cây active` | `Chưa có cây đang áp dụng` |
| `frontend/app/policy/page.tsx` | 276 | `Assignment Count` | `Số phân công` |
| `frontend/app/policy/page.tsx` | 276 | `Unassigned Lecturers` | `Giảng viên chưa được phân công` |
| `frontend/app/policy/page.tsx` | 277 | `Last Change` | `Thay đổi gần nhất` |
| `frontend/app/policy/page.tsx` | 277 | `audit` | `nhật ký` |
| `frontend/app/policy/page.tsx` | 319 | `preview` | `bản xem trước` |
| `frontend/app/policy/page.tsx` | 339 | `confirm`, `refresh Master Tree/Audit` | `xác nhận`, `làm mới cây tri thức/nhật ký` |
| `frontend/app/policy/page.tsx` | 350 | `Knowledge Governance Agent` | `Trợ lý quản trị tri thức` |
| `frontend/app/policy/page.tsx` | 350 | `governance`, `preview impact` | `quản trị`, `xem trước tác động` |
| `frontend/app/policy/page.tsx` | 373 | `Confirm` | `Xác nhận` |
| `frontend/app/policy/page.tsx` | 378 | `Admin xem interpretation, tree changes...` | `Quản trị viên xem diễn giải, thay đổi cây và thay đổi quyền...` |
| `frontend/app/policy/page.tsx` | 382 | `Interpretation` | `Diễn giải` |
| `frontend/app/policy/page.tsx` | 391 | `Tree Changes` | `Thay đổi cây tri thức` |
| `frontend/app/policy/page.tsx` | 392 | `Permission Changes` | `Thay đổi quyền truy cập` |
| `frontend/app/policy/page.tsx` | 395 | `Applied audit` | `Nhật ký đã ghi` |
| `frontend/app/policy/page.tsx` | 400 | `Master Tree` | `cây tri thức chuẩn` |
| `frontend/app/policy/page.tsx` | 443 | `Permission Impact` | `Tác động tới quyền truy cập` |
| `frontend/app/policy/page.tsx` | 446 | `Rule ID` | `Mã quy tắc` |
| `frontend/app/policy/page.tsx` | 447 | `Rule Type` | `Loại quy tắc` |
| `frontend/app/policy/page.tsx` | 454 | `Impact`, `match`, `Access grants` | `Tác động`, `khớp`, `quyền truy cập sẽ cấp` |
| `frontend/app/policy/page.tsx` | 455 | `Risk Warning` | `Cảnh báo rủi ro` |
| `frontend/app/policy/page.tsx` | 470 | `Assignment Impact` | `Tác động phân công` |
| `frontend/app/policy/page.tsx` | 471 | `Virtual Tree Impact`, `Rebuild` | `Tác động cây cá nhân`, `Tạo lại` |
| `frontend/app/policy/page.tsx` | 472 | `Folder Permission Impact` | `Tác động quyền thư mục` |
| `frontend/app/policy/page.tsx` | 484 | `Knowledge risk` | `Rủi ro tri thức` |
| `frontend/app/policy/page.tsx` | 486 | `Policy compliance` | `Mức tuân thủ chính sách` |
| `frontend/app/policy/page.tsx` | 493 | `Advisor Impact` | `Tác động tư vấn` |
| `frontend/app/policy/page.tsx` | 508 | `Governance Score` | `Điểm quản trị` |
| `frontend/app/policy/page.tsx` | 509 | `Risk Summary` | `Tóm tắt rủi ro` |
| `frontend/app/policy/page.tsx` | 510 | `High Risk Areas` | `Khu vực rủi ro cao` |
| `frontend/app/policy/page.tsx` | 511 | `Recommended Actions` | `Hành động khuyến nghị` |
| `frontend/app/policy/page.tsx` | 512 | `Dependency Warnings` | `Cảnh báo phụ thuộc` |
| `frontend/app/policy/page.tsx` | 513 | `Course Gaps` | `Khoảng trống học phần` |
| `frontend/app/policy/page.tsx` | 521 | `Action` | `Hành động` |
| `frontend/app/policy/page.tsx` | 529 | `node`, `Master Tree` | `nhánh`, `cây tri thức chuẩn` |
| `frontend/app/policy/page.tsx` | 546 | `Policy học liệu khoa CNTT` | `Chính sách học liệu khoa CNTT` |
| `frontend/app/policy/page.tsx` | 569 | `Đã upload policy. Hãy activate...` | `Đã tải chính sách lên. Hãy kích hoạt...` |
| `frontend/app/policy/page.tsx` | 583 | `Policy đã được kích hoạt.` | `Chính sách đã được kích hoạt.` |
| `frontend/app/policy/page.tsx` | 642 | `Upload Policy` | `Tải chính sách` |
| `frontend/app/policy/page.tsx` | 642 | `Active Policy` | `Chính sách đang áp dụng` |
| `frontend/app/policy/page.tsx` | 654 | `Upload Policy` | `Tải chính sách lên` |
| `frontend/app/policy/page.tsx` | 657 | `Policy List` | `Danh sách chính sách` |
| `frontend/app/policy/page.tsx` | 660 | `Policy`, `Status`, `Structure`, `Created` | `Chính sách`, `Trạng thái`, `Cấu trúc`, `Ngày tạo` |
| `frontend/app/policy/page.tsx` | 670 | `Activate` | `Kích hoạt` |
| `frontend/app/policy/page.tsx` | 702 | `Activation Audit Summary` | `Tóm tắt nhật ký kích hoạt` |
| `frontend/app/policy/page.tsx` | 719 | `Policy Activation Preview` | `Xem trước kích hoạt chính sách` |
| `frontend/app/policy/page.tsx` | 721 | `Review impact before activating this policy.` | `Xem tác động trước khi kích hoạt chính sách này.` |
| `frontend/app/policy/page.tsx` | 725 | `Added Specializations` | `Nhóm chuyên môn được thêm` |
| `frontend/app/policy/page.tsx` | 726 | `Removed Specializations` | `Nhóm chuyên môn bị gỡ` |
| `frontend/app/policy/page.tsx` | 727 | `Matched Specializations` | `Nhóm chuyên môn khớp` |
| `frontend/app/policy/page.tsx` | 728 | `Virtual Trees` | `Cây thư mục cá nhân` |
| `frontend/app/policy/page.tsx` | 732 | `Assignment Impact` | `Tác động phân công` |
| `frontend/app/policy/page.tsx` | 733 | `Valid` | `Hợp lệ` |
| `frontend/app/policy/page.tsx` | 734 | `Needs resolution` | `Cần xử lý` |
| `frontend/app/policy/page.tsx` | 737 | `Folder Permission Impact` | `Tác động quyền thư mục` |
| `frontend/app/policy/page.tsx` | 738 | `Active permissions to deprecate` | `Quyền đang hiệu lực sẽ được ngừng dùng` |
| `frontend/app/policy/page.tsx` | 739 | `Will rebuild permissions` | `Sẽ tạo lại quyền truy cập` |
| `frontend/app/policy/page.tsx` | 743 | `Added` | `Được thêm` |
| `frontend/app/policy/page.tsx` | 746 | `Removed` | `Bị gỡ` |
| `frontend/app/policy/page.tsx` | 764 | `Confirm Activate` | `Xác nhận kích hoạt` |
| `frontend/app/policy/page.tsx` | 788 | `Knowledge Tree` | `Cây tri thức` |
| `frontend/app/policy/page.tsx` | 790 | `Master Tree active` | `cây tri thức đang áp dụng` |
| `frontend/app/policy/page.tsx` | 853 | `Active Assignment Count` | `Số phân công đang hiệu lực` |
| `frontend/app/policy/page.tsx` | 857 | `Import CSV Assignment` | `Nhập phân công từ CSV` |
| `frontend/app/policy/page.tsx` | 866 | `Preview` | `Xem trước` |
| `frontend/app/policy/page.tsx` | 867 | `Confirm & Provision` | `Xác nhận và cấp quyền` |
| `frontend/app/policy/page.tsx` | 898 | `Preview` | `Xem trước` |
| `frontend/app/policy/page.tsx` | 903 | `Total` | `Tổng số` |
| `frontend/app/policy/page.tsx` | 904 | `Valid` | `Hợp lệ` |
| `frontend/app/policy/page.tsx` | 905 | `Errors` | `Lỗi` |
| `frontend/app/policy/page.tsx` | 906 | `Warnings` | `Cảnh báo` |
| `frontend/app/policy/page.tsx` | 938 | `Policy Audit` | `Nhật ký chính sách` |
| `frontend/app/policy/page.tsx` | 941 | `Actor`, `Action`, `Status`, `Time` | `Người thực hiện`, `Hành động`, `Trạng thái`, `Thời gian` |
| `frontend/app/policy/page.tsx` | 949 | `Assignment Audit` | `Nhật ký phân công` |
| `frontend/app/policy/page.tsx` | 961 | `Policy request` | `Yêu cầu chính sách` |
| `frontend/app/policy/page.tsx` | 1029 | `AI Governance Assistant` | `Trợ lý quản trị AI` |
| `frontend/app/policy/page.tsx` | 1030 | `Import Policy` | `Nhập chính sách` |
| `frontend/app/policy/page.tsx` | 1033 | `Audit Log` | `Nhật ký` |
| `frontend/app/policy/page.tsx` | 1069 | `Admin` | `Quản trị viên` |
| `frontend/app/knowledge-transfer/page.tsx` | 171 | `Document`, `Topic`, `Type` | `Tài liệu`, `Chủ đề`, `Loại` |
| `frontend/app/knowledge-transfer/page.tsx` | 255 | `Priority`, `Action`, `Reason`, `Recommended Actions` | `Mức ưu tiên`, `Hành động`, `Lý do`, `Hành động khuyến nghị` |
| `frontend/app/knowledge-transfer/page.tsx` | 287 | `Specialization`, `Coverage`, `Assigned Lecturers`, `Readiness`, `Risk` | `Nhóm chuyên môn`, `Độ phủ`, `Giảng viên được phân công`, `Mức sẵn sàng`, `Rủi ro` |
| `frontend/app/knowledge-transfer/page.tsx` | 316 | `Lecturer`, `Specialization`, `Owned Documents`, `Dependency Risk` | `Giảng viên`, `Nhóm chuyên môn`, `Tài liệu sở hữu`, `Rủi ro phụ thuộc` |

## Nhom loi B - Vietnamese khong dau

| File | Line | Current text | Recommended Vietnamese text |
|---|---:|---|---|
| `frontend/components/login-screen.tsx` | 21 | `Dang nhap that bai.` | `Đăng nhập thất bại.` |
| `frontend/components/login-screen.tsx` | 33 | `Dang nhap vao kho tri thuc cua khoa.` | `Đăng nhập vào kho tri thức của khoa.` |
| `frontend/components/login-screen.tsx` | 36 | `Ma nguoi dung` | `Mã người dùng` |
| `frontend/components/login-screen.tsx` | 37 | `Mat khau` | `Mật khẩu` |
| `frontend/components/login-screen.tsx` | 40 | `Dang nhap` | `Đăng nhập` |
| `frontend/components/login-screen.tsx` | 42 | `Lien he quan tri vien neu ban chua co tai khoan.` | `Liên hệ quản trị viên nếu bạn chưa có tài khoản.` |
| `frontend/app/audit-logs/page.tsx` | 84 | `Ma nguoi dung` | `Mã người dùng` |
| `frontend/app/audit-logs/page.tsx` | 113 | `Dong thoi gian audit` | `Dòng thời gian nhật ký` |
| `frontend/app/audit-logs/page.tsx` | 113 | `Dang tai...` | `Đang tải...` |
| `frontend/app/audit-logs/page.tsx` | 113 | `Su kien moi nhat duoc sap xep giam dan theo thoi gian` | `Sự kiện mới nhất được sắp xếp giảm dần theo thời gian` |
| `frontend/app/knowledge-transfer/page.tsx` | 114 | `Dang tai phan quyen...` | `Đang tải phân quyền...` |
| `frontend/app/knowledge-transfer/page.tsx` | 149 | `Chuyen giao tri thuc` | `Chuyển giao tri thức` |
| `frontend/app/knowledge-transfer/page.tsx` | 150 | `Tom tat tri thuc` | `Tóm tắt tri thức` |
| `frontend/app/knowledge-transfer/page.tsx` | 151 | `Khong gian ban giao tri thuc...` | `Không gian bàn giao tri thức...` |
| `frontend/app/knowledge-transfer/page.tsx` | 152 | `Lam moi` | `Làm mới` |
| `frontend/app/knowledge-transfer/page.tsx` | 162 | `Tom tat tri thuc` | `Tóm tắt tri thức` |
| `frontend/app/knowledge-transfer/page.tsx` | 162 | `Tai lieu quy trinh co the doc` | `Tài liệu quy trình có thể đọc` |
| `frontend/app/knowledge-transfer/page.tsx` | 163 | `Tri thuc hoc phan` | `Tri thức học phần` |
| `frontend/app/knowledge-transfer/page.tsx` | 163 | `Hoc phan dang co tri thuc lien quan` | `Học phần đang có tri thức liên quan` |
| `frontend/app/knowledge-transfer/page.tsx` | 168 | `Tom tat cac tai lieu...` | `Tóm tắt các tài liệu...` |
| `frontend/app/knowledge-transfer/page.tsx` | 169 | `Chua co du lieu tom tat.` | `Chưa có dữ liệu tóm tắt.` |
| `frontend/app/knowledge-transfer/page.tsx` | 172 | `Chua co tai lieu quy trinh.` | `Chưa có tài liệu quy trình.` |
| `frontend/app/knowledge-transfer/page.tsx` | 181 | `Hoc phan va tai lieu lien quan...` | `Học phần và tài liệu liên quan...` |
| `frontend/app/knowledge-transfer/page.tsx` | 183 | `Hoc phan`, `Tai lieu lien quan`, `Chu de` | `Học phần`, `Tài liệu liên quan`, `Chủ đề` |
| `frontend/app/knowledge-transfer/page.tsx` | 184 | `Chua co hoc phan lien quan.` | `Chưa có học phần liên quan.` |
| `frontend/app/knowledge-transfer/page.tsx` | 201 | `Hoc phan`, `Ban giao tu`, `Ban giao cho`, `Tien do`, `Han chot`, `Trang thai` | `Học phần`, `Bàn giao từ`, `Bàn giao cho`, `Tiến độ`, `Hạn chót`, `Trạng thái` |
| `frontend/app/knowledge-transfer/page.tsx` | 202 | `Chua co phien chuyen giao.` | `Chưa có phiên chuyển giao.` |
| `frontend/app/knowledge-transfer/page.tsx` | 235 | `Bang dieu khien chuyen giao tri thuc` | `Bảng điều khiển chuyển giao tri thức` |
| `frontend/app/knowledge-transfer/page.tsx` | 241 | `Chinh sach dang ap dung:` | `Chính sách đang áp dụng:` |
| `frontend/app/knowledge-transfer/page.tsx` | 246 | `Do phu tai lieu` | `Độ phủ tài liệu` |
| `frontend/app/knowledge-transfer/page.tsx` | 246 | `hoc phan du tai lieu` | `học phần đủ tài liệu` |
| `frontend/app/knowledge-transfer/page.tsx` | 248 | `Muc san sang chuyen giao` | `Mức sẵn sàng chuyển giao` |
| `frontend/app/knowledge-transfer/page.tsx` | 248 | `Muc do rui ro` | `Mức độ rủi ro` |
| `frontend/app/knowledge-transfer/page.tsx` | 249 | `Khoang trong nghiem trong` | `Khoảng trống nghiêm trọng` |
| `frontend/app/knowledge-transfer/page.tsx` | 249 | `chuyen mon phu thuoc 1 GV` | `chuyên môn phụ thuộc một giảng viên` |
| `frontend/app/knowledge-transfer/page.tsx` | 253 | `Hanh dong uu tien` | `Hành động ưu tiên` |
| `frontend/app/knowledge-transfer/page.tsx` | 253 | `Cac viec nen lam tiep...` | `Các việc nên làm tiếp...` |
| `frontend/app/knowledge-transfer/page.tsx` | 269 | `Rui ro tri thuc noi bat` | `Rủi ro tri thức nổi bật` |
| `frontend/app/knowledge-transfer/page.tsx` | 285 | `Bang rui ro chuyen mon` | `Bảng rủi ro chuyên môn` |
| `frontend/app/knowledge-transfer/page.tsx` | 285 | `Do phu tai lieu...` | `Độ phủ tài liệu...` |
| `frontend/app/knowledge-transfer/page.tsx` | 299 | `Bang thieu tai lieu theo hoc phan` | `Bảng thiếu tài liệu theo học phần` |
| `frontend/app/knowledge-transfer/page.tsx` | 299 | `Cac hoc phan con thieu...` | `Các học phần còn thiếu...` |
| `frontend/app/knowledge-transfer/page.tsx` | 301 | `Hoc phan`, `Tai lieu con thieu`, `Do phu`, `Rui ro` | `Học phần`, `Tài liệu còn thiếu`, `Độ phủ`, `Rủi ro` |
| `frontend/app/knowledge-transfer/page.tsx` | 314 | `Bang phu thuoc giang vien` | `Bảng phụ thuộc giảng viên` |
| `frontend/app/knowledge-transfer/page.tsx` | 314 | `Phat hien chuyen mon...` | `Phát hiện chuyên môn...` |
| `frontend/app/knowledge-transfer/page.tsx` | 382 | `Hoan thanh` | `Hoàn thành` |
| `frontend/app/knowledge-transfer/page.tsx` | 382 | `Dang thuc hien` | `Đang thực hiện` |
| `frontend/app/knowledge-transfer/page.tsx` | 386 | `Nghiem trong` | `Nghiêm trọng` |
| `frontend/app/knowledge-transfer/page.tsx` | 388 | `Trung binh` | `Trung bình` |
| `frontend/app/knowledge-transfer/page.tsx` | 390 | `Khong ro` | `Không rõ` |
| `frontend/app/users/page.tsx` | 22 | `Giang vien`, `Giang vien moi`, `Truong bo mon`, `Quan tri vien` | `Giảng viên`, `Giảng viên mới`, `Trưởng bộ môn`, `Quản trị viên` |
| `frontend/app/users/page.tsx` | 77 | `Mat khau` | `Mật khẩu` |
| `frontend/app/users/page.tsx` | 88 | `Quan tri vien` | `Quản trị viên` |
| `frontend/app/users/page.tsx` | 147 | `Quan tri vien` | `Quản trị viên` |
| `frontend/app/users/page.tsx` | 152 | `Tai khoan dang hoat dong` | `Tài khoản đang hoạt động` |
| `frontend/app/users/page.tsx` | 215 | `Quan tri he thong` | `Quản trị hệ thống` |
| `frontend/app/users/page.tsx` | 216 | `Nguoi dung` | `Người dùng` |
| `frontend/app/users/page.tsx` | 217 | `Quan ly tai khoan...` | `Quản lý tài khoản...` |
| `frontend/app/users/page.tsx` | 218 | `Tao tai khoan` | `Tạo tài khoản` |
| `frontend/app/users/page.tsx` | 224 | `Yeu cau cap nhat ho so (... cho duyet)` | `Yêu cầu cập nhật hồ sơ (... chờ duyệt)` |
| `frontend/app/users/page.tsx` | 251 | `Tai khoan he thong` | `Tài khoản hệ thống` |
| `frontend/app/users/page.tsx` | 264 | `Hoat dong`, `Da khoa` | `Hoạt động`, `Đã khóa` |
| `frontend/app/users/page.tsx` | 287 | `Tao tai khoan thanh cong.` | `Tạo tài khoản thành công.` |
| `frontend/app/users/page.tsx` | 290 | `Da cap nhat tai khoan.` | `Đã cập nhật tài khoản.` |
| `frontend/app/policy/page.tsx` | 197 | `Chuyen GV001 sang IoT` | `Chuyển GV001 sang IoT` |
| `frontend/app/policy/page.tsx` | 198 | `Gan GV002 phu trach Data Science` | `Gán GV002 phụ trách Khoa học dữ liệu` |
| `frontend/app/policy/page.tsx` | 199 | `Bo GV001 khoi AI` | `Bỏ GV001 khỏi AI` |
| `frontend/app/policy/page.tsx` | 201 | `Hien tai khoa co rui ro gi?` | `Hiện tại khoa có rủi ro gì?` |
| `frontend/app/policy/page.tsx` | 202 | `Nhung viec nao nen lam tiep?` | `Những việc nào nên làm tiếp?` |
| `frontend/app/policy/page.tsx` | 203 | `Chuyen nganh nao dang thieu tri thuc?` | `Chuyên ngành nào đang thiếu tri thức?` |
| `frontend/app/policy/page.tsx` | 204 | `Them AI Agent thuoc AI` | `Thêm AI Agent thuộc AI` |
| `frontend/app/policy/page.tsx` | 205 | `Them hoc phan Data Engineering vao Data Science` | `Thêm học phần Kỹ thuật dữ liệu vào Khoa học dữ liệu` |
| `frontend/app/policy/page.tsx` | 600 | `Khong tao duoc activation preview.` | `Không tạo được bản xem trước kích hoạt.` |
| `frontend/app/policy/page.tsx` | 615 | `Policy da duoc kich hoat...` | `Chính sách đã được kích hoạt...` |
| `frontend/app/policy/page.tsx` | 618 | `Khong activate duoc policy.` | `Không kích hoạt được chính sách.` |

## Nhom loi C - Mojibake / loi encoding

| File | Line | Current text | Recommended Vietnamese text |
|---|---:|---|---|
| `frontend/src/config/role-menu.ts` | 42 | `Quáº£n trá»‹ viÃªn` | `Quản trị viên` |
| `frontend/src/config/role-menu.ts` | 43 | `TrÆ°á»Ÿng bá»™ mÃ´n` | `Trưởng bộ môn` |
| `frontend/src/config/role-menu.ts` | 44 | `Giáº£ng viÃªn` | `Giảng viên` |
| `frontend/src/config/role-menu.ts` | 45 | `Giáº£ng viÃªn má»›i` | `Giảng viên mới` |
| `frontend/src/config/role-menu.ts` | 111 | `Váº­n hÃ nh` | `Vận hành` |
| `frontend/src/config/role-menu.ts` | 112 | `Tá»•ng quan` | `Tổng quan` |
| `frontend/src/config/role-menu.ts` | 113 | `TÃ¬m kiáº¿m` | `Tìm kiếm` |
| `frontend/src/config/role-menu.ts` | 114 | `Kho tri thá»©c` | `Kho tri thức` |
| `frontend/src/config/role-menu.ts` | 115 | `ThÃ¹ng rÃ¡c` | `Thùng rác` |
| `frontend/src/config/role-menu.ts` | 116 | `Quáº£n trá»‹ tri thá»©c` | `Quản trị tri thức` |
| `frontend/src/config/role-menu.ts` | 117 | `Quy táº¯c quáº£n trá»‹` | `Quy tắc quản trị` |
| `frontend/src/config/role-menu.ts` | 118 | `NgÆ°á»i dÃ¹ng` | `Người dùng` |
| `frontend/src/config/role-menu.ts` | 119 | `PhÃ¢n quyá»n` | `Phân quyền` |
| `frontend/src/config/role-menu.ts` | 120 | `Sao lÆ°u` | `Sao lưu` |
| `frontend/src/config/role-menu.ts` | 121 | `BÃ¡o cÃ¡o` | `Báo cáo` |
| `frontend/src/config/role-menu.ts` | 122 | `Nháº­t kÃ½ há»‡ thá»‘ng` | `Nhật ký hệ thống` |
| `frontend/src/config/role-menu.ts` | 125 | `Tá»•ng quan` | `Tổng quan` |
| `frontend/src/config/role-menu.ts` | 126 | `TÃ¬m kiáº¿m` | `Tìm kiếm` |
| `frontend/src/config/role-menu.ts` | 127 | `Kho tri thá»©c` | `Kho tri thức` |
| `frontend/src/config/role-menu.ts` | 128 | `ThÃ¹ng rÃ¡c` | `Thùng rác` |
| `frontend/src/config/role-menu.ts` | 129 | `Quáº£n trá»‹ tri thá»©c` | `Quản trị tri thức` |
| `frontend/src/config/role-menu.ts` | 130 | `Quy táº¯c quáº£n trá»‹` | `Quy tắc quản trị` |
| `frontend/src/config/role-menu.ts` | 131 | `Äá»“ng bá»™` | `Đồng bộ` |
| `frontend/src/config/role-menu.ts` | 132 | `Chuyá»ƒn giao tri thá»©c` | `Chuyển giao tri thức` |
| `frontend/src/config/role-menu.ts` | 133 | `Trá»£ lÃ½ AI` | `Trợ lý AI` |
| `frontend/src/config/role-menu.ts` | 134 | `BÃ¡o cÃ¡o` | `Báo cáo` |
| `frontend/src/config/role-menu.ts` | 137 | `Tá»•ng quan` | `Tổng quan` |
| `frontend/src/config/role-menu.ts` | 138 | `TÃ¬m kiáº¿m` | `Tìm kiếm` |
| `frontend/src/config/role-menu.ts` | 139 | `Kho tri thá»©c` | `Kho tri thức` |
| `frontend/src/config/role-menu.ts` | 140 | `ThÃ¹ng rÃ¡c` | `Thùng rác` |
| `frontend/src/config/role-menu.ts` | 141 | `Äá»“ng bá»™` | `Đồng bộ` |
| `frontend/src/config/role-menu.ts` | 142 | `PhiÃªn báº£n` | `Phiên bản` |
| `frontend/src/config/role-menu.ts` | 143 | `Trá»£ lÃ½ AI` | `Trợ lý AI` |
| `frontend/src/config/role-menu.ts` | 144 | `Há»“ sÆ¡` | `Hồ sơ` |
| `frontend/src/config/role-menu.ts` | 147 | `Tá»•ng quan` | `Tổng quan` |
| `frontend/src/config/role-menu.ts` | 148 | `TÃ¬m kiáº¿m` | `Tìm kiếm` |
| `frontend/src/config/role-menu.ts` | 149 | `Chuyá»ƒn giao tri thá»©c` | `Chuyển giao tri thức` |
| `frontend/src/config/role-menu.ts` | 150 | `Äá»“ng bá»™` | `Đồng bộ` |
| `frontend/src/config/role-menu.ts` | 151 | `Trá»£ lÃ½ AI` | `Trợ lý AI` |
| `frontend/src/config/role-menu.ts` | 152 | `Há»“ sÆ¡` | `Hồ sơ` |
| `frontend/app/policy/page.tsx` | 236-237 | `Äiá»u phá»‘i...`, `tri thá»©c`, `giÃ¡o viÃªn` | `Điều phối chính sách, cây tri thức, phân công giảng viên...` |
| `frontend/app/policy/page.tsx` | 319 | `Lá»‡nh chÆ°a Ä‘á»§ rÃµ...` | `Lệnh chưa đủ rõ để tạo bản xem trước.` |
| `frontend/app/policy/page.tsx` | 342 | `KhÃ´ng confirm Ä‘Æ°á»£c...` | `Không xác nhận được thay đổi.` |
| `frontend/app/policy/page.tsx` | 378 | `Káº¿t quáº£ phÃ¢n tÃ­ch` | `Kết quả phân tích` |
| `frontend/app/policy/page.tsx` | 443 | `ChÆ°a cÃ³ dá»¯ liá»‡u impact.` | `Chưa có dữ liệu tác động.` |
| `frontend/app/policy/page.tsx` | 533-542 | `KhÃ´ng cÃ³`, `quyá»n`, `TÃ i liá»‡u` | `Không có`, `quyền`, `Tài liệu` |
| `frontend/app/settings/page.tsx` | 85 | `Chá»‰ quáº£n trá»‹ viÃªn...` | `Chỉ quản trị viên...` |
| `frontend/app/settings/page.tsx` | 94 | `TiÃªu Ä‘á» policy` | `Tiêu đề chính sách` |
| `frontend/app/settings/page.tsx` | 96 | `Chá»n file` | `Chọn tệp` |
| `frontend/app/settings/page.tsx` | 113 | `XÃ³a` | `Xóa` |
| `frontend/app/settings/page.tsx` | 119 | `ChÆ°a nháº­n diá»‡n khoa` | `Chưa nhận diện khoa` |
| `frontend/app/settings/page.tsx` | 129 | `Há»‡ thá»‘ng chÆ°a cÃ³ policy active...` | `Hệ thống chưa có chính sách đang áp dụng...` |
| `frontend/app/settings/page.tsx` | 137 | `KhÃ´ng thá»ƒ tá»± tick...` | `Không thể tự chọn chuyên môn...` |
| `frontend/app/settings/page.tsx` | 165 | `Quyá»n tÃ i liá»‡u riÃªng tÆ°` | `Quyền tài liệu riêng tư` |
| `frontend/app/settings/page.tsx` | 168 | `Chá»§ sá»Ÿ há»¯u pháº£i phÃª duyá»‡t` | `Chủ sở hữu phải phê duyệt` |
| `frontend/app/settings/page.tsx` | 171 | `LuÃ´n báº­t` | `Luôn bật` |
| `frontend/app/knowledge-transfer/page.tsx` | 235 | `Theo dÃµi khoáº£ng trá»‘ng...` | `Theo dõi khoảng trống...` |
| `frontend/app/knowledge-transfer/page.tsx` | 241 | `ChÆ°a cÃ³ policy active` | `Chưa có chính sách đang áp dụng` |
| `frontend/app/knowledge-transfer/page.tsx` | 299-316 | `KhÃ´ng cÃ³`, `ChÆ°a cÃ³ dá»¯ liá»‡u...` | `Không có`, `Chưa có dữ liệu...` |

## Dictionary chuan de dung toan he thong

| English / Raw | Vietnamese standard |
|---|---|
| Dashboard | Tổng quan |
| Repository | Kho tri thức |
| Document Repository | Kho tài liệu |
| Search | Tìm kiếm |
| Global Search | Tìm kiếm toàn hệ thống |
| Upload | Tải lên |
| Download | Tải xuống |
| Version | Phiên bản |
| Versions | Các phiên bản |
| Owner | Chủ sở hữu |
| Topic | Chủ đề |
| Type | Loại |
| Document Type | Loại tài liệu |
| Visibility | Phạm vi truy cập |
| Public | Công khai |
| Private | Riêng tư |
| Policy | Chính sách |
| Governance | Quản trị |
| Governance Rules | Quy tắc quản trị |
| Knowledge Governance | Quản trị tri thức |
| Knowledge Transfer | Chuyển giao tri thức |
| Assistant | Trợ lý AI |
| AI Assistant | Trợ lý AI |
| Backup | Sao lưu |
| Restore | Khôi phục |
| Verify Restore | Kiểm tra khả năng khôi phục |
| Chunk | Mảnh tri thức |
| Chunks | Mảnh tri thức |
| Storage | Kho lưu trữ |
| Object Storage | Kho đối tượng |
| Database | Cơ sở dữ liệu |
| Queue | Hàng đợi |
| Health | Trạng thái |
| Status | Trạng thái |
| Success | Thành công |
| Failed | Thất bại |
| Pending | Đang chờ |
| Completed | Hoàn thành |
| Active | Đang áp dụng |
| Draft | Bản nháp |
| Archived | Đã lưu trữ |
| Approved | Đã duyệt |
| Denied | Từ chối |
| Rejected | Bị từ chối |
| Create | Tạo |
| Edit | Chỉnh sửa |
| Delete | Xóa |
| Permanent Delete | Xóa vĩnh viễn |
| Confirm | Xác nhận |
| Preview | Xem trước |
| Impact | Tác động |
| Risk | Rủi ro |
| Risk Warning | Cảnh báo rủi ro |
| Recommended Actions | Hành động khuyến nghị |
| Assignment | Phân công |
| Lecturer Assignment | Phân công giảng viên |
| Master Tree | Cây tri thức chuẩn |
| Virtual Tree | Cây thư mục cá nhân |
| Folder Permission | Quyền thư mục |
| Access Grant | Quyền truy cập được cấp |
| Audit Log | Nhật ký hệ thống |
| Workflow | Quy trình tự động |
| Heartbeat | Tín hiệu hoạt động |
| Offline | Không có tín hiệu gần đây |
| Online | Đang có tín hiệu |
| New Chat | Cuộc hội thoại mới |
| Clear Chat | Xóa nội dung chat |
| Department | Bộ môn |
| Specialization | Nhóm chuyên môn |
| Course | Học phần |
| Coverage | Độ phủ |
| Readiness | Mức sẵn sàng |
| Dependency | Phụ thuộc |

## Top 50 text can sua truoc

Thu tu uu tien theo muc do anh huong demo va tan suat hien thi.

1. `frontend/src/config/role-menu.ts:42` - `Quáº£n trá»‹ viÃªn` -> `Quản trị viên`
2. `frontend/src/config/role-menu.ts:43` - `TrÆ°á»Ÿng bá»™ mÃ´n` -> `Trưởng bộ môn`
3. `frontend/src/config/role-menu.ts:44` - `Giáº£ng viÃªn` -> `Giảng viên`
4. `frontend/src/config/role-menu.ts:45` - `Giáº£ng viÃªn má»›i` -> `Giảng viên mới`
5. `frontend/src/config/role-menu.ts:111-152` - toàn bộ label menu mojibake -> thay bằng tiếng Việt chuẩn
6. `frontend/app/policy/page.tsx:236` - `Knowledge Governance Center` -> `Trung tâm quản trị tri thức`
7. `frontend/app/policy/page.tsx:237` - mô tả mojibake/English -> `Điều phối chính sách, cây tri thức...`
8. `frontend/app/policy/page.tsx:274` - `Active Policy` -> `Chính sách đang áp dụng`
9. `frontend/app/policy/page.tsx:275` - `Master Tree` -> `Cây tri thức chuẩn`
10. `frontend/app/policy/page.tsx:276` - `Assignment Count` -> `Số phân công`
11. `frontend/app/policy/page.tsx:277` - `Last Change` -> `Thay đổi gần nhất`
12. `frontend/app/policy/page.tsx:350` - `Knowledge Governance Agent` -> `Trợ lý quản trị tri thức`
13. `frontend/app/policy/page.tsx:373` - `Confirm` -> `Xác nhận`
14. `frontend/app/policy/page.tsx:378` - `interpretation/tree changes/permission changes` -> `diễn giải/thay đổi cây/thay đổi quyền`
15. `frontend/app/policy/page.tsx:382` - `Interpretation` -> `Diễn giải`
16. `frontend/app/policy/page.tsx:391` - `Tree Changes` -> `Thay đổi cây tri thức`
17. `frontend/app/policy/page.tsx:392` - `Permission Changes` -> `Thay đổi quyền truy cập`
18. `frontend/app/policy/page.tsx:446` - `Rule ID` -> `Mã quy tắc`
19. `frontend/app/policy/page.tsx:447` - `Rule Type` -> `Loại quy tắc`
20. `frontend/app/policy/page.tsx:454` - `Impact/Access grants` -> `Tác động/Quyền truy cập được cấp`
21. `frontend/app/policy/page.tsx:455` - `Risk Warning` -> `Cảnh báo rủi ro`
22. `frontend/app/policy/page.tsx:470` - `Assignment Impact` -> `Tác động phân công`
23. `frontend/app/policy/page.tsx:471` - `Virtual Tree Impact` -> `Tác động cây thư mục cá nhân`
24. `frontend/app/policy/page.tsx:472` - `Folder Permission Impact` -> `Tác động quyền thư mục`
25. `frontend/app/policy/page.tsx:508` - `Governance Score` -> `Điểm quản trị`
26. `frontend/app/policy/page.tsx:509` - `Risk Summary` -> `Tóm tắt rủi ro`
27. `frontend/app/policy/page.tsx:510` - `High Risk Areas` -> `Khu vực rủi ro cao`
28. `frontend/app/policy/page.tsx:511` - `Recommended Actions` -> `Hành động khuyến nghị`
29. `frontend/app/policy/page.tsx:512` - `Dependency Warnings` -> `Cảnh báo phụ thuộc`
30. `frontend/app/policy/page.tsx:513` - `Course Gaps` -> `Khoảng trống học phần`
31. `frontend/app/policy/page.tsx:642` - `Upload Policy` -> `Tải chính sách`
32. `frontend/app/policy/page.tsx:657` - `Policy List` -> `Danh sách chính sách`
33. `frontend/app/policy/page.tsx:660` - `Policy/Status/Structure/Created` -> `Chính sách/Trạng thái/Cấu trúc/Ngày tạo`
34. `frontend/app/policy/page.tsx:719` - `Policy Activation Preview` -> `Xem trước kích hoạt chính sách`
35. `frontend/app/policy/page.tsx:764` - `Confirm Activate` -> `Xác nhận kích hoạt`
36. `frontend/app/policy/page.tsx:1029` - `AI Governance Assistant` -> `Trợ lý quản trị AI`
37. `frontend/app/knowledge-transfer/page.tsx:149-152` - header không dấu -> tiếng Việt có dấu
38. `frontend/app/knowledge-transfer/page.tsx:171` - `Document/Topic/Type` -> `Tài liệu/Chủ đề/Loại`
39. `frontend/app/knowledge-transfer/page.tsx:235` - `Bang dieu khien chuyen giao tri thuc` -> `Bảng điều khiển chuyển giao tri thức`
40. `frontend/app/knowledge-transfer/page.tsx:255` - `Priority/Action/Reason/Recommended Actions` -> tiếng Việt chuẩn
41. `frontend/app/knowledge-transfer/page.tsx:287` - `Specialization/Coverage/...` -> tiếng Việt chuẩn
42. `frontend/app/knowledge-transfer/page.tsx:316` - `Lecturer/Specialization/Owned Documents/Dependency Risk` -> tiếng Việt chuẩn
43. `frontend/app/users/page.tsx:22` - role labels không dấu -> tiếng Việt có dấu
44. `frontend/app/users/page.tsx:215-218` - header/nút không dấu -> tiếng Việt có dấu
45. `frontend/components/login-screen.tsx:33-42` - login text không dấu -> tiếng Việt có dấu
46. `frontend/app/settings/page.tsx:89` - `Policy Upload và Master Folder Tree` -> `Tải chính sách và cây thư mục chuẩn`
47. `frontend/app/settings/page.tsx:100` - `Upload policy` -> `Tải chính sách lên`
48. `frontend/app/settings/page.tsx:127` - `Virtual Folder View` -> `Cây thư mục cá nhân`
49. `frontend/app/repository/page.tsx:101-115` - `Manual Selection/AI Applied` -> `Chọn thủ công/Theo gợi ý AI`
50. `frontend/app/search/page.tsx:252-268` - `Policy`, `Policy Item` -> `Chính sách`, `Mục chính sách`

## Rủi ro nếu chưa sửa

- Hội đồng/giảng viên nhìn vào sidebar bị mojibake sẽ đánh giá sản phẩm chưa ổn định.
- Module quản trị tri thức dùng nhiều thuật ngữ English, làm mất cảm giác sản phẩm giáo dục Việt Nam.
- Các status raw như `active`, `success`, `pending` khiến UI giống công cụ dev hơn là SaaS production.
- Từ `policy`, `governance`, `Master Tree`, `Assignment`, `Preview`, `Confirm` đang bị dùng lẫn với tiếng Việt, cần thống nhất trước demo.

## Kết luận

Ngôn ngữ UI hiện tại: **chưa đạt chuẩn production**.

Mục tiêu ngắn hạn để lên mức demo tốt:
1. Sửa toàn bộ mojibake trong `role-menu.ts`.
2. Chuẩn hóa `policy/page.tsx`.
3. Chuẩn hóa `knowledge-transfer/page.tsx`.
4. Chuẩn hóa `users/page.tsx` và `login-screen.tsx`.
5. Thêm helper map status/backend raw value sang tiếng Việt trước khi render.


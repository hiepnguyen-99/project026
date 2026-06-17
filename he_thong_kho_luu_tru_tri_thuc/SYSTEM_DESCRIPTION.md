# Mô tả chi tiết hệ thống EduVault MVP

> Cập nhật: 2026-06-12

---

## 1. Tổng quan

**EduVault** là hệ thống kho lưu trữ tri thức AI dành cho khoa/bộ môn đại học. Hệ thống cho phép giảng viên upload tài liệu, AI tự phân loại và gắn metadata, sau đó khai thác lại bằng chatbot hỏi đáp tiếng Việt có trích dẫn nguồn.

MVP hiện tại chạy độc lập trên một máy với:
- **Backend**: FastAPI + SQLite (có thể chuyển sang MySQL)
- **Frontend**: Next.js 15 + React 19 + TypeScript + Tailwind CSS
- **AI**: OpenAI API (gpt-5.4-mini + text-embedding-3-small) với local fallback khi không có key
- **Entrypoint chính**: `python run_mvp.py` → `http://127.0.0.1:8080`
- **Demo V1 không cần dependency**: `python web_demo.py` → `http://127.0.0.1:8000`

---

## 2. Cấu trúc thư mục

```
he_thong_kho_luu_tru_tri_thuc/
├── src/eduvault/               # Backend Python
│   ├── main.py                 # FastAPI app, routes, auth
│   ├── database.py             # SQLite/MySQL schema & queries
│   ├── ai.py                   # AI provider (OpenAI + local fallback)
│   ├── services.py             # Business logic (~1000+ dòng)
│   └── cloud.py                # Google Drive & OneDrive OAuth/sync
├── frontend/                   # Next.js 15 frontend
│   ├── app/                    # App Router pages
│   ├── components/             # Reusable components
│   └── lib/                    # API client, hooks, types
├── database/
│   ├── mysql_8_4_production_schema.sql   # Schema production đầy đủ
│   └── PRODUCTION_DATABASE_ARCHITECTURE.md
├── web/                        # Demo V1 (static HTML)
│   ├── index.html
│   └── mvp.html
├── data/
│   ├── demo_state.json         # State demo V1
│   └── mvp/
│       ├── eduvault.db         # SQLite database runtime
│       ├── storage/            # Nội dung tài liệu theo phiên bản
│       │   └── repository/     # File gốc tổ chức theo folder policy
│       └── backups/            # Snapshot backup
├── scripts/
│   └── migrate_sqlite_to_mysql.py
├── tests/
│   ├── test_mvp_api.py
│   └── test_web_demo.py
├── run_mvp.py                  # Entrypoint MVP
├── web_demo.py                 # Entrypoint Demo V1
├── requirements.txt
└── docker-compose.mysql.yml
```

---

## 3. Backend — src/eduvault/

### 3.1 main.py — FastAPI Application

Khoảng **40+ API endpoints** được nhóm theo chức năng:

| Nhóm | Endpoint | Mô tả |
|------|----------|-------|
| Auth | `POST /api/auth/login` | Đăng nhập bằng mã + mật khẩu |
| Dashboard | `GET /api/dashboard` | Thống kê tổng quan cho user |
| Documents | `POST /api/documents` | Tạo tài liệu mới |
| Documents | `GET /api/documents/{id}` | Chi tiết + nội dung |
| Documents | `PUT /api/documents/{id}` | Cập nhật (tạo version mới) |
| Documents | `POST /api/documents/{id}/delete` | Xóa mềm |
| Documents | `POST /api/documents/{id}/restore` | Khôi phục từ thùng rác |
| Versions | `GET /api/documents/{id}/versions` | Lịch sử phiên bản |
| Versions | `POST /api/documents/{id}/rollback` | Rollback về version trước |
| AI | `POST /api/analyze` | AI đề xuất metadata từ nội dung |
| AI | `POST /api/ask` | Chatbot RAG hỏi đáp |
| AI | `GET /api/ai/status` | Trạng thái provider (local/openai) |
| Access | `POST /api/access-requests` | Xin quyền tài liệu Private |
| Access | `GET /api/permissions` | Danh sách quyền của user |
| Onboarding | `GET /api/onboarding/courses` | Danh sách học phần |
| Onboarding | `POST /api/onboarding/courses/{code}/summary` | AI tổng hợp học phần |
| Onboarding | `POST /api/onboarding/processes/summary` | AI tổng hợp quy trình |
| Transfers | `POST /api/transfers` | Khởi tạo chuyển giao học phần |
| Transfers | `GET /api/transfers/{id}/progress` | Tiến độ chuyển giao |
| Admin | `POST /api/admin/backups` | Tạo backup thủ công |
| Admin | `POST /api/admin/backups/{id}/restore` | Khôi phục từ backup |
| Admin | `GET /api/admin/policies` | Danh sách policy |
| Admin | `PUT /api/admin/policies/{key}` | Cập nhật policy |
| Admin | `POST /api/admin/users` | Tạo tài khoản user |
| Reports | `GET /api/reports/usage` | Báo cáo sử dụng |
| Reports | `GET /api/reports/quality` | Báo cáo chất lượng kho |
| Reports | `GET /api/reports/compliance` | Kiểm tra tuân thủ 3-2-1 |
| Cloud | OAuth + sync endpoints cho Google Drive, OneDrive | |

**Middleware**: CORS cho phép frontend Next.js gọi API.

**Auth dependency**: `current_user()` — đọc Bearer token từ header, tra sessions table, trả về user object. `require_roles(*roles)` — kiểm tra role trước khi vào route.

---

### 3.2 database.py — Data Layer

Hỗ trợ **hai database engine**:

| Engine | Kích hoạt | Dùng cho |
|--------|-----------|----------|
| SQLite | Mặc định | Development, MVP |
| MySQL 8.4+ | `DATABASE_PROVIDER=mysql` | Production |

**16 bảng trong SQLite schema:**

| Bảng | Mô tả |
|------|-------|
| `users` | Tài khoản (code, name, role, department, password_hash) |
| `sessions` | Token phiên đăng nhập |
| `documents` | Metadata tài liệu (title, topic, doc_type, visibility, version, soft-delete) |
| `versions` | Lịch sử phiên bản — mỗi lần cập nhật tạo 1 bản ghi |
| `file_assets` | File gốc đã upload (tên, mime, kích thước) |
| `chunks` | Đoạn text + vector embedding cho RAG |
| `access_requests` | Yêu cầu truy cập tài liệu Private (pending/approved/denied) |
| `audit_logs` | Nhật ký hành động của user (actor, action, resource, detail JSON) |
| `policies` | Cấu hình hệ thống dạng key-value JSON |
| `backup_logs` | Lịch sử backup |
| `courses` | Danh sách học phần và các loại tài liệu bắt buộc |
| `transfers` | Phiên chuyển giao học phần (from, to, deadline, progress) |
| `external_storages` | Cấu hình kho lưu trữ ngoài |
| `sync_logs` | Log đồng bộ từng tài liệu lên cloud |
| `cloud_connections` | OAuth token Google Drive / OneDrive (mã hóa Fernet) |
| `oauth_states` | State token CSRF cho OAuth flow |

**Lưu ý MySQL**: Module tự dịch syntax SQLite (`?` → `%s`, `ON CONFLICT` → `ON DUPLICATE KEY`) để cùng một codebase chạy được cả hai engine.

---

### 3.3 ai.py — AI Provider

Class `AIProvider` hoạt động ở hai chế độ, tự chuyển khi khởi động:

**OpenAI mode** (khi có `OPENAI_API_KEY`):
- `metadata()` — gọi gpt-5.4-mini, trả về JSON: title, topic, doc_type, summary, keywords
- `answer()` — gọi gpt-5.4-mini với context RAG, trả lời tiếng Việt + trích dẫn
- `embed()` — gọi text-embedding-3-small, vector 1536 chiều
- `ocr_images()` — gọi OpenAI Vision để đọc PDF scan

**Local mode** (fallback không cần API):
- `metadata()` — keyword matching rules theo nội dung
- `answer()` — template-based summary
- `embed()` — hash SHA256 từng từ → vector 128 chiều, normalize L2 (deterministic, searchable)

Endpoint `GET /api/ai/status` báo cáo mode đang hoạt động.

---

### 3.4 services.py — Business Logic

File trọng tâm (~1000+ dòng), chứa toàn bộ logic nghiệp vụ:

**Document operations:**
- `create_document()` — lưu version 1, tạo metadata, index chunks
- `update_document()` — tạo version mới, re-index
- `soft_delete_document()` / `restore_deleted_document()` / `permanently_delete_document()`
- `content_for()` — đọc nội dung text từ storage path

**AI processing:**
- `extract_text()` — parse file: TXT/MD/CSV/JSON (đọc trực tiếp), PDF có text (PyPDF), PDF scan (OpenAI Vision OCR), DOCX (XML extraction)
- `guess_metadata()` — gọi AI.metadata() với fallback rules
- `index_document()` — chunk nội dung → embed từng chunk → lưu vào bảng chunks
- `ask()` — embed câu hỏi → cosine similarity search trên chunks → filter quyền → gọi AI.answer()

**Access control:**
- `can_read(user, doc)` — public || owner || approved access_request
- `list_documents(user)` — tài liệu user được xem (public + owned + approved)
- `rag_documents(user)` — STRICT: chỉ public + owned (chatbot không dùng tài liệu approved của người khác)
- `anonymize_document()` — ẩn tên chủ sở hữu tài liệu Private

**Storage & Backup:**
- `suggest_folder()` — tính đường dẫn thư mục từ policy template + metadata
- `save_file_asset()` — lưu file gốc vào `storage/repository/{folder_path}/{doc_id}/v{ver}_{filename}`
- `sync_document()` — upload lên Google Drive / OneDrive, ghi sync_logs
- `create_backup()` — snapshot toàn bộ eduvault.db + thư mục storage
- `restore_backup()` — khôi phục từ snapshot

**Reporting:**
- `usage_report()` — thống kê theo khoảng thời gian
- `quality_report()` — phát hiện tài liệu lỗi thời / trùng lặp (content hash) / học phần thiếu tài liệu
- `compliance_report()` — kiểm tra 3-2-1: đếm bản sao local + cloud providers + offsite
- `knowledge_summary()` — AI tổng hợp tài liệu của học phần cho giảng viên mới

**Audit:**
- `audit(actor, action, resource_type, resource_id, detail)` — ghi log mọi hành động

---

### 3.5 cloud.py — Cloud Storage Integration

**Hỗ trợ**: Google Drive API, Microsoft Graph API (OneDrive)

**OAuth flow**:
1. `authorization_url(provider, user_code)` → trả về URL đăng nhập + state token CSRF
2. User đăng nhập Google/Microsoft, callback về `/api/cloud/callback/{provider}`
3. `exchange_code()` — đổi auth code lấy access_token + refresh_token
4. Token được mã hóa Fernet trước khi lưu vào `cloud_connections`

**Sync**:
- `sync_user_document(user_code, doc_id)` — upload file lên tất cả cloud đã kết nối
- Tự động refresh token khi hết hạn
- Ghi log kết quả vào `sync_logs`

**Quản lý**:
- `list_connections(user_code)` — danh sách kết nối cloud của user
- `disconnect(user_code, provider)` — hủy kết nối

> SharePoint: cấu trúc code hỗ trợ nhưng OAuth chưa implement.

---

## 4. Frontend — Next.js 15

### 4.1 Các trang (App Router)

| Trang | Route | Mô tả |
|-------|-------|-------|
| Dashboard | `/` | Thống kê, danh sách tài liệu, trạng thái backup |
| Kho tài liệu | `/repository` | Upload, xem, lọc, tải xuống tài liệu |
| Trợ lý AI | `/assistant` | Chatbot RAG hỏi đáp với trích dẫn |
| Chi tiết tài liệu | `/documents/[id]` | Nội dung, metadata, lịch sử version, access requests |
| Lịch sử phiên bản | `/versions` | Timeline, xem diff, rollback |
| Backup | `/backup` | Trạng thái 3-2-1, log đồng bộ, nút restore |
| Chuyển giao tri thức | `/knowledge-transfer` | Onboarding học phần/quy trình cho giảng viên mới |
| Phân quyền | `/permissions` | Duyệt yêu cầu truy cập, gán quyền |
| Báo cáo | `/reports` | Báo cáo sử dụng, chất lượng, tuân thủ |
| Cài đặt | `/settings` | Cấu hình policy (admin only) |

### 4.2 Components

| File | Mô tả |
|------|-------|
| `app-shell.tsx` | Layout chính — sidebar navigation, role-based menu |
| `auth-provider.tsx` | Context đăng nhập, lưu token, tự redirect |
| `login-screen.tsx` | Form đăng nhập (mã + mật khẩu) |
| `ui.tsx` | Shared components: Button, Modal, Table, Alert, Badge, Icon |

### 4.3 Thư viện

| File | Mô tả |
|------|-------|
| `lib/api.ts` | Fetch wrapper với Bearer token; type definitions: User, Document, DocumentDetail, DashboardData, Backup, Audit... |
| `lib/hooks.ts` | Custom React hooks |
| `lib/data.ts` | Data fetching helpers |

**Stack**: Next.js 15, React 19, TypeScript, Tailwind CSS 4.0, Axios-style fetch.

---

## 5. Authentication & Authorization

### Xác thực

1. `POST /api/auth/login` nhận `{code, password}`
2. Backend hash password bằng SHA256, so sánh với `password_hash`
3. Nếu khớp → `secrets.token_urlsafe()` → lưu vào bảng `sessions`
4. Trả token về client → lưu trong localStorage
5. Mọi request sau gửi `Authorization: Bearer {token}`

> **Lưu ý production**: SHA256 không salted — cần thay bằng bcrypt/argon2.

### Phân quyền (RBAC — 4 vai trò)

| Vai trò | Quyền |
|---------|-------|
| `lecturer` | Upload tài liệu, xem public + tài liệu của mình, chatbot, xin quyền truy cập |
| `new_lecturer` | Tất cả của lecturer + onboarding (tổng hợp học phần, quy trình) |
| `head` | Tất cả của lecturer + xem tất cả public trong bộ môn, giám sát chất lượng, quản lý chuyển giao, phân quyền |
| `admin` | Tất cả + quản lý user, cấu hình policy, backup/restore, kho lưu trữ ngoài |

### Kiểm soát tài liệu

| Trường hợp | Quyền xem |
|------------|-----------|
| Tài liệu `public` | Tất cả user |
| Tài liệu `private` | Chỉ chủ sở hữu |
| Tài liệu `private` + đã approved | Người được duyệt |
| Chatbot (RAG) | Chỉ public + tài liệu của chính mình (STRICT) |

Tên chủ sở hữu tài liệu Private hiển thị là "Ẩn danh" với người khác.

---

## 6. AI & RAG Pipeline

### Pipeline Upload (Auto-classify & Store)

```
User upload file
    │
    ▼
extract_text()
  ├── TXT/MD/CSV/JSON → đọc trực tiếp
  ├── PDF có text → PyPDF
  ├── PDF scan → render ảnh → OpenAI Vision OCR
  └── DOCX → XML extraction
    │
    ▼
guess_metadata()
  ├── [OpenAI] gpt-5.4-mini → JSON: title, topic, doc_type, summary, keywords
  └── [Local] keyword matching rules
    │
    ▼
suggest_folder()
  └── Policy template: {department}/{topic}/{doc_type}/{visibility}
    │
    ▼ (user xác nhận folder)
    │
create_document()
  └── Lưu version 1 vào: data/mvp/storage/{doc_id}/v1.txt
    │
    ▼
save_file_asset()
  └── File gốc: data/mvp/storage/repository/{folder_path}/{doc_id}/v{n}_{filename}
    │
    ▼
index_document()
  ├── Chunk nội dung thành đoạn nhỏ
  ├── embed() từng chunk → vector
  └── Lưu vào bảng chunks
    │
    ▼
sync_document()
  └── Upload lên Google Drive / OneDrive (nếu đã kết nối)
```

### Pipeline Hỏi đáp (RAG Q&A)

```
User đặt câu hỏi
    │
    ▼
rag_documents(user)
  └── Filter STRICT: public + owned only
    │
    ▼
embed(question) → vector câu hỏi
    │
    ▼
Cosine similarity search trên bảng chunks
  └── Lấy top-K chunks phù hợp nhất
    │
    ▼
Kiểm tra quyền từng document nguồn
    │
    ▼
answer(question, context_chunks)
  ├── [OpenAI] gpt-5.4-mini → trả lời tiếng Việt + citations
  └── [Local] template summary
    │
    ▼
Trả về: {answer, citations: [{title, topic, location}]}
```

### Embedding

| Mode | Model | Số chiều | Cách tính |
|------|-------|----------|-----------|
| OpenAI | text-embedding-3-small | 1536 | API call |
| Local fallback | Hash-based | 128 | SHA256 từng từ → index = hash % 128 → L2 normalize |

---

## 7. Storage & Backup

### Cấu trúc lưu trữ file

```
data/mvp/
├── eduvault.db                          # SQLite database
├── storage/
│   ├── {doc_id}/
│   │   ├── v1.txt                       # Nội dung text version 1
│   │   ├── v2.txt                       # Nội dung text version 2
│   │   └── ...
│   └── repository/
│       └── {department}/{topic}/{type}/{visibility}/
│           └── {doc_id}/
│               ├── v1_{filename}.pdf    # File gốc version 1
│               └── v2_{filename}.pdf    # File gốc version 2
└── backups/
    └── backup_{timestamp}/
        ├── eduvault.db                  # Snapshot database
        └── storage/                     # Snapshot storage
```

### Chính sách Backup 3-2-1

| Quy tắc | Thực hiện |
|---------|-----------|
| 3 bản sao | Local + Google Drive + OneDrive |
| 2 loại lưu trữ | Filesystem + Cloud object storage |
| 1 bản ngoài hệ thống | Google Drive hoặc OneDrive |

`compliance_report()` kiểm tra và báo cáo trạng thái từng quy tắc.

---

## 8. Reporting & Monitoring

### Báo cáo sử dụng (`/api/reports/usage`)
- Số tài liệu tạo mới theo khoảng thời gian
- Số lượt truy vấn chatbot
- Số lượt truy cập tài liệu
- Top topics được truy cập nhiều nhất

### Báo cáo chất lượng (`/api/reports/quality`)
- **Tài liệu lỗi thời**: chưa cập nhật trong N ngày (theo policy retention)
- **Tài liệu trùng lặp**: phát hiện qua content_hash
- **Học phần thiếu tài liệu**: so sánh với `required_doc_types` trong bảng courses

### Báo cáo tuân thủ (`/api/reports/compliance`)
- Đếm bản sao theo từng storage provider
- Xác nhận có ≥1 bản offsite
- Cảnh báo nếu vi phạm 3-2-1

### Audit Log
Mọi hành động đều được ghi lại: actor, action type, resource, timestamp, detail JSON.

---

## 9. Tính năng đã triển khai (checklist)

### Core Features
- [x] Đăng nhập bằng mã + mật khẩu, token session
- [x] 4 vai trò phân quyền (RBAC)
- [x] Upload file nhiều định dạng (TXT, MD, CSV, JSON, PDF, DOCX)
- [x] AI tự trích xuất metadata khi upload
- [x] Đề xuất folder lưu trữ theo policy
- [x] Chatbot RAG hỏi đáp tiếng Việt có trích dẫn
- [x] Tài liệu Public/Private + yêu cầu truy cập
- [x] Lịch sử phiên bản + rollback
- [x] Xóa mềm + khôi phục từ thùng rác
- [x] Phát hiện trùng lặp (content hash)

### Storage & Backup
- [x] Lưu file gốc theo cây thư mục policy
- [x] Snapshot backup (database + storage)
- [x] Restore từ backup
- [x] Google Drive OAuth + sync
- [x] OneDrive OAuth + sync
- [x] Báo cáo tuân thủ 3-2-1

### Knowledge Transfer
- [x] AI tổng hợp tri thức học phần cho giảng viên mới
- [x] AI tổng hợp quy trình công tác
- [x] Tạo và theo dõi phiên chuyển giao học phần

### Admin
- [x] Quản lý user (tạo, cập nhật)
- [x] Cấu hình policy (naming template, retention, backup schedule, AI prompts)
- [x] Cấu hình kho lưu trữ ngoài
- [x] Audit log đầy đủ

### Reporting
- [x] Báo cáo sử dụng theo thời gian
- [x] Phát hiện tài liệu lỗi thời / trùng lặp / học phần thiếu tài liệu
- [x] Dashboard thống kê tổng quan

---

## 10. Chưa triển khai / hạn chế MVP

| Hạng mục | Ghi chú |
|----------|---------|
| OCR thực (PaddleOCR) | Hiện dùng OpenAI Vision, PaddleOCR trong tài liệu nhưng chưa code |
| Password hashing an toàn | Dùng SHA256 không salt; cần bcrypt/argon2 cho production |
| SharePoint integration | Cấu trúc hỗ trợ nhưng OAuth chưa implement |
| Email/push notification | Không có alert khi access request được duyệt, backup thất bại... |
| Rate limiting | Chưa có giới hạn request trên API |
| Multi-tenant isolation | Schema MySQL hỗ trợ nhưng application chưa enforce |
| Full-text search truyền thống | Chỉ có semantic search (embedding), không có BM25/FTS |
| Audit log retention policy | Chưa có tự động dọn log cũ |
| HTTPS | Chạy HTTP; cần reverse proxy (Nginx) cho production |

---

## 11. Cấu hình môi trường (.env)

```env
# Database
DATABASE_PROVIDER=sqlite          # sqlite hoặc mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=eduvault
MYSQL_USER=eduvault
MYSQL_PASSWORD=change-me

# AI
OPENAI_API_KEY=                   # Để trống → dùng local fallback
OPENAI_MODEL=gpt-5.4-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_BASE_URL=https://api.openai.com/v1

# Cloud Storage
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8080/api/cloud/callback/google_drive

MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
MICROSOFT_REDIRECT_URI=http://localhost:8080/api/cloud/callback/onedrive

TOKEN_ENCRYPTION_KEY=eduvault-demo-key-change-before-production

# System
MAX_UPLOAD_MB=25
```

---

## 12. Tài khoản mặc định

| Mã (= mật khẩu) | Vai trò |
|-----------------|---------|
| `GV001` | Giảng viên |
| `GVNEW` | Giảng viên mới |
| `TBM01` | Trưởng bộ môn |
| `ADMIN` | Quản trị viên |

---

## 13. Production Schema (MySQL)

File `database/mysql_8_4_production_schema.sql` có schema nâng cấp bao gồm:
- UUID binary(16) cho public ID
- Cây phân cấp khoa/bộ môn với path_cache
- Quản lý nhân viên + tích hợp SSO (identity provider)
- RBAC phân quyền chi tiết theo chức năng
- Soft delete với tracking người xóa
- Indexing đầy đủ cho performance
- Hỗ trợ multi-tenant theo department

Công cụ migrate: `python scripts/migrate_sqlite_to_mysql.py --source data/mvp/eduvault.db --replace`

---

## 14. Thống kê code

| Thành phần | Số lượng |
|------------|----------|
| Backend Python files | 6 (main, database, ai, services, cloud, __init__) |
| Frontend TypeScript/React files | ~15 (pages + components + lib) |
| Database tables (SQLite MVP) | 16 |
| API endpoints | ~40+ |
| Frontend pages | 10 trang chính |
| Test files | 2 |
| Documentation files | 8 (README, AI_ARCHITECTURE, RAG_PIPELINE, MYSQL_SETUP, USE_CASE_COVERAGE, MINIMUM_REQUIREMENTS_AUDIT, JOURNAL, WORKLOG) |

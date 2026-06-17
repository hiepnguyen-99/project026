# EduVault — Tiến độ xây dựng

> Cập nhật mỗi khi hoàn thành 1 Prompt. Team đọc file này để biết dự án đang ở đâu.

---

## Trạng thái tổng quan

| Prompt | Tên | Người làm | Trạng thái | Ngày |
|--------|-----|-----------|-----------|------|
| Setup  | Khởi tạo repo, hooks, môi trường | Hiếu | ✅ Done | 2026-06-08 |
| P0     | Khung backend chạy được | Hiếu | ✅ Done | 2026-06-08 |
| P1     | Auth + RBAC (JWT, login, phân quyền) | Hiếu | ✅ Done | 2026-06-08 |
| P2     | Upload + Storage + Dedup + Celery | Hiếu | ✅ Done | 2026-06-08 |
| P3     | Pipeline nạp tài liệu (parse→chunk→embed) | Hiệp | ✅ Done | 2026-06-08 |
| P4     | Truy xuất + gác quyền + sinh câu trả lời | Hiệp | ✅ Done | 2026-06-08 |
| P5     | Agent LangGraph (tool-use) | Hiệp | ✅ Done | 2026-06-08 |
| P6     | Governance: HITL, xin quyền, versioning | Hiếu+Hiệp | ✅ Done | 2026-06-08 |
| FE-1   | Frontend: Auth + Chat | Huy | ⏳ Chưa làm | — |
| FE-2   | Frontend: Upload + AI metadata | Huy | ⏳ Chưa làm | — |

---

## Chi tiết từng Prompt đã hoàn thành

---

### ✅ Setup — Khởi tạo môi trường (2026-06-08)

**Mục tiêu:** Repo sẵn sàng để cả team bắt đầu code.

**Đã làm:**
- Cài pre-push hook tự động log AI usage (`scripts/setup_hooks.ps1`)
- Tạo `.env` từ `.env.example`, điền API keys (OpenAI, LangSmith, AI Log)
- Tạo virtual environment Python 3.11 + cài toàn bộ dependencies
- Cài Claude Code CLI v2.1.168, login tài khoản
- Cập nhật `README.md` với tên dự án EduVault + link Gate 1 (Brief/PRD/Wireframe)
- Tạo `.claude/CLAUDE.md` — context dự án tự động load khi dùng Claude Code
- Ghi `WORKLOG.md` ngày đầu

**Để chạy được:**
```powershell
# Windows
.\.venv\Scripts\activate
```

---

### ✅ P0 — Khung backend chạy được (2026-06-08)

**Mục tiêu:** `make up` chạy được, `curl localhost:8000/health` trả `{"status":"ok"}`, pgvector bật.

**Files đã tạo/sửa:**

| File | Làm gì |
|------|--------|
| `docker-compose.yml` | 5 services: postgres/pgvector·16, redis·7, minio, backend, worker |
| `Dockerfile` | Cập nhật CMD trỏ sang `src.backend.app.main:app` |
| `requirements.txt` | Thêm SQLAlchemy async, Alembic, asyncpg, Celery, MinIO, JWT, pypdf, python-docx |
| `Makefile` | `make up/down/migrate/revision/logs/test` |
| `.env.example` | Thêm biến `POSTGRES_*`, `REDIS_URL`, `MINIO_*`, `JWT_SECRET` |
| `src/backend/app/core/config.py` | Pydantic Settings — đọc toàn bộ biến `.env` |
| `src/backend/app/db/base.py` | `DeclarativeBase` cho SQLAlchemy ORM |
| `src/backend/app/db/session.py` | Async engine + `AsyncSessionLocal` + `get_db()` |
| `src/backend/app/main.py` | FastAPI app + CORS + `GET /health` kiểm tra DB live |
| `src/backend/alembic.ini` | Config Alembic |
| `src/backend/alembic/env.py` | Migration chạy async (asyncpg) |
| `src/backend/alembic/versions/0001_enable_pgvector.py` | `CREATE EXTENSION IF NOT EXISTS vector` |

**Cách test:**
```bash
# Cập nhật .env với biến mới từ .env.example trước
make up        # khởi động toàn bộ stack (Docker cần chạy)
make migrate   # bật pgvector extension
curl http://localhost:8000/health  # → {"status":"ok"}
# MinIO console: http://localhost:9001 (minioadmin/minioadmin)
```

**Kiến trúc hiện tại:** Chỉ có khung, chưa có nghiệp vụ. DB connect được, pgvector sẵn sàng.

---

### ✅ P1 — Auth + RBAC (2026-06-08)

**Mục tiêu:** Login bằng mã giảng viên trả JWT hợp lệ; endpoint bảo vệ chặn token sai role; test pass.
KHÔNG có đăng ký công khai — tài khoản do admin cấp.

**Files đã tạo/sửa:**

| File | Làm gì |
|------|--------|
| `src/backend/app/models/user.py` | Model `User` (id UUID, code unique, full_name, hashed_password, role enum, is_active) + enum `UserRole` (giang_vien/truong_bo_mon/quan_tri) |
| `src/backend/app/core/security.py` | `hash_password`/`verify_password` (bcrypt), `create_access_token`/`decode_access_token` (JWT sub=code, role) |
| `src/backend/app/core/deps.py` | `get_current_user()` (đọc JWT từ header) + `require_roles(*roles)` (gác RBAC) |
| `src/backend/app/schemas/auth.py` | Pydantic `LoginRequest`, `UserOut`, `TokenResponse` |
| `src/backend/app/api/v1/auth.py` | `POST /api/v1/auth/login`, `GET /me`, `GET /admin-only` (demo RBAC) |
| `src/backend/app/main.py` | Gắn `auth.router` vào app |
| `src/backend/alembic/versions/0002_create_users.py` | Migration tạo bảng `users` + enum `user_role` |
| `scripts/seed_users.py` | Tạo 3 user mẫu cho 3 vai trò |
| `tests/conftest.py` | Test harness SQLite in-memory + override `get_db` + seed user |
| `tests/test_auth.py` | 7 test: login đúng/sai, /me cần token, RBAC chặn/cho phép |
| `pytest.ini` | Cấu hình `asyncio_mode=auto` |

**Lưu ý dọn dẹp:**
- Đã xóa `tests/test_agents/` và `tests/test_api/` (test cũ của template, test endpoint `/api/v1/chat` không còn trong kiến trúc EduVault).
- Đổi từ `passlib[bcrypt]` sang dùng `bcrypt` trực tiếp (passlib 1.7.4 không tương thích bcrypt 4.x).

**Kết quả test:**
```
7 passed in 4.66s   (ruff: All checks passed!)
```

**Cách test thủ công (cần DB chạy):**
```bash
make up && make migrate
python scripts/seed_users.py        # tạo GV001/TBM001/QT001
# login: POST /api/v1/auth/login  {"code":"QT001","password":"quantri123"}
```

3 tài khoản seed mẫu:

| Mã | Mật khẩu | Vai trò |
|----|----------|---------|
| GV001 | giangvien123 | giang_vien |
| TBM001 | truongbomon123 | truong_bo_mon |
| QT001 | quantri123 | quan_tri |

---

### ✅ P2 — Upload + Storage + Dedup + khung Celery (2026-06-08)

**Mục tiêu:** Upload tài liệu → lưu MinIO + tính SHA-256 + tạo Document (status=pending) +
đẩy task ingest vào hàng đợi. Upload trùng nội dung → chặn (duplicate).

**Files đã tạo/sửa:**

| File | Làm gì |
|------|--------|
| `models/document.py` | Model `Document` (owner_code, title, visibility, content_hash, status, current_version...) + `Version` + enum `Visibility`, `DocStatus` |
| `services/storage.py` | `Storage` interface + `MinioStorage` (put_object → uri, get_presigned_url) + dependency `get_storage` |
| `services/dedup.py` | `compute_hash` (SHA-256) + `find_duplicate` (query theo content_hash) |
| `workers/celery_app.py` | Celery + Redis broker; task `ingest_document` (khung rỗng, P3 hoàn thiện) |
| `schemas/document.py` | `UploadResponse` |
| `api/v1/documents.py` | `POST /api/v1/documents` (multipart, cần login) → lưu + hash + tạo Document + enqueue |
| `main.py` | Gắn `documents.router` |
| `alembic/versions/0003_create_documents.py` | Migration tạo bảng `documents` + `versions` + 2 enum |
| `tests/conftest.py` | Thêm `FakeStorage` (RAM) + Celery eager + đăng ký bảng document |
| `tests/test_upload.py` | 3 test: upload thành công, upload trùng → duplicate, thiếu auth bị chặn |

**Cơ chế chống trùng (dedup):**
- Đọc bytes file → `hashlib.sha256` → hex 64 ký tự.
- Đã có Document cùng `content_hash` → trả `status=duplicate` (HTTP 200), KHÔNG lưu lại.
- File mới → lưu MinIO, tạo Document `pending` + Version đầu, enqueue `ingest_document`.

**Lưu ý kỹ thuật:**
- `storage.py` thiết kế dạng interface để test thay bằng `FakeStorage` (không cần MinIO thật).
- Enqueue Celery bọc `try/except` — API không chết nếu Redis chưa chạy.

**Kết quả test:**
```
10 passed in 6.01s   (7 auth + 3 upload, ruff sạch)
```

---

### ✅ P3 — Pipeline nạp tài liệu (2026-06-08)

**Mục tiêu:** Hoàn thiện task `ingest_document`: tải file từ MinIO → parse text → chunk →
embed → ghi bảng `chunks` (pgvector) → đặt Document `status=ready`.

**Files đã tạo/sửa:**

| File | Làm gì |
|------|--------|
| `db/types.py` | `VectorType` — Vector trên Postgres, TEXT/JSON trên SQLite (để test offline) |
| `models/chunk.py` | `Chunk` (document_id, content, page_ref, embedding `Vector(1536)`) |
| `rag/embeddings.py` | `embed_texts()` qua OpenAI (`text-embedding-3-small`) |
| `workers/ingest.py` | `parse_document` (PDF/DOCX/TXT) + `chunk_text` + `_run_ingest` async |
| `workers/celery_app.py` | Task `ingest_document` gọi `run_ingest` |
| `services/storage.py` | Thêm `get_object` (tải file từ MinIO) |
| `alembic/versions/0004_create_chunks.py` | Bảng `chunks` + **HNSW index** (vector_cosine_ops) |
| `scripts/reindex.py` | Chạy lại ingest cho 1 document_id |
| `tests/test_ingest.py` | 5 test logic chunk/parse |

**Quyết định kỹ thuật quan trọng:**
- Đổi embedding sang **`text-embedding-3-small` (1536 chiều)** vì pgvector HNSW chỉ hỗ trợ **≤2000 chiều** (text-embedding-3-large = 3072 sẽ lỗi tạo index).
- `VectorType` tự suy biến để test cũ (SQLite) không vỡ khi có cột vector.
- Ingest chạy `asyncio.run` trong Celery task (sync) → tái dùng async session.

**Chưa test thật:** pipeline ingest đầy đủ (MinIO + OpenAI embed + pgvector) cần hạ tầng thật — test sau. Test hiện tại chỉ kiểm logic chunk/parse.

**Kết quả test:**
```
15 passed in 9.58s   (ruff sạch — code mới)
```

---

### ✅ P4 — Truy xuất + gác quyền + sinh câu trả lời (2026-06-08)

**Mục tiêu:** Hỏi 1 câu tiếng Việt → truy xuất chunk liên quan (đã gác quyền) → LLM tổng hợp
→ trả `answer` + `citations` + danh sách tài liệu Private liên quan (`restricted`).

> **NGUYÊN TẮC 1 (cốt lõi):** quyền enforce bằng **SQL WHERE**, KHÔNG nhờ LLM lọc quyền.

**Files đã tạo/sửa:**

| File | Làm gì |
|------|--------|
| `rag/retriever.py` | `retrieve()` vector search + `WHERE visibility=public OR owner_code=user` · `find_restricted()` trả metadata Private của người khác (không nội dung) |
| `rag/prompts.py` | System prompt tiếng Việt (chỉ trả lời theo ngữ cảnh, đánh số nguồn, không bịa) |
| `rag/llm.py` | `generate_answer()` gọi OpenAI chat |
| `schemas/search.py` | `SearchRequest`, `Citation`, `RestrictedItem`, `SearchResponse` |
| `api/v1/search.py` | `POST /api/v1/search` → answer + citations + restricted |
| `tests/conftest.py` | Tách `engine`/`session_factory` fixture để test seed tài liệu |
| `tests/test_search.py` | Public người khác → vào answer; Private người khác → KHÔNG, chỉ trong restricted |

**Cơ chế gác quyền (quan trọng nhất của dự án):**
- `retrieve` join `chunks` ↔ `documents`, lọc quyền ngay trong câu SQL → LLM **không bao giờ** thấy nội dung Private của người khác.
- `find_restricted` chỉ trả tên/owner tài liệu Private (để FE hiện nút "xin quyền"), tuyệt đối không trả nội dung.

**Chưa test thật:** ranking vector thật + câu trả lời LLM thật cần hạ tầng — test sau. Test hiện tại mock embed/LLM, tập trung verify **logic phân quyền** (phần dễ sai & nguy hiểm nhất).

**Kết quả test:**
```
17 passed in 10.46s   (ruff sạch)
```

---

### ✅ P5 — Agent LangGraph (tool-use) (2026-06-08)

**Mục tiêu:** Biến RAG thành **agentic** — agent tự chọn tool (LangGraph), không phải
pipeline tuyến tính cứng. Ràng buộc quyền vẫn ở tầng tool/SQL.

**Files đã tạo/sửa:**

| File | Làm gì |
|------|--------|
| `rag/tools.py` | `build_tools(db, user)` → `search_documents`, `list_documents`, `summarize_document`, `request_access`. MỖI tool tự lọc quyền bằng SQL |
| `rag/agent.py` | `StateGraph`: node `agent` (LLM bind tools) ↔ `ToolNode`, conditional edge `tools_condition` lặp tới khi có câu trả lời; `run_agent()` trả (answer, citations) |
| `api/v1/search.py` | Route `/search` đi qua `run_agent` thay vì gọi retriever trực tiếp |
| `tests/conftest.py` | `seed_docs` + `patch_embeddings` + `requester` thành fixture dùng chung |
| `tests/test_agent.py` | 3 test: tool search/summarize/list đều gác quyền, không lộ Private |
| `tests/test_search.py` | Test `retrieve` trực tiếp + route (mock agent) |

**Điểm quan trọng:**
- Agent dùng LangGraph thật (StateGraph + ToolNode), tool-calling của OpenAI.
- **Quyền không nằm ở agent/LLM** — mỗi tool tự lọc bằng SQL → kể cả khi LLM "muốn", nó cũng không lấy được nội dung Private của người khác.

**Chưa test thật:** vòng lặp agent với LLM thật cần OpenAI — test sau. Test hiện tại verify **từng tool** (nơi gác quyền), mock LLM ở route.

**Kết quả test:**
```
21 passed in 7.69s   (ruff sạch)
```

---

### ✅ P6 — Governance: HITL, xin quyền, versioning (2026-06-08)

**Mục tiêu:** Hoàn thiện quản trị — xin quyền truy cập (duyệt thủ công), xác nhận metadata,
versioning/rollback, và phân quyền bởi admin.

**Files đã tạo/sửa:**

| File | Làm gì |
|------|--------|
| `models/access_request.py` | `AccessRequest` + enum `AccessStatus` (pending/approved/denied) |
| `core/permissions.py` | `can_access_document` (public / chủ / admin / đã được duyệt) |
| `api/v1/access_requests.py` | POST tạo yêu cầu · GET chủ xem · PATCH duyệt/từ chối |
| `api/v1/admin.py` | `PUT /admin/permissions` — chỉ quản trị đổi vai trò |
| `api/v1/documents.py` | `GET /{id}/download` (gác quyền) · `POST /confirm` (→ready) · `POST /rollback` · versioning qua `replace_document_id` |
| `rag/retriever.py` | Thêm tài liệu đã-được-duyệt vào quyền; loại khỏi `restricted` |
| `alembic/versions/0005_create_access_requests.py` | Bảng `access_requests` + enum |
| `tests/test_access.py` | 4 test: xin quyền→duyệt→tải được; chưa duyệt→403; admin RBAC; confirm→ready |

**Luồng Human-in-the-loop:**
```
GV001 xin quyền (pending) → TBM001 (chủ) duyệt (approved) → GV001 tải được file
                                     ↘ chưa duyệt → 403
```

**Chưa test thật:** download presigned URL thật từ MinIO cần hạ tầng — test dùng FakeStorage. Logic phân quyền + duyệt đã verify đầy đủ.

**Kết quả test:**
```
25 passed in 14.67s   (ruff sạch)
```

---

## Hướng dẫn cho team

### Quy trình làm việc
1. Kéo branch mới từ `main`: `git checkout -b feat/p1-auth`
2. Làm theo Prompt trong `EduVault_Build_Guide.md`
3. Chạy `make test` trước khi commit
4. Cập nhật file này (PROGRESS.md) + WORKLOG.md
5. Tạo PR vào `main`

### Đọc thêm
- **Build Guide đầy đủ:** `EduVault_Build_Guide.md` (ở thư mục cha)
- **Context cho AI:** `.claude/CLAUDE.md` (tự động load khi dùng `claude`)
- **Kiến trúc:** `ARCHITECTURE.md`
- **Quyết định kỹ thuật:** `WORKLOG.md`

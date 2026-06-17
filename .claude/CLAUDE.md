# Bối cảnh dự án — EduVault (team-012)

Web app AI quản lý kho tri thức của khoa: giảng viên thả file lên, AI đọc/phân loại/
gắn metadata; truy xuất bằng hội thoại tiếng Việt có trích dẫn nguồn; phân quyền
Public/Private; có versioning + backup.

## Stack
- Backend: Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2
- Worker: Celery + Redis (broker)
- DB: PostgreSQL 16 + pgvector (index HNSW)
- Object store: MinIO (S3-compatible)
- Agent: LangGraph (tool-use)
- Frontend: Next.js (App Router) + TypeScript
- Auth: JWT, RBAC

## Layout
- Code backend trong src/backend/app/   |  Migrations trong src/backend/alembic/
- Frontend trong src/frontend/          |  Test trong tests/ (pytest)

## Nguyên tắc BẮT BUỘC
1. Phân quyền enforce Ở TẦNG TRUY VẤN (SQL WHERE), KHÔNG nhờ LLM/prompt kiểm soát quyền.
   AI không tự cấp quyền, không tiết lộ dữ liệu Private của người khác.
2. RAG là agentic (LangGraph tool-use), không phải pipeline tuyến tính cứng.
3. Mọi file có content hash (SHA-256) để chống trùng lặp.
4. Ghi vào kho cần admin duyệt (Human-in-the-loop).
5. KHÔNG có đăng ký công khai — tài khoản do admin cấp theo mã giảng viên; người dùng chỉ login.
6. Code có type hint, docstring ngắn, test đi kèm cho mỗi endpoint.

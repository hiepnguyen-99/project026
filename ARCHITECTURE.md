# EduVault — Kiến trúc hệ thống

Web app AI quản lý kho tri thức của khoa: giảng viên thả file lên, AI đọc/phân loại/gắn metadata;
truy xuất bằng hội thoại tiếng Việt có trích dẫn nguồn; phân quyền Public/Private; versioning + backup.

---

## Sơ đồ tổng quan

```
                 USERS: Giảng viên | Trưởng bộ môn | Quản trị
                                    |
                                    v
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND — Next.js (App Router + TypeScript)               │
│  /login   /home   /chat   /upload                           │
│  · Tự động gắn JWT        · Render answer + citations       │
└─────────────────────────────────────────────────────────────┘
                                    | HTTP + Bearer JWT
                                    v
┌─────────────────────────────────────────────────────────────┐
│  API — FastAPI (api/v1/)                                    │
│  auth  |  documents  |  search  |  access_requests  |  admin│
│                                                             │
│  core/ → security=JWT   deps=RBAC   config                  │
│  *** PHÂN QUYỀN ở tầng API + SQL WHERE — KHÔNG nhờ LLM ***  │
└─────────────────────────────────────────────────────────────┘
        |                   |                      |
        | upload             | hỏi đáp (RAG)        | task nền
        v                   v                      v
┌──────────────┐  ┌───────────────────┐  ┌─────────────────┐
│  SERVICES    │  │  RAG / AGENT      │  │  WORKER         │
│              │  │                   │  │  (Celery+Redis) │
│ storage→MinIO│  │ agent (LangGraph) │  │ ingest.py       │
│ dedup SHA-256│  │ tools             │  │ parse→chunk     │
│              │  │ retriever         │  │ →embed→pgvector │
│              │  │ embeddings        │  │                 │
└──────────────┘  └───────────────────┘  └─────────────────┘
        |                   |                      |
        └───────────────────┴──────────────────────┘
                                    |
                                    v
┌─────────────────────────────────────────────────────────────┐
│  DATA LAYER                                                 │
│  PostgreSQL + pgvector    MinIO (S3)        Redis           │
│  users, documents,        file gốc tài liệu broker Celery   │
│  chunks (HNSW index),                                       │
│  access_requests                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Stack kỹ thuật

| Layer | Technology | Ghi chú |
|-------|-----------|---------|
| Frontend | Next.js 14 + TypeScript | App Router, fetch wrapper JWT |
| Backend | FastAPI + Python 3.11 | Async, Pydantic v2 |
| ORM | SQLAlchemy 2.x + Alembic | Async engine (asyncpg) |
| Database | PostgreSQL 16 + pgvector | Index HNSW cho vector search |
| Object store | MinIO | S3-compatible, lưu file gốc |
| Queue | Celery + Redis | Xử lý ingest nền |
| Auth | JWT + RBAC | 3 roles: giảng viên, trưởng bộ môn, quản trị |
| AI Agent | LangGraph (tool-use) | Agentic RAG, không pipeline cứng |
| Embeddings | text-embedding-3-large | Hỗ trợ tiếng Việt |
| LLM | GPT-4o-mini | Sinh câu trả lời + citations |

---

## Luồng A — Upload tài liệu

```
Upload file → Lưu MinIO → SHA-256 hash → Trùng? → Báo duplicate
                                        ↓ Mới
                                   Celery enqueue
                                        ↓
                                   ingest.py: parse → chunk → embed → pgvector
                                        ↓
                                   Document status = ready
```

## Luồng B — Hỏi đáp (Agentic RAG)

```
Câu hỏi tiếng Việt → LangGraph agent → chọn tool search_documents
                                              ↓
                              retriever: embed query + vector search
                              SQL WHERE visibility='public' OR owner=user  ← PHÂN QUYỀN
                                              ↓
                              top-k chunks (CHỈ được xem)
                                              ↓
                        LLM tổng hợp → answer + citations + restricted list
                                              ↓
                        Frontend: hiển thị + nút "Xin quyền" cho tài liệu Private
```

---

## Cấu trúc thư mục (thực tế)

```
src/backend/app/
├── core/
│   ├── config.py          ✅ P0 — Pydantic Settings
│   ├── security.py        ✅ P1 — JWT + bcrypt
│   └── deps.py            ✅ P1 — RBAC (get_current_user, require_roles)
├── db/
│   ├── base.py            ✅ P0 — DeclarativeBase
│   └── session.py         ✅ P0 — Async engine + get_db()
├── core/permissions.py    ✅ P6 — can_access_document
├── db/types.py            ✅ P3 — VectorType (pgvector / SQLite)
├── models/
│   ├── user.py            ✅ P1 — User + UserRole
│   ├── document.py        ✅ P2 — Document + Version + Visibility/DocStatus
│   ├── chunk.py           ✅ P3 — Chunk + embedding Vector(1536)
│   └── access_request.py  ✅ P6 — AccessRequest + AccessStatus
├── schemas/
│   ├── auth.py            ✅ P1 — Login/Token schemas
│   ├── document.py        ✅ P2+P6 — Upload/Confirm/Download
│   ├── search.py          ✅ P4 — Search schemas
│   ├── access.py          ✅ P6 — AccessRequest schemas
│   └── admin.py           ✅ P6 — PermissionUpdate
├── api/v1/
│   ├── auth.py            ✅ P1 — login/me/admin-only
│   ├── documents.py       ✅ P2+P6 — upload/download/confirm/rollback
│   ├── search.py          ✅ P4+P5 — POST search (qua agent)
│   ├── access_requests.py ✅ P6 — xin quyền (POST/GET/PATCH)
│   └── admin.py           ✅ P6 — PUT permissions (quan_tri)
├── services/
│   ├── storage.py         ✅ P2+P3 — MinIO (put/get/presigned)
│   └── dedup.py           ✅ P2 — SHA-256 chống trùng
├── rag/
│   ├── embeddings.py      ✅ P3 — embed_texts (OpenAI)
│   ├── retriever.py       ✅ P4 — vector search + GÁC QUYỀN SQL + find_restricted
│   ├── prompts.py         ✅ P4 — system prompt tiếng Việt
│   ├── llm.py             ✅ P4 — generate_answer (dùng trực tiếp, fallback)
│   ├── tools.py           ✅ P5 — search/list/summarize/request_access (gác quyền SQL)
│   └── agent.py           ✅ P5 — LangGraph StateGraph (agent ↔ ToolNode) + run_agent
├── workers/
│   ├── celery_app.py      ✅ P2+P3 — Celery + task ingest_document
│   └── ingest.py          ✅ P3 — parse + chunk + embed → pgvector
└── main.py                ✅ P0-P6 — auth + documents + search + access-requests + admin
```

**Legend:** ✅ Đã xong · ⏳ Chưa làm

---

## Nguyên tắc bất biến

1. **Phân quyền ở tầng SQL** — `WHERE visibility='public' OR owner_code=:user` — không nhờ LLM lọc
2. **RAG agentic** — LangGraph tool-use, không pipeline tuyến tính
3. **Chống trùng lặp** — SHA-256 content hash trước khi lưu
4. **Human-in-the-loop** — admin duyệt trước khi tài liệu vào kho
5. **Không đăng ký công khai** — tài khoản do admin cấp theo mã giảng viên

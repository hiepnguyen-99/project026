# Pipeline Chatbot EduVault

## Phạm vi dữ liệu

Chatbot chỉ được sử dụng:

- Tài liệu có trạng thái `public`.
- Tài liệu do chính người đang hỏi sở hữu.

Chatbot không sử dụng tài liệu Private của người khác, kể cả khi:

- Người hỏi đã được phê duyệt quyền xem.
- Người hỏi có vai trò Trưởng bộ môn.
- Người hỏi có vai trò Quản trị viên.

## Pipeline

```text
Upload file
  ↓
Parse nội dung
  ├─ TXT / MD / CSV / JSON
  ├─ PDF có text
  ├─ PDF scan → render ảnh → OpenAI vision OCR
  └─ DOCX
  ↓
Chunk nội dung
  ↓
Embedding
  ├─ OpenAI text-embedding-3-small
  └─ Local hash vector fallback
  ↓
Vector store: bảng SQLite chunks
  ↓
Permission filter: Public + tài liệu chính mình
  ↓
Semantic retrieval
  ↓
OpenAI Responses API / local fallback
  ↓
Câu trả lời + citation tài liệu và phiên bản
```

## Bảo mật chủ sở hữu

- Chủ sở hữu tài liệu Private được trả về dưới tên `Ẩn danh` với người dùng khác.
- Owner được che tại dashboard, kho tài liệu, danh sách quyền, lịch sử phiên bản và yêu cầu truy cập.
- Mã chủ sở hữu thật vẫn được giữ nội bộ để hệ thống gửi và xử lý yêu cầu truy cập.

## Theo dõi trạng thái

API:

```text
GET /api/rag/pipeline
```

API trả số tài liệu/chunk được phép dùng và trạng thái từng bước pipeline.


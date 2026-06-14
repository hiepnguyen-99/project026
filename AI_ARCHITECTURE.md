# Kiến trúc hệ thống EduVault hiện tại

Tài liệu này mô tả kiến trúc đang được triển khai trong mã nguồn hiện tại của
EduVault. Các thành phần nét liền là thành phần đã có; các thành phần trong phần
"Hướng nâng cấp production" chưa được triển khai đầy đủ.

## 1. Sơ đồ kiến trúc tổng thể

```mermaid
flowchart LR
    User["Người dùng<br/>Giảng viên / Trưởng bộ môn / Admin"]

    subgraph Frontend["Frontend - Next.js 15 :3000"]
        UI["Giao diện React<br/>Dashboard, Repository, AI Assistant,<br/>Backup, Permission, Report"]
        AuthClient["Auth Provider<br/>Lưu session token"]
        Proxy["Next.js API Rewrite Proxy<br/>/api/* → BACKEND_URL<br/>timeout 5 phút"]
        UI --> AuthClient --> Proxy
    end

    subgraph Backend["Backend - FastAPI :8080"]
        API["REST API<br/>Auth, Document, Search,<br/>Backup, Admin, Cloud"]
        RBAC["Xác thực token + RBAC<br/>Public / Private / Owner"]
        Services["Document & Knowledge Services<br/>version, folder policy, audit"]
        AIService["AI Provider Adapter<br/>OpenAI hoặc local fallback"]
        CloudService["Cloud Adapter<br/>OAuth + đồng bộ"]
        API --> RBAC --> Services
        Services --> AIService
        Services --> CloudService
    end

    subgraph Data["Data Layer"]
        DB[("MySQL hiện tại<br/>hoặc SQLite fallback<br/>metadata + vector chunks")]
        FileStorage[("Local File Storage<br/>file gốc + phiên bản")]
        BackupStorage[("Local Backup Storage<br/>snapshot hệ thống")]
    end

    subgraph External["Dịch vụ bên ngoài"]
        OpenAI["OpenAI API<br/>Responses + Embeddings"]
        Google["Google Drive API"]
        OneDrive["Microsoft Graph / OneDrive"]
    end

    User -->|HTTP| UI
    Proxy -->|REST / JSON / binary| API
    Services --> DB
    Services --> FileStorage
    Services --> BackupStorage
    AIService -->|khi có API key| OpenAI
    CloudService --> Google
    CloudService --> OneDrive
```

## 2. Kiến trúc backend theo thành phần

```mermaid
flowchart TB
    Main["src/eduvault/main.py<br/>FastAPI routes + middleware"]

    Main --> Auth["Authentication & Authorization<br/>session token, role, owner, visibility"]
    Main --> Service["src/eduvault/services.py"]
    Main --> Cloud["src/eduvault/cloud.py"]
    Main --> Database["src/eduvault/database.py"]

    subgraph CoreServices["Document & Knowledge Services"]
        Parse["Trích xuất nội dung<br/>TXT, DOCX, PDF, OCR fallback"]
        Metadata["AI metadata<br/>title, topic, doc_type, summary, keywords"]
        Policy["Storage policy<br/>sinh folder_path"]
        Version["Quản lý phiên bản<br/>rollback, trash, restore"]
        Index["RAG indexing<br/>chunk + embedding"]
        Retrieve["RAG retrieval<br/>permission filter + citation"]
        Audit["Audit log"]
    end

    Service --> Parse
    Service --> Metadata
    Service --> Policy
    Service --> Version
    Service --> Index
    Service --> Retrieve
    Service --> Audit

    Metadata --> AI["src/eduvault/ai.py<br/>AI Provider"]
    Index --> AI
    Retrieve --> AI
    AI --> OpenAI["OpenAI khi được cấu hình"]
    AI --> Local["Local deterministic fallback"]

    Database --> SQL[("MySQL / SQLite")]
    Service --> Files[("data/mvp/storage")]
    Service --> Backups[("data/mvp/backups")]
    Cloud --> Providers["Google Drive / OneDrive"]
```

## 3. Luồng upload và phân tích tài liệu

Hệ thống hiện chia giới hạn file thành hai tầng:

- AI phân tích trực tiếp: tối đa `MAX_AI_ANALYZE_MB`, mặc định `25 MB`.
- Lưu file gốc: tối đa `MAX_UPLOAD_MB`, hiện cấu hình `250 MB`.
- File vượt giới hạn AI vẫn có thể được lưu nếu người dùng nhập metadata thủ công.

```mermaid
sequenceDiagram
    actor User as Người dùng
    participant FE as Next.js Frontend
    participant API as FastAPI
    participant Parser as Text/PDF/DOCX Parser
    participant AI as OpenAI hoặc Local Fallback
    participant DB as MySQL/SQLite
    participant FS as Local File Storage
    participant Cloud as Cloud Storage

    User->>FE: Chọn file
    FE->>FE: Kiểm tra kích thước file

    alt File <= 25 MB và chọn AI phân tích
        FE->>API: POST /api/documents/analyze-file
        API->>API: Kiểm tra Content-Length
        API->>Parser: Trích xuất text
        Parser-->>API: Nội dung tài liệu
        API->>AI: Đề xuất metadata từ nội dung mẫu
        AI-->>API: Metadata hoặc local fallback
        API->>DB: Kiểm tra trùng lặp + đọc storage policy
        API-->>FE: Metadata + folder_path đề xuất
    else File > 25 MB
        FE-->>User: Yêu cầu nhập metadata thủ công
    end

    User->>FE: Xác nhận metadata và thư mục
    FE->>API: POST /api/documents/upload
    API->>API: Kiểm tra giới hạn upload
    API->>Parser: Trích xuất nội dung
    API->>DB: Lưu document, version, asset, audit
    API->>FS: Lưu file gốc theo folder policy
    API->>AI: Chia chunk + tạo embedding
    API->>DB: Lưu chunks và vector
    API->>Cloud: Đồng bộ nếu đã cấu hình
    API-->>FE: Document đã được tạo
```

## 4. Luồng hỏi đáp RAG

Quyền truy cập được lọc trước khi retrieval. AI không tự cấp quyền và không
được nhận nội dung private ngoài phạm vi người dùng.

```mermaid
sequenceDiagram
    actor User as Người dùng
    participant FE as AI Assistant
    participant API as FastAPI /api/search
    participant Auth as Permission Filter
    participant DB as Chunks + Metadata
    participant AI as OpenAI hoặc Local Fallback

    User->>FE: Đặt câu hỏi
    FE->>API: POST /api/search + Bearer token
    API->>Auth: Xác định người dùng và phạm vi dữ liệu
    Auth->>DB: Chỉ lấy tài liệu public hoặc do người dùng sở hữu
    API->>AI: Tạo embedding câu hỏi
    AI-->>API: Query vector
    API->>DB: Tìm chunks gần nhất trong phạm vi được phép
    DB-->>API: Context + document/version
    API->>AI: Sinh câu trả lời từ context
    AI-->>API: Câu trả lời hoặc local fallback
    API-->>FE: Answer + citations
    FE-->>User: Hiển thị trả lời và nguồn
```

## 5. Mô hình dữ liệu logic

```mermaid
erDiagram
    USERS ||--o{ SESSIONS : creates
    USERS ||--o{ DOCUMENTS : owns
    USERS ||--o{ ACCESS_REQUESTS : requests
    DOCUMENTS ||--o{ VERSIONS : has
    DOCUMENTS ||--o{ FILE_ASSETS : stores
    DOCUMENTS ||--o{ CHUNKS : indexes
    DOCUMENTS ||--o{ ACCESS_REQUESTS : receives
    USERS ||--o{ AUDIT_LOGS : performs
    USERS ||--o{ CLOUD_CONNECTIONS : connects
    COURSES ||--o{ TRANSFERS : has

    USERS {
        string code PK
        string role
        string department
        string password_hash
    }
    DOCUMENTS {
        string id PK
        string owner_code FK
        string title
        string visibility
        int current_version
        string folder_path
    }
    VERSIONS {
        string id PK
        string document_id FK
        int version_no
        string storage_path
        string content_hash
    }
    FILE_ASSETS {
        string id PK
        string document_id FK
        string original_path
        string mime_type
        int size
    }
    CHUNKS {
        string id PK
        string document_id FK
        string content
        string vector
        string provider
    }
    ACCESS_REQUESTS {
        string id PK
        string document_id FK
        string requester_code
        string owner_code
        string status
    }
```

## 6. Sơ đồ triển khai hiện tại

```mermaid
flowchart LR
    Browser["Trình duyệt người dùng"]

    subgraph Host["Máy chạy ứng dụng hiện tại"]
        Next["Next.js Production<br/>127.0.0.1:3000"]
        FastAPI["FastAPI / Uvicorn<br/>127.0.0.1:8080"]
        DB[("MySQL<br/>hoặc SQLite")]
        Storage[("Local filesystem<br/>storage + backups")]
    end

    Browser -->|Mở giao diện| Next
    Next -->|Rewrite /api/*| FastAPI
    FastAPI --> DB
    FastAPI --> Storage
    FastAPI -->|HTTPS| OpenAI["OpenAI API"]
    FastAPI -->|OAuth + HTTPS| Cloud["Google Drive / OneDrive"]
```

Lệnh chạy hiện tại:

```powershell
# Backend
python run_mvp.py

# Frontend
cd frontend
npm run build
npm start
```

## 7. Policy và ranh giới an toàn

- Frontend gửi token qua header `Authorization: Bearer ...`.
- Backend kiểm tra token, vai trò, chủ sở hữu và visibility trước khi xử lý.
- AI không được cấp quyền truy cập và không tự thay đổi quyền tài liệu.
- Tài liệu private của người khác bị loại khỏi phạm vi RAG trước retrieval.
- Chủ sở hữu tài liệu private được ẩn danh với người dùng khác.
- Folder do AI/policy đề xuất phải được người dùng xác nhận.
- Khi OpenAI lỗi hoặc chưa cấu hình, metadata, embedding và RAG dùng local
  fallback để hệ thống vẫn hoạt động.
- File lớn được từ chối sớm trước khi backend đọc toàn bộ request vào RAM.
- OAuth token của cloud provider được mã hóa trước khi lưu.

Policy thư mục mặc định:

```text
{department}/{topic}/{doc_type}/{visibility}
```

Ví dụ:

```text
Công nghệ thông tin/Học máy/Học liệu/public/
```

## 8. Hướng nâng cấp production

Kiến trúc hiện tại phù hợp MVP chạy trên một máy. Để triển khai production và
xử lý tài liệu lớn ổn định, nên nâng cấp theo sơ đồ sau:

```mermaid
flowchart LR
    User["Người dùng"] --> Gateway["Nginx / API Gateway"]
    Gateway --> FE["Next.js Frontend"]
    Gateway --> API["FastAPI API"]
    API --> DB[("MySQL/PostgreSQL HA")]
    API --> Object[("MinIO / S3<br/>multipart upload")]
    API --> Queue["Task Queue<br/>Redis + Celery/RQ"]
    Queue --> Workers["Parser / OCR / AI Workers"]
    Workers --> Object
    Workers --> Vector[("Qdrant / pgvector")]
    Workers --> AI["OpenAI / Local Model"]
    API --> Monitor["Prometheus + Grafana"]
    Workers --> Monitor
```

Các thay đổi quan trọng:

1. Upload file lớn trực tiếp vào MinIO/S3 bằng multipart hoặc presigned URL.
2. Đưa parse, OCR, embedding và indexing vào hàng đợi xử lý nền.
3. Frontend theo dõi trạng thái `uploaded → parsing → indexing → ready/failed`.
4. Tách vector store khỏi bảng SQL khi khối lượng chunks tăng cao.
5. Bổ sung reverse proxy, HTTPS, secrets manager, rate limit và monitoring.
6. Chạy backup/restore định kỳ và kiểm tra tuân thủ 3-2-1 tự động.

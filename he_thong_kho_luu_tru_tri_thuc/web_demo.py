"""EduVault demo v1 server using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "demo_state.json"
UPLOAD_DIR = DATA_DIR / "uploads"
LOCK = threading.Lock()

DEMO_USERS = {
    "GV001": {"name": "Nguyễn Minh Anh", "role": "Giảng viên", "department": "Công nghệ thông tin"},
    "GVNEW": {"name": "Lê Thu Hà", "role": "Giảng viên mới", "department": "Công nghệ thông tin"},
    "TBM01": {"name": "Trần Hoàng Nam", "role": "Trưởng bộ môn", "department": "Công nghệ thông tin"},
    "ADMIN": {"name": "Phạm Quỳnh Chi", "role": "Quản trị viên", "department": "Phòng hệ thống"},
}

SEED_DOCUMENTS = [
    {
        "id": "doc-de-cuong-ai",
        "title": "Đề cương học phần Trí tuệ nhân tạo",
        "doc_type": "Đề cương",
        "topic": "Trí tuệ nhân tạo",
        "author": "Nguyễn Minh Anh",
        "owner_code": "GV001",
        "visibility": "public",
        "created_at": "2026-05-20T08:30:00+00:00",
        "version": 3,
        "size": 286720,
        "status": "Đã lập chỉ mục",
        "content": "Học phần Trí tuệ nhân tạo cung cấp kiến thức về tìm kiếm, biểu diễn tri thức, học máy và hệ chuyên gia. Hình thức đánh giá gồm quá trình 40% và thi cuối kỳ 60%.",
        "citations": "Mục 4. Nội dung và đánh giá học phần",
    },
    {
        "id": "doc-rag-guide",
        "title": "Hướng dẫn xây dựng hệ thống RAG",
        "doc_type": "Học liệu",
        "topic": "Trí tuệ nhân tạo",
        "author": "Trần Hoàng Nam",
        "owner_code": "TBM01",
        "visibility": "public",
        "created_at": "2026-06-01T03:15:00+00:00",
        "version": 2,
        "size": 1183744,
        "status": "Đã lập chỉ mục",
        "content": "RAG kết hợp truy xuất tài liệu và mô hình ngôn ngữ. Pipeline gồm ingest, chunking, embedding, retrieval, kiểm tra quyền, sinh câu trả lời và trích dẫn nguồn.",
        "citations": "Trang 7, sơ đồ RAG pipeline",
    },
    {
        "id": "doc-exam-process",
        "title": "Quy trình xây dựng đề thi cuối kỳ",
        "doc_type": "Quy trình",
        "topic": "Khảo thí",
        "author": "Trần Hoàng Nam",
        "owner_code": "TBM01",
        "visibility": "private",
        "created_at": "2026-04-12T10:00:00+00:00",
        "version": 5,
        "size": 430080,
        "status": "Đã lập chỉ mục",
        "content": "Quy trình xây dựng đề thi gồm lập ma trận, biên soạn câu hỏi, phản biện chéo, phê duyệt và bàn giao bảo mật cho bộ phận khảo thí.",
        "citations": "Mục 2. Các bước thực hiện",
    },
    {
        "id": "doc-handover",
        "title": "Bộ tài liệu bàn giao học phần Lập trình Python",
        "doc_type": "Học liệu",
        "topic": "Lập trình",
        "author": "Nguyễn Minh Anh",
        "owner_code": "GV001",
        "visibility": "public",
        "created_at": "2026-06-06T02:20:00+00:00",
        "version": 1,
        "size": 2097152,
        "status": "Đã lập chỉ mục",
        "content": "Bộ tài liệu gồm đề cương, slide 12 tuần, bài thực hành, rubric đồ án và các lưu ý khi giảng dạy học phần Lập trình Python.",
        "citations": "Danh mục tài liệu bàn giao",
    },
]

TOPIC_RULES = {
    "Trí tuệ nhân tạo": ["ai", "trí tuệ", "machine learning", "rag", "embedding", "llm"],
    "Lập trình": ["python", "lập trình", "code", "phần mềm"],
    "Khảo thí": ["đề thi", "chấm thi", "khảo thí", "đánh giá"],
    "Quy trình nội bộ": ["quy trình", "biên bản", "hướng dẫn", "thủ tục"],
}

TYPE_RULES = {
    "Đề cương": ["đề cương", "syllabus"],
    "Quy trình": ["quy trình", "hướng dẫn", "thủ tục"],
    "Biên bản": ["biên bản", "cuộc họp"],
    "Học liệu": ["bài giảng", "slide", "giáo trình", "học liệu"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_state() -> dict:
    return {
        "documents": SEED_DOCUMENTS,
        "access_requests": [],
        "activity": [
            {"text": "Đồng bộ Google Drive hoàn tất", "time": "10 phút trước", "kind": "backup"},
            {"text": "Hướng dẫn xây dựng hệ thống RAG được cập nhật", "time": "2 giờ trước", "kind": "document"},
            {"text": "Bộ tài liệu Python được bàn giao", "time": "Hôm qua", "kind": "transfer"},
        ],
        "backup": {
            "compliant": True,
            "copies": 3,
            "locations": 2,
            "offsite": 1,
            "last_run": "2026-06-09T01:00:00+00:00",
            "providers": [
                {"name": "MinIO", "status": "Đồng bộ", "type": "Bản chính"},
                {"name": "Google Drive", "status": "Đồng bộ", "type": "Ngoài hệ thống"},
                {"name": "OneDrive", "status": "Đồng bộ", "type": "Ngoài hệ thống"},
            ],
        },
    }


def ensure_state() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        save_state(seed_state())


def load_state() -> dict:
    ensure_state()
    with LOCK:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with LOCK:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def json_bytes(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def guess_metadata(filename: str, content: str) -> dict:
    haystack = normalize(f"{filename} {content}")
    topic = "Khác"
    doc_type = "Tài liệu"
    for candidate, words in TOPIC_RULES.items():
        if any(word in haystack for word in words):
            topic = candidate
            break
    for candidate, words in TYPE_RULES.items():
        if any(word in haystack for word in words):
            doc_type = candidate
            break
    title = Path(filename).stem.replace("_", " ").replace("-", " ").strip().title()
    return {"title": title or "Tài liệu chưa đặt tên", "topic": topic, "doc_type": doc_type}


def visible_documents(state: dict, user_code: str) -> list[dict]:
    user = DEMO_USERS.get(user_code, {})
    elevated = user.get("role") in {"Trưởng bộ môn", "Quản trị viên"}
    return [
        doc
        for doc in state["documents"]
        if doc["visibility"] == "public" or doc["owner_code"] == user_code or elevated
    ]


def public_document(doc: dict) -> dict:
    return {key: value for key, value in doc.items() if key != "content"}


class DemoHandler(SimpleHTTPRequestHandler):
    server_version = "EduVaultDemo/1.0"

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        relative = unquote(parsed.path).lstrip("/") or "index.html"
        return str(WEB_ROOT / relative)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[EduVault] {self.address_string()} - {fmt % args}")

    def send_json(self, data: object, status: int = HTTPStatus.OK) -> None:
        body = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"status": "ok", "version": "v1"})
            return
        if parsed.path == "/api/state":
            user_code = self.headers.get("X-User-Code", "")
            if user_code not in DEMO_USERS:
                self.send_json({"error": "Bạn chưa đăng nhập."}, HTTPStatus.UNAUTHORIZED)
                return
            state = load_state()
            documents = [public_document(doc) for doc in visible_documents(state, user_code)]
            topics = sorted({doc["topic"] for doc in documents})
            self.send_json(
                {
                    "user": {"code": user_code, **DEMO_USERS[user_code]},
                    "documents": documents,
                    "topics": topics,
                    "activity": state["activity"][:8],
                    "backup": state["backup"],
                    "access_requests": state["access_requests"],
                    "stats": {
                        "documents": len(documents),
                        "topics": len(topics),
                        "indexed": sum(doc["status"] == "Đã lập chỉ mục" for doc in documents),
                        "private": sum(doc["visibility"] == "private" for doc in documents),
                    },
                }
            )
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json({"error": "Dữ liệu JSON không hợp lệ."}, HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/login":
            code = str(payload.get("code", "")).upper().strip()
            user = DEMO_USERS.get(code)
            if not user:
                self.send_json({"error": "Mã đăng nhập không hợp lệ."}, HTTPStatus.UNAUTHORIZED)
                return
            self.send_json({"code": code, **user})
            return

        user_code = self.headers.get("X-User-Code", "")
        if user_code not in DEMO_USERS:
            self.send_json({"error": "Phiên đăng nhập không hợp lệ."}, HTTPStatus.UNAUTHORIZED)
            return

        if parsed.path == "/api/documents/analyze":
            filename = str(payload.get("filename", "tai-lieu.txt"))
            content = str(payload.get("content", ""))
            metadata = guess_metadata(filename, content)
            duplicate = None
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            state = load_state()
            for doc in state["documents"]:
                if hashlib.sha256(doc.get("content", "").encode("utf-8")).hexdigest() == digest and content:
                    duplicate = doc["title"]
                    break
            self.send_json({"metadata": metadata, "duplicate": duplicate})
            return

        if parsed.path == "/api/documents":
            required = ["title", "topic", "doc_type", "visibility"]
            if any(not payload.get(field) for field in required):
                self.send_json({"error": "Thiếu metadata bắt buộc."}, HTTPStatus.BAD_REQUEST)
                return
            state = load_state()
            doc_id = f"doc-{uuid.uuid4().hex[:10]}"
            content = str(payload.get("content", ""))
            document = {
                "id": doc_id,
                "title": str(payload["title"]),
                "topic": str(payload["topic"]),
                "doc_type": str(payload["doc_type"]),
                "author": DEMO_USERS[user_code]["name"],
                "owner_code": user_code,
                "visibility": str(payload["visibility"]),
                "created_at": utc_now(),
                "version": 1,
                "size": len(content.encode("utf-8")),
                "status": "Đã lập chỉ mục",
                "content": content or f"Tài liệu {payload['title']} đã được tải lên bản demo.",
                "citations": "Nội dung tài liệu tải lên",
            }
            state["documents"].insert(0, document)
            state["activity"].insert(
                0, {"text": f"{document['title']} được tải lên và lập chỉ mục", "time": "Vừa xong", "kind": "document"}
            )
            save_state(state)
            self.send_json({"document": public_document(document)}, HTTPStatus.CREATED)
            return

        if parsed.path == "/api/chat":
            question = normalize(str(payload.get("question", "")))
            if not question:
                self.send_json({"error": "Vui lòng nhập câu hỏi."}, HTTPStatus.BAD_REQUEST)
                return
            state = load_state()
            allowed = visible_documents(state, user_code)
            words = {word for word in re.findall(r"\w+", question, re.UNICODE) if len(word) > 2}
            scored = []
            for doc in allowed:
                searchable = normalize(f"{doc['title']} {doc['topic']} {doc['doc_type']} {doc.get('content', '')}")
                score = sum(word in searchable for word in words)
                if score:
                    scored.append((score, doc))
            scored.sort(key=lambda item: item[0], reverse=True)
            matches = [doc for _, doc in scored[:3]]
            if not matches:
                self.send_json(
                    {
                        "answer": "Mình chưa tìm thấy thông tin phù hợp trong các tài liệu bạn được phép truy cập.",
                        "citations": [],
                    }
                )
                return
            summaries = " ".join(doc["content"] for doc in matches[:2])
            answer = f"Dựa trên kho tri thức: {summaries}"
            citations = [
                {"id": doc["id"], "title": doc["title"], "location": doc["citations"], "topic": doc["topic"]}
                for doc in matches
            ]
            self.send_json({"answer": answer, "citations": citations})
            return

        if parsed.path == "/api/access-requests":
            document_id = str(payload.get("document_id", ""))
            state = load_state()
            document = next((doc for doc in state["documents"] if doc["id"] == document_id), None)
            if not document:
                self.send_json({"error": "Không tìm thấy tài liệu."}, HTTPStatus.NOT_FOUND)
                return
            request = {
                "id": f"req-{uuid.uuid4().hex[:8]}",
                "document_id": document_id,
                "document_title": document["title"],
                "requester_code": user_code,
                "owner_code": document["owner_code"],
                "status": "pending",
                "created_at": utc_now(),
            }
            state["access_requests"].insert(0, request)
            state["activity"].insert(0, {"text": f"Yêu cầu truy cập {document['title']} đã được gửi", "time": "Vừa xong", "kind": "access"})
            save_state(state)
            self.send_json({"request": request}, HTTPStatus.CREATED)
            return

        self.send_json({"error": "Endpoint không tồn tại."}, HTTPStatus.NOT_FOUND)


def run_server(host: str, port: int) -> None:
    ensure_state()
    server = ThreadingHTTPServer((host, port), DemoHandler)
    print(f"EduVault demo v1 đang chạy tại http://{host}:{port}")
    print("Mã đăng nhập demo: GV001, GVNEW, TBM01, ADMIN")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng EduVault demo.")
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chạy EduVault demo v1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(args.host, args.port)

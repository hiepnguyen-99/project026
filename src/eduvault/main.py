from __future__ import annotations

import secrets
import html
import os
import difflib
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from .ai import ai_provider
from .cloud import PROVIDERS, authorization_url, disconnect, exchange_code, list_connections, sync_user_document
from .database import ROOT, connection, database_backend, hash_secret, init_database, now, rows, transaction
from .infrastructure import infrastructure_status
from .services import (
    anonymize_document, anonymize_documents, ask, audit, can_read, compliance_report, content_for, create_backup,
    create_document, extract_text, guess_metadata, index_document, knowledge_summary, list_deleted_documents, list_documents, permanently_delete_document,
    quality_report, restore_backup, restore_deleted_document, rollback_document, save_file_asset,
    set_v2_state, soft_delete_document, suggest_folder, sync_document, update_document, usage_report, v2_state_for,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_database()
    with transaction() as db:
        for document in db.execute("SELECT * FROM documents").fetchall():
            exists = db.execute("SELECT 1 FROM chunks WHERE document_id=?", (document["id"],)).fetchone()
            if not exists:
                # Startup must remain available even when an external AI provider is slow.
                index_document(db, document["id"], document["current_version"], content_for(db, dict(document)), force_local=True)
    yield


app = FastAPI(title="EduVault API", version="2.0.0", lifespan=lifespan)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
MAX_AI_ANALYZE_BYTES = int(os.getenv("MAX_AI_ANALYZE_MB", "25")) * 1024 * 1024
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Login(BaseModel):
    code: str
    password: str


class DocumentInput(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    doc_type: str = Field(min_length=2, max_length=80)
    topic: str = Field(min_length=2, max_length=120)
    visibility: Literal["public", "private"]
    content: str = Field(min_length=1)
    folder_path: str | None = None


class AnalyzeInput(BaseModel):
    filename: str
    content: str


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class TransferInput(BaseModel):
    course_code: str
    from_code: str
    to_code: str
    deadline: str


class ProgressInput(BaseModel):
    progress: int = Field(ge=0, le=100)


class ExamPublicationInput(BaseModel):
    publish_after: str = Field(min_length=10, max_length=40)


class PolicyInput(BaseModel):
    value: dict


class UserInput(BaseModel):
    code: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    role: Literal["lecturer", "new_lecturer", "head", "admin"]
    department: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=4, max_length=200)


class UserUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role: Literal["lecturer", "new_lecturer", "head", "admin"]
    department: str = Field(min_length=2, max_length=120)
    active: bool = True


class StorageInput(BaseModel):
    name: str
    provider: Literal["local", "google_drive", "onedrive", "sharepoint"]
    location: str
    enabled: bool = True


class CloudConnectInput(BaseModel):
    provider: Literal["google_drive", "onedrive"]


def current_user(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    with connection() as db:
        user = db.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.code=s.user_code WHERE s.token=? AND u.active=1", (token,)
        ).fetchone()
    if not user:
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ.")
    return dict(user)


def require_roles(*roles):
    def dependency(user: dict = Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "Bạn không có quyền thực hiện thao tác này.")
        return user
    return dependency


def get_document(db, document_id: str) -> dict:
    document = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not document:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    return dict(document)


def get_active_document(db, document_id: str) -> dict:
    document = get_document(db, document_id)
    if document.get("deleted_at"):
        raise HTTPException(404, "Tài liệu đang nằm trong thùng rác.")
    return document


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "database": database_backend(),
        "max_upload_mb": MAX_UPLOAD_BYTES // 1024 // 1024,
        "max_ai_analyze_mb": MAX_AI_ANALYZE_BYTES // 1024 // 1024,
        "ai": ai_provider.status(),
        "infrastructure": infrastructure_status(),
    }


@app.get("/api/v2/status")
def v2_status(user: dict = Depends(current_user)):
    with connection() as db:
        states = rows(db.execute(
            "SELECT lifecycle_status,indexing_status,COUNT(*) count FROM document_v2_state GROUP BY lifecycle_status,indexing_status"
        ).fetchall())
        outbox = rows(db.execute("SELECT status,COUNT(*) count FROM outbox_events GROUP BY status").fetchall())
        objects = rows(db.execute("SELECT provider,COUNT(*) count,SUM(size) size FROM object_refs GROUP BY provider").fetchall())
    return {
        **infrastructure_status(),
        "ai": ai_provider.status(),
        "documents": states,
        "outbox": outbox,
        "objects": objects,
        "scope": "single-faculty",
        "capacity_target_gb": 100,
    }


@app.get("/api/ai/status")
def ai_status(user: dict = Depends(current_user)):
    return ai_provider.status()


@app.get("/api/cloud/connections")
def cloud_connections(user: dict = Depends(current_user)):
    with connection() as db:
        return list_connections(db, user["code"])


@app.post("/api/cloud/connect")
def connect_cloud(payload: CloudConnectInput, user: dict = Depends(current_user)):
    try:
        with transaction() as db:
            url = authorization_url(db, user["code"], payload.provider)
            audit(db, user["code"], "cloud.connect_started", "cloud", payload.provider)
            return {"authorization_url": url}
    except ValueError as exc:
        raise HTTPException(503, str(exc))


@app.get("/api/cloud/callback/{provider}", response_class=HTMLResponse)
def cloud_callback(provider: str, state: str, code: str):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Nhà cung cấp cloud không được hỗ trợ.")
    try:
        with transaction() as db:
            result = exchange_code(db, provider, state, code)
            audit(db, result["user_code"], "cloud.connected", "cloud", provider, {"account": result["account_email"]})
        return HTMLResponse("<h2>Kết nối thành công</h2><p>Bạn có thể đóng cửa sổ này và quay lại EduVault.</p><script>setTimeout(()=>window.close(),1500)</script>")
    except Exception as exc:
        return HTMLResponse(f"<h2>Kết nối thất bại</h2><p>{html.escape(str(exc))}</p>", status_code=400)


@app.delete("/api/cloud/connections/{provider}")
def disconnect_cloud(provider: Literal["google_drive", "onedrive"], user: dict = Depends(current_user)):
    with transaction() as db:
        disconnect(db, user["code"], provider)
        audit(db, user["code"], "cloud.disconnected", "cloud", provider)
    return {"status": "disconnected", "provider": provider}


@app.post("/api/cloud/connections/{provider}/sync")
def sync_personal_cloud(provider: Literal["google_drive", "onedrive"], user: dict = Depends(current_user)):
    with transaction() as db:
        if not db.execute(
            "SELECT 1 FROM cloud_connections WHERE user_code=? AND provider=? AND status='connected'",
            (user["code"], provider),
        ).fetchone():
            raise HTTPException(404, "Kho cloud cá nhân chưa được kết nối.")
        results = []
        for document in db.execute(
            "SELECT * FROM documents WHERE owner_code=? AND deleted_at IS NULL", (user["code"],)
        ).fetchall():
            version = db.execute(
                "SELECT storage_path FROM versions WHERE document_id=? AND version_no=?",
                (document["id"], document["current_version"]),
            ).fetchone()
            results.extend(sync_user_document(db, user["code"], document["id"], __import__("pathlib").Path(version["storage_path"]), provider))
        audit(db, user["code"], "cloud.sync", "cloud", provider, {"documents": len(results)})
        return {"provider": provider, "results": results}


@app.post("/api/auth/login")
def login(payload: Login):
    with transaction() as db:
        user = db.execute("SELECT * FROM users WHERE code=? AND active=1", (payload.code.upper(),)).fetchone()
        if not user or user["password_hash"] != hash_secret(payload.password):
            raise HTTPException(401, "Mã đăng nhập hoặc mật khẩu không đúng.")
        token = secrets.token_urlsafe(32)
        db.execute("INSERT INTO sessions VALUES(?,?,?)", (token, user["code"], now()))
        audit(db, user["code"], "auth.login", "session", token[:8])
        public = {key: user[key] for key in ("code", "name", "role", "department")}
        return {"token": token, "user": public}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default=""), user: dict = Depends(current_user)):
    token = authorization.removeprefix("Bearer ").strip()
    with transaction() as db:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        audit(db, user["code"], "auth.logout", "session", token[:8])
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    with connection() as db:
        docs = list_documents(db, user)
        requests = rows(db.execute("SELECT * FROM access_requests WHERE requester_code=? OR owner_code=? ORDER BY created_at DESC", (user["code"], user["code"])).fetchall())
        for request in requests:
            if request["requester_code"] == user["code"] and request["owner_code"] != user["code"]:
                request["owner_code"] = "Ẩn danh"
        return {
            "user": {key: user[key] for key in ("code", "name", "role", "department")},
            "stats": {"documents": len(docs), "private": sum(d["visibility"] == "private" for d in docs), "topics": len({d["topic"] for d in docs})},
            "documents": [
                {**item, "v2_state": v2_state_for(db, item["id"])}
                for item in anonymize_documents(docs, user)
            ],
            "requests": requests,
            "backups": rows(db.execute("SELECT * FROM backup_logs ORDER BY created_at DESC LIMIT 10").fetchall()),
            "audit": rows(db.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 20").fetchall()) if user["role"] == "admin" else [],
        }


@app.post("/api/documents/analyze")
def analyze(payload: AnalyzeInput, user: dict = Depends(current_user)):
    with connection() as db:
        prompt_row = db.execute("SELECT value FROM policies WHERE key='ai_prompts'").fetchone()
        import json
        prompts = json.loads(prompt_row["value"]) if prompt_row else {}
        metadata = guess_metadata(payload.filename, payload.content, prompts.get("metadata_instructions"))
        duplicate = db.execute("SELECT id,title FROM documents WHERE content_hash=?", (hash_secret(payload.content.strip()),)).fetchone()
        folder_path = suggest_folder(db, user, {**metadata, "visibility": "public"})
    return {"metadata": metadata, "folder_path": folder_path, "duplicate": dict(duplicate) if duplicate else None, "ai": ai_provider.status()}


@app.post("/api/documents/analyze-file")
async def analyze_file(request: Request, x_filename: str = Header(), user: dict = Depends(current_user)):
    from urllib.parse import unquote
    content_length = int(request.headers.get("content-length", "0") or 0)
    if content_length > MAX_AI_ANALYZE_BYTES:
        raise HTTPException(
            413,
            f"File quá lớn để AI phân tích trực tiếp. Giới hạn hiện tại là {MAX_AI_ANALYZE_BYTES // 1024 // 1024} MB; "
            "hãy nhập metadata thủ công để lưu file hoặc dùng xử lý nền.",
        )
    try:
        raw = await request.body()
    except ClientDisconnect:
        raise HTTPException(400, "Kết nối tải file bị ngắt trước khi hoàn tất. Hãy thử tải lại.")
    if not raw:
        raise HTTPException(400, "File phân tích đang trống.")
    if len(raw) > MAX_AI_ANALYZE_BYTES:
        raise HTTPException(
            413,
            f"File quá lớn để AI phân tích trực tiếp. Giới hạn hiện tại là {MAX_AI_ANALYZE_BYTES // 1024 // 1024} MB; "
            "hãy nhập metadata thủ công để lưu file hoặc dùng xử lý nền.",
        )
    filename = unquote(x_filename)
    content = extract_text(filename, request.headers.get("content-type", "application/octet-stream"), raw)
    with connection() as db:
        import json
        prompt_row = db.execute("SELECT value FROM policies WHERE key='ai_prompts'").fetchone()
        prompts = json.loads(prompt_row["value"]) if prompt_row else {}
        metadata = guess_metadata(filename, content, prompts.get("metadata_instructions"))
        duplicate = db.execute("SELECT id,title FROM documents WHERE content_hash=?", (hash_secret(content.strip()),)).fetchone()
        folder_path = suggest_folder(db, user, {**metadata, "visibility": "public"})
    return {
        "metadata": metadata, "folder_path": folder_path, "duplicate": dict(duplicate) if duplicate else None,
        "content_preview": content[:5000], "ai": ai_provider.status(),
    }


@app.post("/api/folders/suggest")
def folder_suggestion(payload: DocumentInput, user: dict = Depends(current_user)):
    with connection() as db:
        return {"folder_path": suggest_folder(db, user, payload.model_dump())}


@app.get("/api/folders/tree")
def folder_tree(user: dict = Depends(current_user)):
    with connection() as db:
        documents = list_documents(db, user)
    tree: dict = {}
    for document in documents:
        node = tree
        for segment in (document.get("folder_path") or "Unsorted").split("/"):
            node = node.setdefault(segment, {})
        node.setdefault("_documents", []).append({"id": document["id"], "title": document["title"]})
    return tree


@app.get("/api/rag/pipeline")
def rag_pipeline(user: dict = Depends(current_user)):
    with connection() as db:
        documents = db.execute(
            "SELECT COUNT(*) count FROM documents WHERE deleted_at IS NULL AND (visibility='public' OR owner_code=?)",
            (user["code"],),
        ).fetchone()["count"]
        chunks = db.execute(
            "SELECT COUNT(*) count FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.deleted_at IS NULL AND (d.visibility='public' OR d.owner_code=?)",
            (user["code"],),
        ).fetchone()["count"]
    return {
        "scope": "public_or_owned",
        "documents": documents,
        "chunks": chunks,
        "stages": [
            {"name": "upload", "status": "ready"},
            {"name": "parse_pdf_docx_ocr", "status": "ready"},
            {"name": "chunk", "status": "ready"},
            {"name": "embedding", "status": "ready", "provider": ai_provider.status()["embedding_model"]},
            {"name": "vector_store", "status": "ready", "provider": "sqlite_chunks"},
            {"name": "permission_filter", "status": "ready", "rule": "public_or_owned"},
            {"name": "retrieve_answer", "status": "ready"},
        ],
    }


@app.post("/api/documents", status_code=201)
def create(payload: DocumentInput, user: dict = Depends(current_user)):
    try:
        with transaction() as db:
            return create_document(db, user, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/documents/upload", status_code=201)
async def upload_document(
    request: Request,
    x_filename: str = Header(),
    x_title: str = Header(),
    x_topic: str = Header(),
    x_doc_type: str = Header(),
    x_visibility: Literal["public", "private"] = Header(),
    x_folder_path: str = Header(default=""),
    user: dict = Depends(current_user),
):
    from urllib.parse import unquote
    content_length = int(request.headers.get("content-length", "0") or 0)
    if content_length > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File vượt quá giới hạn tải lên {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
    try:
        raw = await request.body()
    except ClientDisconnect:
        raise HTTPException(400, "Kết nối tải file bị ngắt trước khi hoàn tất. Hãy thử tải lại.")
    if not raw:
        raise HTTPException(400, "File tải lên đang trống.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File vượt quá giới hạn tải lên {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
    filename = unquote(x_filename)
    mime_type = request.headers.get("content-type", "application/octet-stream")
    payload = {
        "title": unquote(x_title), "topic": unquote(x_topic), "doc_type": unquote(x_doc_type),
        "visibility": x_visibility, "content": extract_text(filename, mime_type, raw), "folder_path": unquote(x_folder_path) or None,
    }
    try:
        with transaction() as db:
            document = create_document(db, user, payload)
            asset = save_file_asset(db, document["id"], 1, filename, mime_type, raw)
            sync_user_document(db, user["code"], document["id"], __import__("pathlib").Path(asset["original_path"]))
            audit(db, user["code"], "file.upload", "document", document["id"], {"filename": filename, "size": len(raw)})
            return {"document": document, "asset": asset}
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.put("/api/documents/{document_id}/upload")
async def upload_new_version(
    document_id: str,
    request: Request,
    x_filename: str = Header(),
    x_title: str = Header(),
    x_topic: str = Header(),
    x_doc_type: str = Header(),
    x_visibility: Literal["public", "private"] = Header(),
    x_folder_path: str = Header(default=""),
    user: dict = Depends(current_user),
):
    from urllib.parse import unquote
    try:
        raw = await request.body()
    except ClientDisconnect:
        raise HTTPException(400, "Kết nối tải file bị ngắt trước khi hoàn tất. Hãy thử tải lại.")
    if not raw:
        raise HTTPException(400, "File tải lên đang trống.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds the configured {MAX_UPLOAD_BYTES // 1024 // 1024} MB limit.")
    filename = unquote(x_filename)
    mime_type = request.headers.get("content-type", "application/octet-stream")
    payload = {
        "title": unquote(x_title), "topic": unquote(x_topic), "doc_type": unquote(x_doc_type),
        "visibility": x_visibility, "content": extract_text(filename, mime_type, raw), "folder_path": unquote(x_folder_path) or None,
    }
    try:
        with transaction() as db:
            document = update_document(db, user, get_document(db, document_id), payload)
            asset = save_file_asset(db, document_id, document["current_version"], filename, mime_type, raw)
            sync_user_document(db, user["code"], document_id, __import__("pathlib").Path(asset["original_path"]))
            audit(db, user["code"], "file.upload_version", "document", document_id, {"filename": filename})
            return {"document": document, "asset": asset}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.put("/api/documents/{document_id}")
def update(document_id: str, payload: DocumentInput, user: dict = Depends(current_user)):
    try:
        with transaction() as db:
            return update_document(db, user, get_active_document(db, document_id), payload.model_dump())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.get("/api/documents/{document_id}")
def document_detail(document_id: str, user: dict = Depends(current_user)):
    with connection() as db:
        document = get_active_document(db, document_id)
        if not can_read(db, user, document):
            raise HTTPException(403, "Bạn không có quyền xem tài liệu.")
        return {**anonymize_document(document, user), "content": content_for(db, document)}


@app.get("/api/documents/{document_id}/versions")
def versions(document_id: str, user: dict = Depends(current_user)):
    with connection() as db:
        document = get_document(db, document_id)
        if not can_read(db, user, document):
            raise HTTPException(403, "Bạn không có quyền xem tài liệu.")
        result = rows(db.execute("SELECT id,version_no,created_by,created_at FROM versions WHERE document_id=? ORDER BY version_no DESC", (document_id,)).fetchall())
        if document["visibility"] == "private" and document["owner_code"] != user["code"]:
            for version in result:
                version["created_by"] = "Ẩn danh"
        return result


@app.get("/api/documents/{document_id}/versions/compare")
def compare_versions(
    document_id: str,
    base_version: int,
    target_version: int,
    user: dict = Depends(current_user),
):
    with connection() as db:
        document = get_document(db, document_id)
        if not can_read(db, user, document):
            raise HTTPException(403, "Bạn không có quyền xem tài liệu.")
        version_rows = rows(db.execute(
            "SELECT version_no,storage_path FROM versions WHERE document_id=? AND version_no IN (?,?)",
            (document_id, base_version, target_version),
        ).fetchall())
        paths = {item["version_no"]: item["storage_path"] for item in version_rows}
        if base_version not in paths or target_version not in paths:
            raise HTTPException(404, "Không tìm thấy một trong hai phiên bản cần so sánh.")
        base_content = __import__("pathlib").Path(paths[base_version]).read_text(encoding="utf-8")
        target_content = __import__("pathlib").Path(paths[target_version]).read_text(encoding="utf-8")
        changes = []
        stats = {"added": 0, "removed": 0, "unchanged": 0}
        for line in difflib.ndiff(base_content.splitlines(), target_content.splitlines()):
            prefix = line[:2]
            if prefix == "? ":
                continue
            kind = "added" if prefix == "+ " else "removed" if prefix == "- " else "unchanged"
            stats[kind] += 1
            changes.append({"kind": kind, "content": line[2:]})
        return {
            "document_id": document_id,
            "base_version": base_version,
            "target_version": target_version,
            "stats": stats,
            "changes": changes,
            "base_content": base_content,
            "target_content": target_content,
        }


@app.get("/api/documents/{document_id}/provenance")
def provenance(document_id: str, user: dict = Depends(current_user)):
    with connection() as db:
        document = get_document(db, document_id)
        if not can_read(db, user, document):
            raise HTTPException(403, "Bạn không có quyền xem nguồn gốc tài liệu.")
        access = {"type": "public" if document["visibility"] == "public" else "owner", "request_id": None}
        if document["visibility"] == "private" and document["owner_code"] != user["code"]:
            approved = db.execute(
                "SELECT id FROM access_requests WHERE document_id=? AND requester_code=? AND status='approved' ORDER BY resolved_at DESC LIMIT 1",
                (document_id, user["code"]),
            ).fetchone()
            access = {"type": "approved_request", "request_id": approved["id"] if approved else None}
        versions_result = rows(db.execute("SELECT id,version_no,created_by,created_at FROM versions WHERE document_id=? ORDER BY version_no DESC", (document_id,)).fetchall())
        if document["visibility"] == "private" and document["owner_code"] != user["code"]:
            for version in versions_result:
                version["created_by"] = "Ẩn danh"
        return {
            "document": anonymize_document(document, user),
            "versions": versions_result,
            "sync_history": rows(db.execute("SELECT * FROM sync_logs WHERE document_id=? ORDER BY created_at DESC", (document_id,)).fetchall()),
            "files": rows(db.execute("SELECT id,version_no,original_name,mime_type,size,created_at FROM file_assets WHERE document_id=? ORDER BY version_no DESC", (document_id,)).fetchall()),
            "objects": rows(db.execute("SELECT id,version_no,kind,provider,object_uri,checksum,size,created_at FROM object_refs WHERE document_id=? ORDER BY created_at DESC", (document_id,)).fetchall()),
            "v2_state": v2_state_for(db, document_id),
            "access": access,
        }


@app.get("/api/files/{asset_id}")
def download_file(asset_id: str, user: dict = Depends(current_user)):
    with connection() as db:
        asset = db.execute("SELECT * FROM file_assets WHERE id=?", (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(404, "Không tìm thấy file.")
        document = get_document(db, asset["document_id"])
        if not can_read(db, user, document):
            raise HTTPException(403, "Bạn không có quyền tải file.")
        return FileResponse(asset["original_path"], filename=asset["original_name"], media_type=asset["mime_type"])


@app.get("/api/permissions")
def permissions(user: dict = Depends(current_user)):
    with connection() as db:
        readable = list_documents(db, user)
        editable = [item for item in readable if item["owner_code"] == user["code"]]
        restricted = rows(db.execute(
            "SELECT id,title,owner_code,topic FROM documents WHERE visibility='private' AND owner_code!=?",
            (user["code"],),
        ).fetchall())
        restricted = [item for item in restricted if not can_read(db, user, {**item, "visibility": "private"})]
        return {
            "readable": anonymize_documents(readable, user),
            "editable": anonymize_documents(editable, user),
            "restricted": anonymize_documents([{**item, "visibility": "private"} for item in restricted], user),
        }


@app.post("/api/documents/{document_id}/rollback/{version_no}")
def rollback(document_id: str, version_no: int, user: dict = Depends(current_user)):
    try:
        with transaction() as db:
            return rollback_document(db, user, get_active_document(db, document_id), version_no)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/search")
def search(payload: Question, user: dict = Depends(current_user)):
    with transaction() as db:
        return ask(db, user, payload.question)


@app.get("/api/trash")
def trash(user: dict = Depends(current_user)):
    with connection() as db:
        return list_deleted_documents(db, user)


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str, user: dict = Depends(current_user)):
    try:
        with transaction() as db:
            return soft_delete_document(db, user, get_active_document(db, document_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/trash/{document_id}/restore")
def restore_document(document_id: str, user: dict = Depends(current_user)):
    try:
        with transaction() as db:
            return restore_deleted_document(db, user, get_document(db, document_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/trash/{document_id}")
def purge_document(document_id: str, user: dict = Depends(current_user)):
    try:
        with transaction() as db:
            return permanently_delete_document(db, user, get_document(db, document_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/onboarding/courses")
def onboarding_courses(user: dict = Depends(current_user)):
    with connection() as db:
        courses = rows(db.execute("SELECT * FROM courses ORDER BY code").fetchall())
        for course in courses:
            course["knowledge"] = knowledge_summary(db, user, topic=course["name"])
        return courses


@app.get("/api/onboarding/processes")
def onboarding_processes(user: dict = Depends(current_user)):
    with connection() as db:
        return knowledge_summary(db, user, doc_type="Quy trình")


@app.get("/api/transfers")
def transfers(user: dict = Depends(current_user)):
    with connection() as db:
        if user["role"] in {"head", "admin"}:
            return rows(db.execute("SELECT t.*,c.name course_name FROM transfers t JOIN courses c ON c.code=t.course_code ORDER BY created_at DESC").fetchall())
        return rows(db.execute("SELECT t.*,c.name course_name FROM transfers t JOIN courses c ON c.code=t.course_code WHERE from_code=? OR to_code=? ORDER BY created_at DESC", (user["code"], user["code"])).fetchall())


@app.post("/api/transfers", status_code=201)
def create_transfer(payload: TransferInput, user: dict = Depends(require_roles("head", "admin"))):
    transfer_id = f"transfer-{secrets.token_hex(5)}"
    with transaction() as db:
        if not db.execute("SELECT 1 FROM courses WHERE code=?", (payload.course_code,)).fetchone():
            raise HTTPException(404, "Học phần không tồn tại.")
        db.execute("INSERT INTO transfers VALUES(?,?,?,?,?,'active',0,?)", (transfer_id, payload.course_code, payload.from_code, payload.to_code, payload.deadline, now()))
        audit(db, user["code"], "transfer.create", "transfer", transfer_id)
        return dict(db.execute("SELECT * FROM transfers WHERE id=?", (transfer_id,)).fetchone())


@app.put("/api/transfers/{transfer_id}/progress")
def update_transfer_progress(transfer_id: str, payload: ProgressInput, user: dict = Depends(current_user)):
    with transaction() as db:
        transfer = db.execute("SELECT * FROM transfers WHERE id=?", (transfer_id,)).fetchone()
        if not transfer:
            raise HTTPException(404, "Không tìm thấy phiên chuyển giao.")
        if user["role"] not in {"head", "admin"} and user["code"] not in {transfer["from_code"], transfer["to_code"]}:
            raise HTTPException(403, "Bạn không có quyền cập nhật chuyển giao.")
        status = "completed" if payload.progress == 100 else "active"
        db.execute("UPDATE transfers SET progress=?,status=? WHERE id=?", (payload.progress, status, transfer_id))
        audit(db, user["code"], "transfer.progress", "transfer", transfer_id, {"progress": payload.progress})
        return {"id": transfer_id, "progress": payload.progress, "status": status}


@app.get("/api/quality")
def quality(user: dict = Depends(require_roles("head", "admin"))):
    with connection() as db:
        report = quality_report(db)
        report["stale"] = anonymize_documents(report["stale"], user)
        return report


@app.post("/api/v2/exams/{document_id}/schedule-publication")
def schedule_exam_publication(
    document_id: str, payload: ExamPublicationInput, user: dict = Depends(require_roles("head", "admin"))
):
    with transaction() as db:
        document = get_active_document(db, document_id)
        db.execute("UPDATE documents SET visibility='private',updated_at=? WHERE id=?", (now(), document_id))
        state = set_v2_state(
            db, document_id, classification="confidential", lifecycle_status="published",
            publish_after=payload.publish_after,
        )
        audit(db, user["code"], "exam.publication_scheduled", "document", document_id, {"publish_after": payload.publish_after})
        return state


@app.post("/api/v2/exams/process-publications")
def process_exam_publications(user: dict = Depends(require_roles("head", "admin"))):
    with transaction() as db:
        due = rows(db.execute(
            "SELECT * FROM document_v2_state WHERE classification='confidential' AND publish_after IS NOT NULL AND publish_after<=?",
            (now(),),
        ).fetchall())
        for state in due:
            db.execute("UPDATE documents SET visibility='public',updated_at=? WHERE id=?", (now(), state["document_id"]))
            set_v2_state(db, state["document_id"], classification="public", publish_after=None)
            audit(db, user["code"], "exam.published", "document", state["document_id"])
        return {"published": len(due), "documents": [item["document_id"] for item in due]}


@app.get("/api/reports/usage")
def report_usage(user: dict = Depends(require_roles("head", "admin"))):
    with connection() as db:
        return usage_report(db)


@app.get("/api/backups/compliance")
def backup_compliance(user: dict = Depends(require_roles("head", "admin"))):
    with connection() as db:
        return compliance_report(db)


@app.post("/api/access-requests/{document_id}", status_code=201)
def request_access(document_id: str, user: dict = Depends(current_user)):
    with transaction() as db:
        document = get_active_document(db, document_id)
        if document["visibility"] != "private":
            raise HTTPException(400, "Tài liệu này không yêu cầu phê duyệt.")
        if document["owner_code"] == user["code"]:
            raise HTTPException(400, "Bạn đã là chủ sở hữu tài liệu.")
        if can_read(db, user, document):
            raise HTTPException(400, "Bạn đã được cấp quyền đọc tài liệu.")
        request_id = f"req-{secrets.token_hex(6)}"
        try:
            db.execute("INSERT INTO access_requests VALUES(?,?,?,?, 'pending', ?, NULL)", (request_id, document_id, user["code"], document["owner_code"], now()))
        except Exception:
            raise HTTPException(409, "Đã có yêu cầu đang chờ xử lý.")
        audit(db, user["code"], "access.request", "document", document_id)
        return {"id": request_id, "status": "pending"}


@app.post("/api/access-requests/{request_id}/revoke")
def revoke_access(request_id: str, user: dict = Depends(current_user)):
    with transaction() as db:
        request = db.execute("SELECT * FROM access_requests WHERE id=? AND status='approved'", (request_id,)).fetchone()
        if not request:
            raise HTTPException(404, "Không tìm thấy quyền truy cập đang có hiệu lực.")
        if request["owner_code"] != user["code"]:
            raise HTTPException(403, "Chỉ chủ sở hữu được thu hồi quyền truy cập.")
        db.execute("UPDATE access_requests SET status='revoked',resolved_at=? WHERE id=?", (now(), request_id))
        audit(db, user["code"], "access.revoked", "request", request_id)
        return {"id": request_id, "status": "revoked"}


@app.post("/api/access-requests/{request_id}/{decision}")
def decide_access(request_id: str, decision: Literal["approved", "denied"], user: dict = Depends(current_user)):
    with transaction() as db:
        request = db.execute("SELECT * FROM access_requests WHERE id=? AND status='pending'", (request_id,)).fetchone()
        if not request:
            raise HTTPException(404, "Không tìm thấy yêu cầu đang chờ.")
        if request["owner_code"] != user["code"]:
            raise HTTPException(403, "Bạn không có quyền phê duyệt yêu cầu.")
        db.execute("UPDATE access_requests SET status=?,resolved_at=? WHERE id=?", (decision, now(), request_id))
        audit(db, user["code"], f"access.{decision}", "request", request_id)
        return {"id": request_id, "status": decision}


@app.get("/api/admin/users")
def users(user: dict = Depends(require_roles("admin"))):
    with connection() as db:
        return rows(db.execute("SELECT code,name,role,department,active FROM users ORDER BY code").fetchall())


@app.post("/api/admin/users", status_code=201)
def create_user(payload: UserInput, user: dict = Depends(require_roles("admin"))):
    with transaction() as db:
        try:
            db.execute("INSERT INTO users VALUES(?,?,?,?,?,1)", (payload.code.upper(), payload.name, payload.role, payload.department, hash_secret(payload.password)))
        except Exception:
            raise HTTPException(409, "Mã người dùng đã tồn tại.")
        audit(db, user["code"], "user.create", "user", payload.code.upper())
        return {"code": payload.code.upper(), "name": payload.name, "role": payload.role, "department": payload.department, "active": 1}


@app.put("/api/admin/users/{code}")
def update_user(code: str, payload: UserUpdate, user: dict = Depends(require_roles("admin"))):
    with transaction() as db:
        if not db.execute("SELECT 1 FROM users WHERE code=?", (code.upper(),)).fetchone():
            raise HTTPException(404, "Người dùng không tồn tại.")
        db.execute("UPDATE users SET name=?,role=?,department=?,active=? WHERE code=?", (payload.name, payload.role, payload.department, int(payload.active), code.upper()))
        audit(db, user["code"], "user.update", "user", code.upper())
        return {"code": code.upper(), **payload.model_dump()}


@app.get("/api/admin/policies")
def policies(user: dict = Depends(require_roles("admin"))):
    with connection() as db:
        result = rows(db.execute("SELECT * FROM policies ORDER BY key").fetchall())
        for item in result:
            import json
            item["value"] = json.loads(item["value"])
        return result


@app.put("/api/admin/policies/{key}")
def update_policy(key: str, payload: PolicyInput, user: dict = Depends(require_roles("admin"))):
    import json
    if key == "backup_321":
        required = {"copies", "media", "offsite"}
        if not required.issubset(payload.value) or any(not isinstance(payload.value[item], int) or payload.value[item] < 1 for item in required):
            raise HTTPException(422, "Policy backup cần copies, media và offsite là số nguyên lớn hơn 0.")
        if payload.value["offsite"] > payload.value["copies"]:
            raise HTTPException(422, "Số bản ngoài hệ thống không thể lớn hơn tổng số bản sao.")
    elif key == "permission_rules":
        if payload.value.get("private_requires_owner_approval") is not True:
            raise HTTPException(422, "Tài liệu riêng tư luôn bắt buộc chủ sở hữu phê duyệt.")
    elif key == "storage_rules":
        naming = payload.value.get("naming", "")
        retention = payload.value.get("retention_years")
        allowed = {"{department}", "{topic}", "{doc_type}", "{visibility}", "{owner_code}", "{title}"}
        fields = set(__import__("re").findall(r"\{[^}]+\}", naming))
        if not naming or not fields or not fields.issubset(allowed):
            raise HTTPException(422, "Cấu trúc thư mục phải sử dụng các trường metadata được hỗ trợ.")
        if not isinstance(retention, int) or retention < 1:
            raise HTTPException(422, "Thời gian lưu trữ phải là số năm lớn hơn 0.")
    elif key == "ai_prompts":
        if not all(isinstance(payload.value.get(item), str) and len(payload.value[item].strip()) >= 10 for item in ("metadata_instructions", "answer_instructions")):
            raise HTTPException(422, "Prompt AI phải gồm hướng dẫn metadata và hỏi đáp, mỗi prompt tối thiểu 10 ký tự.")
    elif key == "exam_publication":
        if payload.value.get("classification_before_exam") != "confidential":
            raise HTTPException(422, "Đề thi trước ngày thi bắt buộc có classification confidential.")
        if payload.value.get("publish_after_exam") is not True:
            raise HTTPException(422, "V2 yêu cầu hỗ trợ công bố đề thi sau ngày thi.")
    with transaction() as db:
        db.execute("INSERT INTO policies(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (key, json.dumps(payload.value, ensure_ascii=False), now()))
        audit(db, user["code"], "policy.update", "policy", key)
        return {"key": key, "value": payload.value}


@app.get("/api/admin/storages")
def storages(user: dict = Depends(require_roles("admin"))):
    with connection() as db:
        return rows(db.execute("SELECT * FROM external_storages ORDER BY id").fetchall())


@app.post("/api/admin/storages", status_code=201)
def create_storage(payload: StorageInput, user: dict = Depends(require_roles("admin"))):
    storage_id = f"storage-{secrets.token_hex(5)}"
    from pathlib import Path
    Path(payload.location).mkdir(parents=True, exist_ok=True)
    with transaction() as db:
        db.execute("INSERT INTO external_storages VALUES(?,?,?,?,?,?,?)", (storage_id, payload.name, payload.provider, payload.location, int(payload.enabled), None, "ready"))
        audit(db, user["code"], "storage.create", "storage", storage_id)
        return dict(db.execute("SELECT * FROM external_storages WHERE id=?", (storage_id,)).fetchone())


@app.post("/api/admin/storages/{storage_id}/sync")
def sync_storage(storage_id: str, user: dict = Depends(require_roles("admin"))):
    with transaction() as db:
        if not db.execute("SELECT 1 FROM external_storages WHERE id=?", (storage_id,)).fetchone():
            raise HTTPException(404, "Kho lưu trữ không tồn tại.")
        results = []
        for document in db.execute("SELECT * FROM documents").fetchall():
            version = db.execute("SELECT storage_path FROM versions WHERE document_id=? AND version_no=?", (document["id"], document["current_version"])).fetchone()
            results.extend(sync_document(db, document["id"], __import__("pathlib").Path(version["storage_path"]), storage_id))
        audit(db, user["code"], "storage.sync", "storage", storage_id)
        return {"synced": len(results), "results": results}


@app.post("/api/admin/backups", status_code=201)
def backup(user: dict = Depends(require_roles("admin"))):
    with transaction() as db:
        return create_backup(db, user)


@app.post("/api/admin/backups/{backup_id}/restore")
def restore(backup_id: str, user: dict = Depends(require_roles("admin"))):
    try:
        with transaction() as db:
            return restore_backup(db, user, backup_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


WEB = ROOT / "web"
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


@app.get("/")
def index():
    return FileResponse(WEB / "mvp.html")

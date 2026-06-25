from __future__ import annotations

import secrets
import html
import os
import difflib
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from .ai import ai_provider
from .cloud import PROVIDERS, authorization_url, disconnect, exchange_code, list_connections, sync_user_document
from .database import DATA_DIR, ROOT, connection, database_backend, hash_secret, init_database, now, rows, transaction
from .infrastructure import infrastructure_status
from .services import (
    anonymize_document, anonymize_documents, ask, audit, can_read, compliance_report, content_for, create_backup, delete_policy_file,
    DOCUMENT_TYPES, active_course_suggestions, active_policy, apply_due_time_based_permission_rules, apply_policy_action, create_document, create_policy_action_request, create_policy_file, enqueue_processing_jobs, expire_time_based_permission_rule, extract_text, folder_assignment_from_metadata, get_my_folder_tree, guess_metadata, index_document, knowledge_summary,
    knowledge_transfer_actions, knowledge_transfer_course_gaps, knowledge_transfer_insights, knowledge_transfer_lecturer_dependency, knowledge_transfer_specialization_insights,
    list_deleted_documents, list_documents, list_policy_files, master_tree, permanently_delete_document,
    governance_rule_detail, list_governance_rules,
    build_lecturer_folder_tree, profile_specializations, public_specializations, quality_report, restore_backup, restore_deleted_document, rollback_document, save_file_asset,
    extraction_placeholder, global_knowledge_search, list_audit_logs, meaningful_text_score, qdrant_reindex_status, quick_preview_text, run_document_processing_jobs, set_v2_state, soft_delete_document, suggest_folder, suggest_upload_destination, sync_document, update_document, usage_report, v2_state_for,
    activate_policy_file, preview_policy_activation, preview_policy_action, rollback_policy_action, set_user_specializations, validate_folder_access,
    confirm_lecturer_assignment_batch, lecturer_assignment_batch_detail, list_lecturer_assignments, my_assignment, preview_lecturer_assignment_import,
    operations_status, record_automation_heartbeat, verify_restore_backup,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_security_config()
    init_database()
    with transaction() as db:
        for document in db.execute("SELECT * FROM documents WHERE status='INDEXED'").fetchall():
            exists = db.execute("SELECT 1 FROM chunks WHERE document_id=?", (document["id"],)).fetchone()
            if not exists:
                # Startup must remain available even when an external AI provider is slow.
                index_document(db, document["id"], document["current_version"], content_for(db, dict(document)), force_local=True)
    yield


app = FastAPI(title="EduVault API", version="2.0.0", lifespan=lifespan)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
MAX_AI_ANALYZE_BYTES = int(os.getenv("MAX_AI_ANALYZE_MB", "25")) * 1024 * 1024


REQUIRED_SECURITY_ENV = (
    "N8N_POLICY_SECRET",
    "TOKEN_ENCRYPTION_KEY",
    "SESSION_TTL_MINUTES",
)

INSECURE_SECRET_VALUES = {
    "dev-policy-secret",
    "eduvault-demo-key-change-before-production",
    "change-me",
    "change-root-me",
    "eduvault-demo-secret",
    "ADMIN",
    "GV001",
    "GVNEW",
    "TBM01",
}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    if value in INSECURE_SECRET_VALUES:
        raise RuntimeError(f"Insecure demo value is not allowed for environment variable: {name}")
    return value


def validate_security_config() -> None:
    for name in REQUIRED_SECURITY_ENV:
        _required_env(name)
    ttl_raw = _required_env("SESSION_TTL_MINUTES")
    try:
        ttl = int(ttl_raw)
    except ValueError as exc:
        raise RuntimeError("SESSION_TTL_MINUTES must be an integer.") from exc
    if ttl <= 0:
        raise RuntimeError("SESSION_TTL_MINUTES must be greater than zero.")
    if os.getenv("DATABASE_PROVIDER", "sqlite").strip().lower() == "mysql":
        _required_env("MYSQL_PASSWORD")
    if os.getenv("MINIO_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        _required_env("MINIO_ACCESS_KEY")
        _required_env("MINIO_SECRET_KEY")
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
    folder_node_id: str | None = None


class AnalyzeInput(BaseModel):
    filename: str
    content: str


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    filters: dict | None = None


class SearchFeedbackInput(BaseModel):
    trace_id: str
    rating: str
    reason: str = ""
    detail: str = ""


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


class PolicyAssistantInput(BaseModel):
    message: str = Field(min_length=2, max_length=1000)


class PolicyAssistantConfirmInput(BaseModel):
    message: str = Field(min_length=2, max_length=1000)
    action: dict
    preview: dict
    apply_now: bool = False


class InternalPolicyApplyInput(BaseModel):
    request_id: str | None = None
    actor: str = Field(default="n8n", min_length=2, max_length=60)
    action: dict


class InternalPolicyRollbackInput(BaseModel):
    audit_log_id: str
    actor: str = Field(default="n8n", min_length=2, max_length=60)


class AutomationHeartbeatInput(BaseModel):
    workflow: Literal["policy_activation", "lecturer_assignment"] | None = None
    workflow_name: str | None = Field(default=None, max_length=120)
    status: Literal["success", "failure", "error"]
    timestamp: str | None = Field(default=None, max_length=80)
    detail: dict = Field(default_factory=dict)
    details: dict | str | None = None


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


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4, max_length=200)


class ProfileUpdateInput(BaseModel):
    new_name: str = Field(min_length=2, max_length=120)
    new_department: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=5, max_length=500)


class CloudConnectInput(BaseModel):
    provider: Literal["google_drive", "onedrive"]


class UploadInitInput(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="application/octet-stream", max_length=255)
    total_bytes: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=200)
    topic: str = Field(min_length=2, max_length=120)
    doc_type: str = Field(min_length=2, max_length=80)
    visibility: Literal["public", "private"]
    folder_path: str | None = None
    folder_node_id: str | None = None
    existing_document_id: str | None = None
    specialization_id: str | None = None
    course_id: str | None = None
    final_destination_source: Literal["manual", "ai"] | None = None


class UploadConfirmInput(BaseModel):
    specialization_id: str | None = None
    course_id: str | None = None
    folder_node_id: str | None = None
    folder_path: str | None = None
    document_type: str = Field(min_length=2, max_length=80)
    visibility: Literal["public", "private"]
    final_destination_source: Literal["manual", "ai"] | None = None


class SpecializationSelection(BaseModel):
    specialization_ids: list[str] = Field(default_factory=list)


class LecturerAssignmentConfirmInput(BaseModel):
    batch_preview_id: str
    apply_mode: Literal["replace_for_listed_lecturers", "append", "replace_all"] = "replace_for_listed_lecturers"


def metadata_payload_for_upload(
    db,
    user: dict,
    filename: str,
    mime_type: str,
    raw: bytes,
    *,
    title: str = "",
    topic: str = "",
    doc_type: str = "",
    visibility: str = "public",
    folder_path: str = "",
    folder_node_id: str = "",
) -> dict:
    preview = quick_preview_text(filename, mime_type, raw)
    prompt_row = db.execute("SELECT value FROM policies WHERE key='ai_prompts'").fetchone()
    prompts = json.loads(prompt_row["value"]) if prompt_row else {}
    metadata = guess_metadata(filename, preview or filename, prompts.get("metadata_instructions"))
    suggestion = suggest_upload_destination(db, dict(user), filename, preview or filename)
    selected_type = doc_type.strip()
    if selected_type not in DOCUMENT_TYPES:
        selected_type = metadata.get("doc_type") or suggestion.get("document_type") or "Tài liệu khác"
    if selected_type not in DOCUMENT_TYPES:
        selected_type = "Tài liệu khác"
    payload = {
        "title": title.strip() or metadata.get("title") or Path(filename).stem.replace("_", " ").replace("-", " ").strip() or "Tài liệu chưa đặt tên",
        "topic": topic.strip() or metadata.get("topic") or suggestion.get("course") or suggestion.get("specialization") or "Khác",
        "doc_type": selected_type,
        "visibility": visibility,
        "content": preview or f"File: {filename}\nStatus: UPLOADED. AI processing is running asynchronously.",
        "folder_path": folder_path.strip() or suggestion.get("folder_path") or None,
        "folder_node_id": folder_node_id or None,
    }
    payload["folder_path"] = payload["folder_path"] or suggest_folder(db, dict(user), payload)
    return payload


def current_user(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    with connection() as db:
        user = db.execute(
            "SELECT u.*, s.created_at session_created_at FROM sessions s JOIN users u ON u.code=s.user_code WHERE s.token=? AND u.active=1", (token,)
        ).fetchone()
    if not user:
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ.")
    ttl_minutes = int(_required_env("SESSION_TTL_MINUTES"))
    try:
        created_at = datetime.fromisoformat(user["session_created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        with connection() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (token,))
            db.commit()
        raise HTTPException(401, "Phiên đăng nhập đã hết hạn.")
    if datetime.now(timezone.utc) - created_at > timedelta(minutes=ttl_minutes):
        with connection() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (token,))
            db.commit()
        raise HTTPException(401, "Phiên đăng nhập đã hết hạn.")
    user_dict = dict(user)
    user_dict.pop("session_created_at", None)
    return user_dict


def require_roles(*roles):
    def dependency(user: dict = Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "Bạn không có quyền thực hiện thao tác này.")
        return user
    return dependency


ROLE_PERMISSIONS = {
    "admin": [
        "dashboard.view", "repository.view", "repository.upload", "policy.manage", "users.manage",
        "permissions.manage", "backup.manage", "cloud.sync", "reports.view", "audit.view", "profile.manage", "transfer.manage",
    ],
    "head": [
        "dashboard.view", "repository.view", "policy.manage", "cloud.sync", "transfer.manage", "quality.view", "reports.view", "profile.manage",
    ],
    "lecturer": [
        "dashboard.view", "repository.own", "repository.upload", "cloud.sync", "versions.view", "chatbot.use", "profile.manage",
    ],
    "new_lecturer": [
        "dashboard.view", "cloud.sync", "handover.view", "knowledge.summary", "chatbot.use", "profile.manage",
    ],
}


def permissions_for_role(role: str) -> list[str]:
    return ROLE_PERMISSIONS.get(role, ["dashboard.view"])


def public_user(user: dict) -> dict:
    return {
        "code": user["code"],
        "name": user["name"],
        "role": user["role"],
        "department": user["department"],
        "permissions": permissions_for_role(user["role"]),
    }


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


def require_internal_policy_secret(x_internal_policy_secret: str = Header(default="")) -> None:
    expected = _required_env("N8N_POLICY_SECRET")
    if not expected or not secrets.compare_digest(x_internal_policy_secret, expected):
        raise HTTPException(403, "Internal policy endpoint chi cho n8n workflow duoc phep goi.")


def maybe_call_n8n_policy_webhook(payload: dict) -> dict:
    webhook_url = os.getenv("N8N_POLICY_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return {"status": "not_configured", "message": "N8N_POLICY_WEBHOOK_URL chua duoc cau hinh; request dang cho n8n goi webhook."}
    import urllib.request
    import urllib.error
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read().decode("utf-8")
            try:
                return {"status": "sent", "response": json.loads(text)}
            except json.JSONDecodeError:
                return {"status": "sent", "response": text}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"status": "failed", "message": str(exc)}


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


@app.get("/api/operations/status")
def operations(user: dict = Depends(require_roles("admin"))):
    with connection() as db:
        return operations_status(db)


@app.post("/api/operations/backups/{backup_id}/verify")
def verify_backup_restore(backup_id: str, user: dict = Depends(require_roles("admin"))):
    try:
        with transaction() as db:
            return verify_restore_backup(db, user, backup_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/operations/n8n/heartbeat")
def n8n_heartbeat(payload: AutomationHeartbeatInput, _: None = Depends(require_internal_policy_secret)):
    try:
        with transaction() as db:
            workflow = payload.workflow or payload.workflow_name
            detail = payload.detail or {}
            if payload.details is not None:
                detail = payload.details if isinstance(payload.details, dict) else {"message": payload.details}
            return record_automation_heartbeat(db, workflow or "", payload.status, detail, payload.timestamp)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


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
            asset = db.execute(
                """SELECT original_path FROM file_assets
                   WHERE document_id=? AND version_no=?
                   ORDER BY created_at DESC, id DESC LIMIT 1""",
                (document["id"], document["current_version"]),
            ).fetchone()
            version = db.execute(
                "SELECT storage_path FROM versions WHERE document_id=? AND version_no=?",
                (document["id"], document["current_version"]),
            ).fetchone()
            source_path = asset["original_path"] if asset else version["storage_path"]
            results.extend(sync_user_document(db, user["code"], document["id"], __import__("pathlib").Path(source_path), provider))
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
        return {"token": token, "user": public_user(dict(user))}


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
            "user": public_user(user),
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
    mime_type = request.headers.get("content-type", "application/octet-stream")
    content = extract_text(filename, mime_type, raw)
    with connection() as db:
        payload = metadata_payload_for_upload(db, user, filename, mime_type, raw)
        metadata = {
            "title": payload["title"],
            "topic": payload["topic"],
            "doc_type": payload["doc_type"],
            "summary": content[:300].strip(),
            "visibility": payload["visibility"],
        }
        classification_ticket = build_classification_ticket_preview(db, filename, content[:5000], metadata)
        duplicate = db.execute("SELECT id,title FROM documents WHERE content_hash=?", (hash_secret(content.strip()),)).fetchone()
    return {
        "metadata": metadata, "folder_path": payload["folder_path"], "duplicate": dict(duplicate) if duplicate else None,
        "content_preview": content[:5000], "classification_ticket": classification_ticket, "ai": ai_provider.status(),
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


@app.post("/api/policies/upload", status_code=201)
async def upload_policy(
    request: Request,
    x_filename: str = Header(default="policy.txt"),
    x_title: str = Header(default="Policy khoa"),
    user: dict = Depends(require_roles("admin")),
):
    from urllib.parse import unquote
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "File policy dang trong.")
    with transaction() as db:
        try:
            return create_policy_file(
                db,
                user,
                unquote(x_title),
                unquote(x_filename),
                raw,
                request.headers.get("content-type", "text/plain"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.get("/api/policies")
def policy_files(user: dict = Depends(require_roles("admin", "head"))):
    with connection() as db:
        return list_policy_files(db)


@app.post("/api/policies/{policy_id}/activate")
def activate_policy(policy_id: str, user: dict = Depends(require_roles("admin"))):
    try:
        with transaction() as db:
            return activate_policy_file(db, user, policy_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/policies/{policy_id}/activation-preview")
def policy_activation_preview(policy_id: str, user: dict = Depends(require_roles("admin"))):
    try:
        with connection() as db:
            return preview_policy_activation(db, policy_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/api/policies/{policy_id}")
def delete_policy(policy_id: str, user: dict = Depends(require_roles("admin"))):
    try:
        with transaction() as db:
            return delete_policy_file(db, user, policy_id)
    except PermissionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/policy-assistant/preview")
def policy_assistant_preview(payload: PolicyAssistantInput, user: dict = Depends(require_roles("admin", "head"))):
    with transaction() as db:
        try:
            return preview_policy_action(db, payload.message, user)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.post("/api/policy-assistant/confirm")
def policy_assistant_confirm(payload: PolicyAssistantConfirmInput, user: dict = Depends(require_roles("admin", "head"))):
    applied = None
    try:
        with transaction() as db:
            request = create_policy_action_request(db, user, payload.message, payload.action, payload.preview)
            if payload.apply_now:
                applied = apply_policy_action(db, user["code"], payload.action, request["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    n8n = {"status": "skipped", "reason": "apply_now"} if payload.apply_now else maybe_call_n8n_policy_webhook(request["webhook_payload"])
    return {**request, "n8n": n8n, "applied": applied}


@app.get("/api/policy-assistant/audit")
def policy_assistant_audit(user: dict = Depends(require_roles("admin", "head"))):
    with connection() as db:
        items = rows(db.execute("SELECT * FROM policy_audit_logs ORDER BY created_at DESC LIMIT 100").fetchall())
        for item in items:
            item["before_state"] = json.loads(item["before_state"])
            item["after_state"] = json.loads(item["after_state"])
        return items


@app.get("/api/policy-assistant/requests")
def policy_assistant_requests(user: dict = Depends(require_roles("admin", "head"))):
    with connection() as db:
        items = rows(db.execute("SELECT * FROM policy_action_requests ORDER BY created_at DESC LIMIT 100").fetchall())
        for item in items:
            item["action_json"] = json.loads(item["action_json"])
            item["preview"] = json.loads(item["preview"])
        return items


@app.get("/api/governance-rules")
def governance_rules(user: dict = Depends(require_roles("admin", "head"))):
    with connection() as db:
        return list_governance_rules(db)


@app.get("/api/governance-rules/{rule_id}")
def governance_rule(rule_id: str, user: dict = Depends(require_roles("admin", "head"))):
    try:
        with connection() as db:
            return governance_rule_detail(db, rule_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/internal/policy/apply")
def internal_policy_apply(payload: InternalPolicyApplyInput, _: None = Depends(require_internal_policy_secret)):
    try:
        with transaction() as db:
            return apply_policy_action(db, payload.actor, payload.action, payload.request_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/internal/policy/rollback")
def internal_policy_rollback(payload: InternalPolicyRollbackInput, _: None = Depends(require_internal_policy_secret)):
    try:
        with transaction() as db:
            return rollback_policy_action(db, payload.actor, payload.audit_log_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/internal/policy/time-based-permissions/apply-due")
def internal_apply_due_time_based_permissions(_: None = Depends(require_internal_policy_secret)):
    with transaction() as db:
        return apply_due_time_based_permission_rules(db, "n8n")


@app.post("/internal/policy/time-based-permissions/{rule_id}/expire")
def internal_expire_time_based_permission(rule_id: str, _: None = Depends(require_internal_policy_secret)):
    try:
        with transaction() as db:
            return expire_time_based_permission_rule(db, "n8n", rule_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/internal/policy/tree")
def internal_policy_tree(_: None = Depends(require_internal_policy_secret)):
    with connection() as db:
        return master_tree(db)


@app.get("/internal/policy/audit")
def internal_policy_audit(_: None = Depends(require_internal_policy_secret)):
    with connection() as db:
        items = rows(db.execute("SELECT * FROM policy_audit_logs ORDER BY created_at DESC LIMIT 200").fetchall())
        for item in items:
            item["before_state"] = json.loads(item["before_state"])
            item["after_state"] = json.loads(item["after_state"])
        return items


@app.get("/api/admin/master-tree")
def admin_master_tree(user: dict = Depends(require_roles("admin", "head"))):
    with connection() as db:
        return master_tree(db)


@app.get("/api/master-folder-tree")
def api_master_folder_tree(user: dict = Depends(require_roles("admin", "head"))):
    with connection() as db:
        result = master_tree(db)
    return [result["tree"]] if result.get("tree") else []


@app.get("/master-tree")
def public_master_tree(user: dict = Depends(require_roles("admin", "head"))):
    with connection() as db:
        result = master_tree(db)
    return [result["tree"]] if result.get("tree") else []


@app.get("/api/specializations")
def api_specializations(user: dict = Depends(current_user)):
    with connection() as db:
        return public_specializations(db)


@app.get("/api/profile/specializations")
def get_profile_specializations(user: dict = Depends(current_user)):
    with connection() as db:
        return profile_specializations(db, user["code"])


@app.put("/api/profile/specializations")
def update_profile_specializations(payload: SpecializationSelection, user: dict = Depends(current_user)):
    if user["role"] in {"lecturer", "new_lecturer"}:
        raise HTTPException(403, "Chuyen mon cua giang vien duoc phan cong boi Admin/Truong bo mon. Ban khong the tu chon chuyen mon.")
    try:
        with transaction() as db:
            result = set_user_specializations(db, user, payload.specialization_ids)
            result["message"] = "Cay thu muc cua ban da duoc cap nhat theo policy hien hanh."
            return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/lecturer-assignments/import/preview")
async def preview_lecturer_assignments(request: Request, user: dict = Depends(require_roles("admin", "head"))):
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "File assignment rong.")
    filename = request.headers.get("X-Filename") or ("assignments.json" if "json" in request.headers.get("Content-Type", "") else "assignments.csv")
    mime_type = request.headers.get("Content-Type", "text/csv")
    try:
        with transaction() as db:
            return preview_lecturer_assignment_import(db, user, filename, raw, mime_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/lecturer-assignments/import/confirm")
def confirm_lecturer_assignments(payload: LecturerAssignmentConfirmInput, user: dict = Depends(require_roles("admin", "head"))):
    try:
        with transaction() as db:
            return confirm_lecturer_assignment_batch(db, user, payload.batch_preview_id, payload.apply_mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/lecturer-assignments")
def api_lecturer_assignments(status: str | None = None, user: dict = Depends(require_roles("admin", "head"))):
    with connection() as db:
        return {"items": list_lecturer_assignments(db, status=status)}


@app.get("/api/lecturer-assignments/batches/{batch_id}")
def api_lecturer_assignment_batch(batch_id: str, user: dict = Depends(require_roles("admin", "head"))):
    try:
        with connection() as db:
            return lecturer_assignment_batch_detail(db, batch_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/my-assignment")
def api_my_assignment(user: dict = Depends(current_user)):
    with connection() as db:
        return my_assignment(db, user)


@app.put("/api/profile/password")
def change_password(payload: PasswordChange, user: dict = Depends(current_user)):
    with transaction() as db:
        row = db.execute("SELECT password_hash FROM users WHERE code=?", (user["code"],)).fetchone()
        if not row or row["password_hash"] != hash_secret(payload.current_password):
            raise HTTPException(400, "Mật khẩu hiện tại không đúng.")
        db.execute("UPDATE users SET password_hash=? WHERE code=?", (hash_secret(payload.new_password), user["code"]))
        audit(db, user["code"], "user.password_change", "user", user["code"])
    return {"message": "Đổi mật khẩu thành công."}


@app.post("/api/profile/update-request")
def submit_profile_update(payload: ProfileUpdateInput, user: dict = Depends(current_user)):
    with transaction() as db:
        pending = db.execute(
            "SELECT id FROM profile_update_requests WHERE user_code=? AND status='pending'",
            (user["code"],)
        ).fetchone()
        if pending:
            raise HTTPException(400, "Bạn đã có một yêu cầu cập nhật đang chờ duyệt.")
        req_id = __import__("secrets").token_urlsafe(12)
        db.execute(
            "INSERT INTO profile_update_requests VALUES(?,?,?,?,?,?,?,NULL,NULL)",
            (req_id, user["code"], payload.new_name, payload.new_department, payload.reason, "pending", now()),
        )
        audit(db, user["code"], "user.profile_update_request", "user", user["code"])
    return {"id": req_id, "status": "pending"}


@app.get("/api/profile/update-requests")
def my_profile_update_requests(user: dict = Depends(current_user)):
    with connection() as db:
        return rows(db.execute(
            "SELECT * FROM profile_update_requests WHERE user_code=? ORDER BY created_at DESC LIMIT 5",
            (user["code"],)
        ).fetchall())


@app.get("/api/admin/profile-update-requests")
def list_profile_update_requests(user: dict = Depends(require_roles("admin"))):
    with connection() as db:
        return rows(db.execute(
            "SELECT r.*, u.name as current_name, u.department as current_department "
            "FROM profile_update_requests r JOIN users u ON u.code=r.user_code "
            "ORDER BY r.created_at DESC"
        ).fetchall())


@app.put("/api/admin/profile-update-requests/{req_id}/approve")
def approve_profile_update(req_id: str, user: dict = Depends(require_roles("admin"))):
    with transaction() as db:
        req = db.execute("SELECT * FROM profile_update_requests WHERE id=?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(404, "Yêu cầu không tồn tại.")
        if req["status"] != "pending":
            raise HTTPException(400, "Yêu cầu đã được xử lý.")
        db.execute("UPDATE users SET name=?, department=? WHERE code=?", (req["new_name"], req["new_department"], req["user_code"]))
        db.execute("UPDATE profile_update_requests SET status='approved',reviewed_at=?,reviewed_by=? WHERE id=?", (now(), user["code"], req_id))
        audit(db, user["code"], "user.profile_approved", "user", req["user_code"])
    return {"status": "approved"}


@app.put("/api/admin/profile-update-requests/{req_id}/reject")
def reject_profile_update(req_id: str, user: dict = Depends(require_roles("admin"))):
    with transaction() as db:
        req = db.execute("SELECT * FROM profile_update_requests WHERE id=?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(404, "Yêu cầu không tồn tại.")
        if req["status"] != "pending":
            raise HTTPException(400, "Yêu cầu đã được xử lý.")
        db.execute("UPDATE profile_update_requests SET status='rejected',reviewed_at=?,reviewed_by=? WHERE id=?", (now(), user["code"], req_id))
        audit(db, user["code"], "user.profile_rejected", "user", req["user_code"])
    return {"status": "rejected"}


@app.post("/api/lecturers/{lecturer_id}/specializations")
def update_lecturer_specializations(lecturer_id: str, payload: SpecializationSelection, user: dict = Depends(current_user)):
    if user["role"] in {"lecturer", "new_lecturer"}:
        raise HTTPException(403, "Chuyen mon cua giang vien duoc phan cong boi Admin/Truong bo mon. Ban khong the tu chon chuyen mon.")
    if user["code"] != lecturer_id and user["role"] not in {"admin", "head"}:
        raise HTTPException(403, "Ban khong co quyen cap nhat nhom chuyen mon cua nguoi dung nay.")
    try:
        with transaction() as db:
            target = db.execute("SELECT * FROM users WHERE code=? AND active=1", (lecturer_id,)).fetchone()
            if not target:
                raise HTTPException(404, "Khong tim thay giang vien.")
            result = set_user_specializations(db, dict(target), payload.specialization_ids)
            result["folder_tree"] = build_lecturer_folder_tree(db, lecturer_id)
            result["message"] = "Cay thu muc ca nhan da duoc tao tu chuyen mon da chon."
            return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/my-folder-tree")
def my_folder_tree(user: dict = Depends(current_user)):
    with connection() as db:
        return get_my_folder_tree(db, user)


@app.get("/api/lecturers/{lecturer_id}/folder-tree")
def lecturer_folder_tree(lecturer_id: str, user: dict = Depends(current_user)):
    if user["code"] != lecturer_id and user["role"] not in {"admin", "head"}:
        raise HTTPException(403, "Ban khong co quyen xem cay thu muc cua nguoi dung nay.")
    with connection() as db:
        target = db.execute("SELECT * FROM users WHERE code=? AND active=1", (lecturer_id,)).fetchone()
        if not target:
            raise HTTPException(404, "Khong tim thay giang vien.")
        tree = build_lecturer_folder_tree(db, lecturer_id)
    return [tree]


@app.get("/virtual-tree/{user_id}")
def virtual_tree(user_id: str, user: dict = Depends(current_user)):
    if user["code"] != user_id and user["role"] not in {"admin", "head"}:
        raise HTTPException(403, "Ban khong co quyen xem cay thu muc cua nguoi dung nay.")
    with connection() as db:
        target = db.execute("SELECT * FROM users WHERE code=? AND active=1", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "Khong tim thay nguoi dung.")
        result = get_my_folder_tree(db, dict(target))
    return result["children"]


@app.get("/api/rag/pipeline")
def rag_pipeline(user: dict = Depends(current_user)):
    with connection() as db:
        documents = db.execute(
            "SELECT COUNT(*) count FROM documents WHERE deleted_at IS NULL AND status='INDEXED' AND (visibility='public' OR owner_code=?)",
            (user["code"],),
        ).fetchone()["count"]
        chunks = db.execute(
            "SELECT COUNT(*) count FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.deleted_at IS NULL AND d.status='INDEXED' AND (d.visibility='public' OR d.owner_code=?)",
            (user["code"],),
        ).fetchone()["count"]
    vector_store = infrastructure_status()["services"]["vector_store"]
    return {
        "scope": "public_or_owned",
        "documents": documents,
        "chunks": chunks,
        "qdrant": {
            **vector_store,
            "last_reindex": qdrant_reindex_status(),
        },
        "stages": [
            {"name": "upload", "status": "ready"},
            {"name": "parse_pdf_docx_ocr", "status": "ready"},
            {"name": "chunk", "status": "ready"},
            {"name": "embedding", "status": "ready", "provider": ai_provider.status()["embedding_model"]},
            {"name": "vector_store", "status": "ready", "provider": "sqlite_chunks", "qdrant": vector_store},
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
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


def upload_task_public(task) -> dict:
    item = dict(task)
    item["metadata"] = json.loads(item["metadata"])
    item.pop("temp_path", None)
    return item


def classification_ticket_public(ticket) -> dict:
    item = dict(ticket)
    if isinstance(item.get("suggestions"), str):
        item["suggestions"] = json.loads(item["suggestions"])
    return item


def build_classification_ticket_preview(db, filename: str, preview: str, metadata: dict, *, ticket_id: str | None = None) -> dict:
    suggestions = active_course_suggestions(db, filename, preview, metadata)
    top = suggestions[0] if suggestions else {}
    text = f"{filename} {preview}".casefold()
    suggested_type = metadata.get("doc_type") if metadata.get("doc_type") in DOCUMENT_TYPES else "Tài liệu khác"
    for candidate in DOCUMENT_TYPES:
        if candidate.casefold() in text or candidate.replace(" ", "_").casefold() in text:
            suggested_type = candidate
            break
    confidence = float(top.get("confidence") or 0)
    reasoning = (
        f"AI đọc nhanh tên file và 1-2 trang đầu. Gợi ý học phần '{top.get('course', '')}' "
        f"vì nội dung/tên file có độ khớp {round(confidence * 100)}%."
        if top else
        "AI đọc nhanh tên file và 1-2 trang đầu nhưng chưa tìm thấy học phần khớp đủ rõ trong Master Tree."
    )
    return {
        "id": ticket_id or f"preview-{secrets.token_hex(8)}",
        "filename": filename,
        "suggested_specialization_id": top.get("specialization_id"),
        "suggested_specialization": top.get("specialization"),
        "suggested_course_id": top.get("course_id"),
        "suggested_course": top.get("course"),
        "suggested_document_type": suggested_type,
        "suggested_visibility": metadata.get("visibility", "private"),
        "confidence": confidence,
        "reasoning": reasoning,
        "suggestions": suggestions,
        "selected_specialization_id": top.get("specialization_id"),
        "selected_course_id": top.get("course_id"),
        "selected_document_type": suggested_type,
        "selected_visibility": metadata.get("visibility", "private"),
        "status": "PENDING_CONFIRMATION",
        "document_id": None,
    }


def create_classification_ticket(db, task, user: dict) -> dict:
    existing = db.execute(
        "SELECT * FROM document_classification_tickets WHERE upload_task_id=? ORDER BY created_at DESC LIMIT 1",
        (task["id"],),
    ).fetchone()
    if existing and existing["status"] in {"PENDING_CONFIRMATION", "CONFIRMED"}:
        return classification_ticket_public(existing)
    raw = __import__("pathlib").Path(task["temp_path"]).read_bytes()
    preview = quick_preview_text(task["filename"], task["mime_type"], raw)
    metadata = json.loads(task["metadata"])
    preview_ticket = build_classification_ticket_preview(db, task["filename"], preview, metadata, ticket_id=f"ticket-{secrets.token_hex(8)}")
    timestamp = now()
    db.execute(
        """INSERT INTO document_classification_tickets(
           id,upload_task_id,user_code,filename,suggested_specialization_id,suggested_specialization,
           suggested_course_id,suggested_course,suggested_document_type,suggested_visibility,confidence,
           reasoning,suggestions,selected_specialization_id,selected_course_id,selected_document_type,
           selected_visibility,status,document_id,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING_CONFIRMATION', NULL, ?, ?)""",
        (
            preview_ticket["id"], task["id"], user["code"], task["filename"],
            preview_ticket.get("suggested_specialization_id"), preview_ticket.get("suggested_specialization"),
            preview_ticket.get("suggested_course_id"), preview_ticket.get("suggested_course"),
            preview_ticket.get("suggested_document_type"), preview_ticket.get("suggested_visibility"),
            preview_ticket.get("confidence"), preview_ticket.get("reasoning"),
            json.dumps(preview_ticket.get("suggestions") or [], ensure_ascii=False),
            preview_ticket.get("selected_specialization_id"), preview_ticket.get("selected_course_id"),
            preview_ticket.get("selected_document_type"), preview_ticket.get("selected_visibility"), timestamp, timestamp,
        ),
    )
    ticket = classification_ticket_public(db.execute("SELECT * FROM document_classification_tickets WHERE id=?", (preview_ticket["id"],)).fetchone())
    task_metadata = {**metadata, "classification_ticket": ticket}
    db.execute(
        "UPDATE upload_tasks SET status='pending_confirmation',metadata=?,error=NULL,updated_at=? WHERE id=?",
        (json.dumps(task_metadata, ensure_ascii=False), timestamp, task["id"]),
    )
    audit(db, user["code"], "upload.classification_ticket", "upload_task", task["id"], {"ticket_id": preview_ticket["id"], "confidence": preview_ticket["confidence"]})
    return ticket


def process_upload_task(task_id: str) -> None:
    try:
        with transaction() as db:
            task = db.execute("SELECT * FROM upload_tasks WHERE id=?", (task_id,)).fetchone()
            if not task or task["uploaded_bytes"] != task["total_bytes"]:
                raise ValueError("File chưa được tải lên đầy đủ.")
            db.execute(
                "UPDATE upload_tasks SET status='analyzing',error=NULL,updated_at=? WHERE id=?",
                (now(), task_id),
            )
        raw = __import__("pathlib").Path(task["temp_path"]).read_bytes()
        content = extract_text(task["filename"], task["mime_type"], raw)
        if meaningful_text_score(content) < 12:
            content = extraction_placeholder(task["filename"], content)
        with connection() as db:
            prompt_row = db.execute("SELECT value FROM policies WHERE key='ai_prompts'").fetchone()
            prompts = json.loads(prompt_row["value"]) if prompt_row else {}
        ai_metadata = guess_metadata(task["filename"], content, prompts.get("metadata_instructions"))
        with transaction() as db:
            task = db.execute("SELECT * FROM upload_tasks WHERE id=?", (task_id,)).fetchone()
            user = db.execute("SELECT * FROM users WHERE code=?", (task["user_code"],)).fetchone()
            metadata = json.loads(task["metadata"])
            existing_id = metadata.get("existing_document_id")
            applied_metadata = {
                "title": metadata["title"] if existing_id else ai_metadata["title"],
                "topic": ai_metadata["topic"],
                "doc_type": ai_metadata["doc_type"],
                "visibility": metadata["visibility"],
            }
            folder_path = metadata.get("folder_path") or suggest_folder(db, dict(user), applied_metadata)
            task_metadata = {
                **metadata,
                "ai_metadata": ai_metadata,
                "applied_metadata": {**applied_metadata, "folder_path": folder_path},
            }
            db.execute(
                "UPDATE upload_tasks SET status='saving_metadata',metadata=?,updated_at=? WHERE id=?",
                (json.dumps(task_metadata, ensure_ascii=False), now(), task_id),
            )
            payload = {
                **applied_metadata,
                "folder_path": folder_path,
                "folder_node_id": metadata.get("folder_node_id"),
                "content": content,
            }
            if existing_id:
                document = update_document(db, dict(user), get_active_document(db, existing_id), payload, defer_processing=True)
                version_no = document["current_version"]
            else:
                document = create_document(db, dict(user), payload, defer_processing=True)
                version_no = 1
            asset = save_file_asset(db, document["id"], version_no, task["filename"], task["mime_type"], raw, defer_processing=True)
            version = db.execute(
                "SELECT storage_path FROM versions WHERE document_id=? AND version_no=?",
                (document["id"], version_no),
            ).fetchone()

        with transaction() as db:
            index_document(db, document["id"], version_no, content, force_local=True)
            sync_document(db, document["id"], __import__("pathlib").Path(version["storage_path"]))
            audit(db, task["user_code"], "upload.completed", "document", document["id"], {"task_id": task_id})
            db.execute(
                "UPDATE upload_tasks SET status='completed',document_id=?,error=NULL,updated_at=? WHERE id=?",
                (document["id"], now(), task_id),
            )
        with transaction() as db:
            sync_user_document(db, task["user_code"], document["id"], __import__("pathlib").Path(asset["original_path"]))
    except Exception as exc:
        with transaction() as db:
            db.execute(
                "UPDATE upload_tasks SET status='failed',error=?,updated_at=? WHERE id=?",
                (str(exc), now(), task_id),
            )


def process_document_background(document_id: str, task_id: str | None = None) -> None:
    try:
        with transaction() as db:
            document = run_document_processing_jobs(db, document_id)
            if task_id:
                db.execute(
                    "UPDATE upload_tasks SET status='completed',document_id=?,error=NULL,updated_at=? WHERE id=?",
                    (document_id, now(), task_id),
                )
            version = db.execute(
                "SELECT storage_path FROM versions WHERE document_id=? AND version_no=?",
                (document_id, document["current_version"]),
            ).fetchone()
            if version:
                sync_document(db, document_id, __import__("pathlib").Path(version["storage_path"]))
            asset = db.execute(
                "SELECT original_path FROM file_assets WHERE document_id=? AND version_no=? ORDER BY created_at DESC LIMIT 1",
                (document_id, document["current_version"]),
            ).fetchone()
            if asset:
                sync_user_document(db, document["owner_code"], document_id, __import__("pathlib").Path(asset["original_path"]))
    except Exception as exc:
        with transaction() as db:
            if task_id:
                db.execute("UPDATE upload_tasks SET status='failed',error=?,updated_at=? WHERE id=?", (str(exc), now(), task_id))


def save_upload_task_fast(task_id: str) -> str:
    with transaction() as db:
        task = db.execute("SELECT * FROM upload_tasks WHERE id=?", (task_id,)).fetchone()
        if not task or task["uploaded_bytes"] != task["total_bytes"]:
            raise ValueError("File chưa được tải lên đầy đủ.")
        if task["document_id"]:
            return task["document_id"]
        raw = __import__("pathlib").Path(task["temp_path"]).read_bytes()
        preview = quick_preview_text(task["filename"], task["mime_type"], raw)
        user = db.execute("SELECT * FROM users WHERE code=?", (task["user_code"],)).fetchone()
        metadata = json.loads(task["metadata"])
        suggestion = suggest_upload_destination(db, dict(user), task["filename"], preview)
        ai_metadata = guess_metadata(task["filename"], preview)
        doc_type = metadata["doc_type"] if metadata.get("doc_type") in DOCUMENT_TYPES else "Tài liệu khác"
        applied_metadata = {
            "title": metadata["title"],
            "topic": suggestion.get("course") or suggestion.get("specialization") or ai_metadata.get("topic") or metadata.get("topic") or "Chưa phân loại",
            "doc_type": doc_type,
            "visibility": metadata["visibility"],
        }
        folder_path = metadata.get("folder_path") or suggestion.get("folder_path") or suggest_folder(db, dict(user), applied_metadata)
        task_metadata = {
            **metadata,
            "quick_suggestion": suggestion,
            "ai_metadata": ai_metadata,
            "applied_metadata": {**applied_metadata, "folder_path": folder_path},
        }
        db.execute(
            "UPDATE upload_tasks SET status='saving_metadata',metadata=?,updated_at=? WHERE id=?",
            (json.dumps(task_metadata, ensure_ascii=False), now(), task_id),
        )
        payload = {
            **applied_metadata,
            "folder_path": folder_path,
            "folder_node_id": metadata.get("folder_node_id"),
            "content": f"File: {task['filename']}\nStatus: UPLOADED. AI processing is running asynchronously.\n\n{preview[:4000]}",
        }
        existing_id = metadata.get("existing_document_id")
        if existing_id:
            document = update_document(db, dict(user), get_active_document(db, existing_id), payload, defer_processing=True)
            version_no = document["current_version"]
        else:
            document = create_document(db, dict(user), payload, defer_processing=True)
            version_no = 1
        asset = save_file_asset(db, document["id"], version_no, task["filename"], task["mime_type"], raw, defer_processing=True)
        enqueue_processing_jobs(db, document["id"])
        db.execute("UPDATE documents SET status='PROCESSING',updated_at=? WHERE id=?", (now(), document["id"]))
        set_v2_state(db, document["id"], indexing_status="processing")
        audit(db, task["user_code"], "upload.saved_fast", "document", document["id"], {"task_id": task_id, "asset_id": asset["id"]})
        db.execute(
            "UPDATE upload_tasks SET status='completed',document_id=?,error=NULL,updated_at=? WHERE id=?",
            (document["id"], now(), task_id),
        )
        return document["id"]


@app.post("/api/uploads/init", status_code=201)
def init_upload(payload: UploadInitInput, user: dict = Depends(current_user)):
    if payload.total_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File vượt quá giới hạn tải lên {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
    if payload.existing_document_id:
        with connection() as db:
            document = get_active_document(db, payload.existing_document_id)
            if document["owner_code"] != user["code"]:
                raise HTTPException(403, "Bạn không có quyền cập nhật tài liệu này.")
            try:
                validate_folder_access(db, user, payload.folder_node_id or document.get("folder_node_id"))
            except PermissionError as exc:
                raise HTTPException(403, str(exc))
    elif payload.folder_node_id:
        with connection() as db:
            try:
                validate_folder_access(db, user, payload.folder_node_id)
            except PermissionError as exc:
                raise HTTPException(403, str(exc))
    task_id = f"upload-{secrets.token_hex(8)}"
    upload_dir = DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"{task_id}.part"
    temp_path.write_bytes(b"")
    timestamp = now()
    metadata = payload.model_dump(exclude={"filename", "mime_type", "total_bytes"})
    with transaction() as db:
        db.execute(
            """INSERT INTO upload_tasks(id,user_code,filename,mime_type,total_bytes,uploaded_bytes,status,metadata,temp_path,document_id,error,created_at,updated_at)
               VALUES(?,?,?,?,?,0,'uploading',?,?,NULL,NULL,?,?)""",
            (
                task_id, user["code"], payload.filename, payload.mime_type, payload.total_bytes,
                json.dumps(metadata, ensure_ascii=False), str(temp_path), timestamp, timestamp,
            ),
        )
        audit(db, user["code"], "upload.started", "upload_task", task_id, {"filename": payload.filename, "size": payload.total_bytes})
        return upload_task_public(db.execute("SELECT * FROM upload_tasks WHERE id=?", (task_id,)).fetchone())


@app.post("/api/uploads/{task_id}/file")
async def upload_chunk(
    task_id: str,
    request: Request,
    x_upload_offset: int = Header(),
    user: dict = Depends(current_user),
):
    chunk = await request.body()
    if not chunk:
        raise HTTPException(400, "Chunk tải lên đang trống.")
    with transaction() as db:
        task = db.execute("SELECT * FROM upload_tasks WHERE id=? AND user_code=?", (task_id, user["code"])).fetchone()
        if not task:
            raise HTTPException(404, "Không tìm thấy tác vụ tải lên.")
        if task["status"] not in {"uploading", "failed"}:
            raise HTTPException(409, "Tác vụ không còn nhận dữ liệu tải lên.")
        if x_upload_offset != task["uploaded_bytes"]:
            raise HTTPException(409, f"Offset không hợp lệ. Máy chủ đang có {task['uploaded_bytes']} byte.")
        uploaded_bytes = x_upload_offset + len(chunk)
        if uploaded_bytes > task["total_bytes"]:
            raise HTTPException(413, "Dữ liệu tải lên vượt quá dung lượng đã khai báo.")
        path = __import__("pathlib").Path(task["temp_path"])
        with path.open("r+b") as output:
            output.seek(x_upload_offset)
            output.write(chunk)
        status = "uploaded" if uploaded_bytes == task["total_bytes"] else "uploading"
        db.execute(
            "UPDATE upload_tasks SET uploaded_bytes=?,status=?,error=NULL,updated_at=? WHERE id=?",
            (uploaded_bytes, status, now(), task_id),
        )
        return upload_task_public(db.execute("SELECT * FROM upload_tasks WHERE id=?", (task_id,)).fetchone())


@app.post("/api/uploads/{task_id}/analyze", status_code=202)
def analyze_upload(task_id: str, user: dict = Depends(current_user)):
    with transaction() as db:
        task = db.execute("SELECT * FROM upload_tasks WHERE id=? AND user_code=?", (task_id, user["code"])).fetchone()
        if not task:
            raise HTTPException(404, "Khong tim thay tac vu tai len.")
        if task["uploaded_bytes"] != task["total_bytes"]:
            raise HTTPException(409, "File chua duoc tai len day du.")
        if task["status"] in {"completed", "processing"}:
            return upload_task_public(task)
        create_classification_ticket(db, task, dict(user))
        result = upload_task_public(db.execute("SELECT * FROM upload_tasks WHERE id=?", (task_id,)).fetchone())
    return result


@app.post("/api/uploads/{task_id}/confirm", status_code=201)
def confirm_upload(task_id: str, payload: UploadConfirmInput, background_tasks: BackgroundTasks, user: dict = Depends(current_user)):
    with transaction() as db:
        task = db.execute("SELECT * FROM upload_tasks WHERE id=? AND user_code=?", (task_id, user["code"])).fetchone()
        if not task:
            raise HTTPException(404, "Khong tim thay tac vu tai len.")
        if task["uploaded_bytes"] != task["total_bytes"]:
            raise HTTPException(409, "File chua duoc tai len day du.")
        ticket = db.execute(
            "SELECT * FROM document_classification_tickets WHERE upload_task_id=? AND user_code=? ORDER BY created_at DESC LIMIT 1",
            (task_id, user["code"]),
        ).fetchone()
        if not ticket:
            ticket = create_classification_ticket(db, task, dict(user))
            ticket = db.execute("SELECT * FROM document_classification_tickets WHERE id=?", (ticket["id"],)).fetchone()
        if ticket["status"] == "CONFIRMED" and ticket["document_id"]:
            return {"ticket": classification_ticket_public(ticket), "document": dict(db.execute("SELECT * FROM documents WHERE id=?", (ticket["document_id"],)).fetchone())}

        metadata = json.loads(task["metadata"])
        final_specialization_id = payload.specialization_id
        final_course_id = payload.course_id
        final_document_type = payload.document_type
        selected_node = validate_folder_access(db, user, payload.folder_node_id) if payload.folder_node_id else None
        if selected_node and selected_node["type"] in {"faculty", "specialization", "course"}:
            raise HTTPException(400, "Document must be saved inside a document-type folder.")
        if selected_node and selected_node["type"] == "standard_folder":
            final_document_type = selected_node["name"]
            final_course_id = selected_node["parent_id"]
        selected_document_folder = bool(selected_node and selected_node["type"] in {"standard_folder", "folder", "document_type_folder"})
        if final_document_type not in DOCUMENT_TYPES and not selected_document_folder:
            raise HTTPException(422, "Loai tai lieu khong hop le.")
        selected_course = db.execute("SELECT * FROM folder_nodes WHERE id=? AND type='course' AND status='active'", (final_course_id,)).fetchone() if final_course_id else None
        if selected_course:
            spec_node = db.execute("SELECT * FROM folder_nodes WHERE id=? AND type='specialization' AND status='active'", (selected_course["parent_id"],)).fetchone()
            specialization = db.execute("SELECT * FROM specializations WHERE folder_node_id=?", (spec_node["id"],)).fetchone() if spec_node else None
            final_specialization_id = specialization["id"] if specialization else final_specialization_id
        assignment = folder_assignment_from_metadata(db, final_specialization_id, final_course_id, final_document_type)
        if final_course_id and not assignment["folder_node_id"]:
            raise HTTPException(400, "Hay chon hoc phan hop le de luu tai lieu vao thu muc loai tai lieu.")
        if not assignment["folder_node_id"] and payload.folder_path:
            assignment["folder_path"] = payload.folder_path
        destination_node = db.execute("SELECT * FROM folder_nodes WHERE id=? AND status='active'", (assignment["folder_node_id"],)).fetchone() if assignment["folder_node_id"] else None
        if destination_node and destination_node["type"] in {"faculty", "specialization", "course"}:
            raise HTTPException(400, "Document must be saved inside a document-type folder.")
        print(json.dumps({
            "document_title": metadata.get("title") or __import__("pathlib").Path(task["filename"]).stem,
            "course_id": final_course_id,
            "document_type": final_document_type,
            "resolved_destination_folder_id": assignment["folder_node_id"],
            "resolved_destination_folder_name": destination_node["name"] if destination_node else None,
            "resolved_destination_folder_type": destination_node["type"] if destination_node else None,
            "final_destination_source": payload.final_destination_source,
        }, ensure_ascii=True))
        title = metadata.get("title") or __import__("pathlib").Path(task["filename"]).stem
        topic = selected_course["name"] if selected_course else metadata.get("topic") or final_document_type
        raw = __import__("pathlib").Path(task["temp_path"]).read_bytes()
        preview = quick_preview_text(task["filename"], task["mime_type"], raw)
        document_payload = {
            "title": title,
            "topic": topic,
            "doc_type": final_document_type,
            "document_type": final_document_type,
            "visibility": payload.visibility,
            "folder_path": assignment["folder_path"],
            "folder_node_id": assignment["folder_node_id"],
            "specialization_id": final_specialization_id,
            "course_id": final_course_id,
            "content": f"File: {task['filename']}\nStatus: SAVED. AI processing is waiting in background.\n\n{preview[:4000]}",
        }
        existing_id = metadata.get("existing_document_id")
        if existing_id:
            document = update_document(db, dict(user), get_active_document(db, existing_id), document_payload, defer_processing=True)
            version_no = document["current_version"]
        else:
            document = create_document(db, dict(user), document_payload, defer_processing=True)
            version_no = 1
        asset = save_file_asset(db, document["id"], version_no, task["filename"], task["mime_type"], raw, defer_processing=True)
        enqueue_processing_jobs(db, document["id"])
        db.execute(
            "UPDATE documents SET status='SAVED',specialization_id=?,course_id=?,document_type=?,folder_node_id=?,folder_path=?,updated_at=? WHERE id=?",
            (final_specialization_id, final_course_id, final_document_type, assignment["folder_node_id"], assignment["folder_path"], now(), document["id"]),
        )
        db.execute(
            "UPDATE document_classification_tickets SET selected_specialization_id=?,selected_course_id=?,selected_document_type=?,selected_visibility=?,status='CONFIRMED',document_id=?,updated_at=? WHERE id=?",
            (final_specialization_id, final_course_id, final_document_type, payload.visibility, document["id"], now(), ticket["id"]),
        )
        db.execute(
            "UPDATE upload_tasks SET status='processing',document_id=?,error=NULL,updated_at=? WHERE id=?",
            (document["id"], now(), task_id),
        )
        audit(db, user["code"], "upload.confirmed", "document", document["id"], {"ticket_id": ticket["id"], "asset_id": asset["id"]})
        document = dict(db.execute("SELECT * FROM documents WHERE id=?", (document["id"],)).fetchone())
        ticket_public = classification_ticket_public(db.execute("SELECT * FROM document_classification_tickets WHERE id=?", (ticket["id"],)).fetchone())
    background_tasks.add_task(process_document_background, document["id"], task_id)
    return {"ticket": ticket_public, "document": document, "asset": asset}


@app.get("/api/uploads")
def upload_tasks(user: dict = Depends(current_user)):
    with connection() as db:
        return [
            upload_task_public(task)
            for task in db.execute(
                "SELECT * FROM upload_tasks WHERE user_code=? ORDER BY created_at DESC LIMIT 20",
                (user["code"],),
            ).fetchall()
        ]


@app.get("/api/uploads/{task_id}")
def upload_status(task_id: str, user: dict = Depends(current_user)):
    with connection() as db:
        task = db.execute("SELECT * FROM upload_tasks WHERE id=? AND user_code=?", (task_id, user["code"])).fetchone()
        if not task:
            raise HTTPException(404, "Không tìm thấy tác vụ tải lên.")
        return upload_task_public(task)


@app.delete("/api/uploads/{task_id}")
def delete_upload_task(task_id: str, user: dict = Depends(current_user)):
    with transaction() as db:
        task = db.execute("SELECT * FROM upload_tasks WHERE id=? AND user_code=?", (task_id, user["code"])).fetchone()
        if not task:
            raise HTTPException(404, "Không tìm thấy tác vụ tải lên.")
        if task["status"] in {"processing", "saving_metadata"}:
            raise HTTPException(409, "Không thể xóa tác vụ đang xử lý.")
        temp_path = __import__("pathlib").Path(task["temp_path"])
        db.execute("DELETE FROM document_classification_tickets WHERE upload_task_id=?", (task_id,))
        db.execute("DELETE FROM upload_tasks WHERE id=?", (task_id,))
        action = "upload.removed" if task["document_id"] else "upload.cancelled"
        audit(db, user["code"], action, "upload_task", task_id, {"filename": task["filename"], "status": task["status"]})
    if temp_path.exists():
        temp_path.unlink()
    return {"status": "deleted" if task["document_id"] else "cancelled", "id": task_id}


@app.post("/api/documents/upload", status_code=201)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    x_filename: str = Header(),
    x_title: str = Header(default=""),
    x_topic: str = Header(default=""),
    x_doc_type: str = Header(default=""),
    x_visibility: Literal["public", "private"] = Header(),
    x_folder_path: str = Header(default=""),
    x_folder_node_id: str = Header(default=""),
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
    doc_type = unquote(x_doc_type)
    if doc_type not in DOCUMENT_TYPES:
        doc_type = "Tài liệu khác"
    payload = {
        "title": unquote(x_title), "topic": unquote(x_topic), "doc_type": doc_type,
        "visibility": x_visibility, "content": quick_preview_text(filename, mime_type, raw) or f"File: {filename}\nStatus: UPLOADED. AI processing is running asynchronously.",
        "folder_path": unquote(x_folder_path) or None, "folder_node_id": x_folder_node_id or None,
    }
    try:
        with transaction() as db:
            payload = metadata_payload_for_upload(
                db, user, filename, mime_type, raw,
                title=unquote(x_title), topic=unquote(x_topic), doc_type=unquote(x_doc_type),
                visibility=x_visibility, folder_path=unquote(x_folder_path), folder_node_id=x_folder_node_id,
            )
            suggestion = suggest_upload_destination(db, dict(user), filename, payload["content"])
            payload["folder_path"] = payload["folder_path"] or suggestion.get("folder_path") or suggest_folder(db, dict(user), payload)
            document = create_document(db, user, payload, defer_processing=True)
            asset = save_file_asset(db, document["id"], 1, filename, mime_type, raw, defer_processing=True)
            enqueue_processing_jobs(db, document["id"])
            db.execute("UPDATE documents SET status='PROCESSING',updated_at=? WHERE id=?", (now(), document["id"]))
            set_v2_state(db, document["id"], indexing_status="processing")
            sync_user_document(db, user["code"], document["id"], __import__("pathlib").Path(asset["original_path"]))
            audit(db, user["code"], "file.upload", "document", document["id"], {"filename": filename, "size": len(raw)})
            document = dict(db.execute("SELECT * FROM documents WHERE id=?", (document["id"],)).fetchone())
        background_tasks.add_task(process_document_background, document["id"], None)
        return {"document": document, "asset": asset}
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.put("/api/documents/{document_id}/upload")
async def upload_new_version(
    document_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_filename: str = Header(),
    x_title: str = Header(default=""),
    x_topic: str = Header(default=""),
    x_doc_type: str = Header(default=""),
    x_visibility: Literal["public", "private"] = Header(),
    x_folder_path: str = Header(default=""),
    x_folder_node_id: str = Header(default=""),
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
    doc_type = unquote(x_doc_type)
    if doc_type not in DOCUMENT_TYPES:
        doc_type = "Tài liệu khác"
    payload = {
        "title": unquote(x_title), "topic": unquote(x_topic), "doc_type": doc_type,
        "visibility": x_visibility, "content": quick_preview_text(filename, mime_type, raw) or f"File: {filename}\nStatus: UPLOADED. AI processing is running asynchronously.",
        "folder_path": unquote(x_folder_path) or None, "folder_node_id": x_folder_node_id or None,
    }
    try:
        with transaction() as db:
            payload = metadata_payload_for_upload(
                db, user, filename, mime_type, raw,
                title=unquote(x_title), topic=unquote(x_topic), doc_type=unquote(x_doc_type),
                visibility=x_visibility, folder_path=unquote(x_folder_path), folder_node_id=x_folder_node_id,
            )
            suggestion = suggest_upload_destination(db, dict(user), filename, payload["content"])
            payload["folder_path"] = payload["folder_path"] or suggestion.get("folder_path") or suggest_folder(db, dict(user), payload)
            document = update_document(db, user, get_document(db, document_id), payload, defer_processing=True)
            asset = save_file_asset(db, document_id, document["current_version"], filename, mime_type, raw, defer_processing=True)
            enqueue_processing_jobs(db, document_id)
            db.execute("UPDATE documents SET status='PROCESSING',updated_at=? WHERE id=?", (now(), document_id))
            set_v2_state(db, document_id, indexing_status="processing")
            sync_user_document(db, user["code"], document_id, __import__("pathlib").Path(asset["original_path"]))
            audit(db, user["code"], "file.upload_version", "document", document_id, {"filename": filename})
            document = dict(db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())
        background_tasks.add_task(process_document_background, document_id, None)
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
        return ask(db, user, payload.question, payload.filters)


@app.post("/api/search/stream")
def search_stream(payload: Question, user: dict = Depends(current_user)):
    def event_stream():
        yield json.dumps({"type": "status", "message": "Đang tìm trong kho tri thức..."}, ensure_ascii=False) + "\n"
        try:
            with transaction() as db:
                result = ask(db, user, payload.question, payload.filters)
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
            return

        yield json.dumps({"type": "status", "message": "Đang soạn câu trả lời..."}, ensure_ascii=False) + "\n"
        for chunk in re.findall(r"\S+\s*", result["answer"]):
            yield json.dumps({"type": "delta", "text": chunk}, ensure_ascii=False) + "\n"
        yield json.dumps(
            {
                "type": "complete",
                "citations": result["citations"],
                "scope": result["scope"],
                "pipeline": result.get("pipeline", []),
                "trace_id": result.get("trace_id"),
                "intent": result.get("intent"),
                "rewritten_query": result.get("rewritten_query"),
                "verification": result.get("verification"),
            },
            ensure_ascii=False,
        ) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/search/feedback", status_code=201)
def search_feedback(payload: SearchFeedbackInput, user: dict = Depends(current_user)):
    feedback_id = f"fb-{secrets.token_hex(6)}"
    with transaction() as db:
        db.execute(
            "INSERT INTO search_feedback(id,trace_id,user_code,rating,reason,detail,created_at) VALUES(?,?,?,?,?,?,?)",
            (feedback_id, payload.trace_id, user["code"], payload.rating, payload.reason, payload.detail, now()),
        )
        audit(db, user["code"], "rag.feedback", "query", payload.trace_id, {
            "feedback_id": feedback_id,
            "rating": payload.rating,
            "reason": payload.reason,
        })
    return {"id": feedback_id, "status": "received"}


@app.get("/api/search/global")
def search_global(q: str = "", user: dict = Depends(current_user)):
    with connection() as db:
        return global_knowledge_search(db, user, q)


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


@app.get("/api/knowledge-transfer/insights")
def knowledge_transfer_insight_summary(user: dict = Depends(require_roles("head", "admin"))):
    with connection() as db:
        return knowledge_transfer_insights(db)


@app.get("/api/knowledge-transfer/actions")
def knowledge_transfer_recommended_actions(user: dict = Depends(require_roles("head", "admin"))):
    with connection() as db:
        return knowledge_transfer_actions(db)


@app.get("/api/knowledge-transfer/insights/specializations")
def knowledge_transfer_insight_specializations(user: dict = Depends(require_roles("head", "admin"))):
    with connection() as db:
        return knowledge_transfer_specialization_insights(db)


@app.get("/api/knowledge-transfer/insights/course-gaps")
def knowledge_transfer_insight_course_gaps(user: dict = Depends(require_roles("head", "admin"))):
    with connection() as db:
        return knowledge_transfer_course_gaps(db)


@app.get("/api/knowledge-transfer/insights/lecturer-dependency")
def knowledge_transfer_insight_lecturer_dependency(user: dict = Depends(require_roles("head", "admin"))):
    with connection() as db:
        return knowledge_transfer_lecturer_dependency(db)


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


@app.get("/api/audit-logs")
def audit_logs(
    actor: str = Query(default=""),
    action: str = Query(default=""),
    resource_type: str = Query(default=""),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(require_roles("admin")),
):
    with connection() as db:
        return list_audit_logs(
            db,
            actor=actor,
            action=action,
            resource_type=resource_type,
            query=q,
            page=page,
            page_size=page_size,
        )


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
            db.execute(
                """INSERT INTO access_requests(id,document_id,requester_code,owner_code,status,created_at,resolved_at)
                   VALUES(?,?,?,?, 'pending', ?, NULL)""",
                (request_id, document_id, user["code"], document["owner_code"], now()),
            )
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

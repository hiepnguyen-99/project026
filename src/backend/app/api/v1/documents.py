import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user
from ...core.permissions import can_access_document
from ...db.session import get_db
from ...models.document import DocStatus, Document, Version, Visibility
from ...models.user import User, UserRole
from ...schemas.document import ConfirmRequest, DownloadResponse, UploadResponse
from ...services.dedup import compute_hash, find_duplicate
from ...services.storage import Storage, get_storage
from ...workers.celery_app import ingest_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def _enqueue_ingest(document_id: str) -> None:
    try:
        ingest_document.delay(document_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Không enqueue được ingest_document: %s", exc)


async def _owned_or_admin(db: AsyncSession, document_id: uuid.UUID, user: User) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")
    if doc.owner_code != user.code and user.role != UserRole.quan_tri:
        raise HTTPException(status_code=403, detail="Chỉ chủ tài liệu hoặc quản trị")
    return doc


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
    file: Annotated[UploadFile, File(...)],
    replace_document_id: Annotated[str | None, Form()] = None,
):
    """Upload tài liệu: lưu MinIO, tính SHA-256, tạo Document, enqueue ingest.

    - Trùng hash (upload mới) → trả cảnh báo duplicate, KHÔNG lưu trùng.
    - `replace_document_id` → tạo Version mới cho tài liệu đã có (versioning).
    """
    data = await file.read()
    content_hash = compute_hash(data)
    filename = file.filename or "untitled"
    object_name = f"{content_hash}/{filename}"

    # --- Versioning: upload đè tài liệu đã có ---
    if replace_document_id:
        doc = await _owned_or_admin(db, uuid.UUID(replace_document_id), user)
        storage_uri = storage.put_object(object_name, data, file.content_type or "application/octet-stream")
        new_version_no = doc.current_version + 1
        doc.storage_uri = storage_uri
        doc.content_hash = content_hash
        doc.status = DocStatus.pending
        doc.current_version = new_version_no
        db.add(Version(document_id=doc.id, version_no=new_version_no, storage_uri=storage_uri))
        await db.commit()
        await db.refresh(doc)
        _enqueue_ingest(str(doc.id))
        return UploadResponse(
            document_id=doc.id, content_hash=content_hash, status=DocStatus.pending.value,
            message=f"Đã tạo version {new_version_no}.",
        )

    # --- Upload mới: chống trùng ---
    existing = await find_duplicate(db, content_hash)
    if existing:
        response.status_code = status.HTTP_200_OK
        return UploadResponse(
            document_id=existing.id,
            content_hash=content_hash,
            status=DocStatus.duplicate.value,
            message="Tài liệu đã tồn tại trong kho (trùng nội dung).",
        )

    storage_uri = storage.put_object(object_name, data, file.content_type or "application/octet-stream")
    doc = Document(
        owner_code=user.code,
        title=filename,
        visibility=Visibility.private,
        storage_uri=storage_uri,
        content_hash=content_hash,
        status=DocStatus.pending,
        current_version=1,
    )
    db.add(doc)
    await db.flush()
    db.add(Version(document_id=doc.id, version_no=1, storage_uri=storage_uri))
    await db.commit()
    await db.refresh(doc)

    _enqueue_ingest(str(doc.id))
    return UploadResponse(
        document_id=doc.id, content_hash=content_hash, status=DocStatus.pending.value
    )


@router.get("/{document_id}/download", response_model=DownloadResponse)
async def download_document(
    document_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
):
    """Tải tài liệu — chỉ khi có quyền (Public / chủ / admin / đã được duyệt xin quyền)."""
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")
    if not await can_access_document(db, user, doc):
        raise HTTPException(status_code=403, detail="Bạn không có quyền tải tài liệu này")
    return DownloadResponse(url=storage.get_presigned_url(doc.storage_uri))


@router.post("/{document_id}/confirm")
async def confirm_document(
    document_id: uuid.UUID,
    payload: ConfirmRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Chủ/admin xác nhận & sửa metadata AI gợi ý → chuyển status=ready."""
    doc = await _owned_or_admin(db, document_id, user)
    for field in ("doc_type", "topic", "subtopic", "author", "visibility"):
        value = getattr(payload, field)
        if value is not None:
            setattr(doc, field, value)
    doc.status = DocStatus.ready
    await db.commit()
    return {"document_id": str(doc.id), "status": doc.status.value}


@router.post("/{document_id}/rollback")
async def rollback_document(
    document_id: uuid.UUID,
    version_no: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Khôi phục về 1 version cũ (ghi log)."""
    doc = await _owned_or_admin(db, document_id, user)
    stmt = select(Version).where(
        Version.document_id == doc.id, Version.version_no == version_no
    )
    ver = (await db.execute(stmt)).scalar_one_or_none()
    if ver is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy version {version_no}")
    doc.storage_uri = ver.storage_uri
    doc.current_version = ver.version_no
    await db.commit()
    logger.info("rollback: document %s -> version %d", document_id, version_no)
    return {"document_id": str(doc.id), "current_version": ver.version_no}

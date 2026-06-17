import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user
from ...db.session import get_db
from ...models.access_request import AccessRequest, AccessStatus
from ...models.document import Document
from ...models.user import User, UserRole
from ...schemas.access import AccessRequestCreate, AccessRequestDecision, AccessRequestOut

router = APIRouter(prefix="/api/v1/access-requests", tags=["access-requests"])


@router.post("", response_model=AccessRequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: AccessRequestCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Người dùng gửi yêu cầu xin quyền truy cập 1 tài liệu."""
    doc = await db.get(Document, payload.document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")
    req = AccessRequest(document_id=doc.id, requester_code=user.code, status=AccessStatus.pending)
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


@router.get("", response_model=list[AccessRequestOut])
async def list_incoming(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Chủ tài liệu xem các yêu cầu gửi tới tài liệu của mình."""
    stmt = (
        select(AccessRequest)
        .join(Document, AccessRequest.document_id == Document.id)
        .where(Document.owner_code == user.code)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.patch("/{request_id}", response_model=AccessRequestOut)
async def decide(
    request_id: uuid.UUID,
    payload: AccessRequestDecision,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Chủ tài liệu (hoặc quản trị) duyệt/từ chối yêu cầu."""
    req = await db.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
    doc = await db.get(Document, req.document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")
    if doc.owner_code != user.code and user.role != UserRole.quan_tri:
        raise HTTPException(status_code=403, detail="Chỉ chủ tài liệu hoặc quản trị mới được duyệt")
    if payload.status not in (AccessStatus.approved, AccessStatus.denied):
        raise HTTPException(status_code=400, detail="status phải là approved hoặc denied")
    req.status = payload.status
    await db.commit()
    await db.refresh(req)
    return req

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import require_roles
from ...db.session import get_db
from ...models.user import User, UserRole
from ...schemas.admin import PermissionUpdate
from ...schemas.auth import UserOut

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.put("/permissions", response_model=UserOut)
async def set_permissions(
    payload: PermissionUpdate,
    _admin: Annotated[User, Depends(require_roles(UserRole.quan_tri))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Chỉ quản trị: đặt vai trò cho 1 tài khoản theo mã giảng viên."""
    result = await db.execute(select(User).where(User.code == payload.code))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    target.role = payload.role
    await db.commit()
    await db.refresh(target)
    return UserOut.model_validate(target)

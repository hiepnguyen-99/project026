from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, require_roles
from ...core.security import create_access_token, verify_password
from ...db.session import get_db
from ...models.user import User, UserRole
from ...schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Đăng nhập bằng mã giảng viên + mật khẩu → trả JWT."""
    result = await db.execute(select(User).where(User.code == payload.code))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mã hoặc mật khẩu không đúng",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tài khoản bị khóa")
    token = create_access_token(subject=user.code, role=user.role.value)
    return TokenResponse(token=token, user=UserOut.model_validate(user), role=user.role)


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]):
    """Thông tin user hiện tại (cần token hợp lệ)."""
    return UserOut.model_validate(user)


@router.get("/admin-only")
async def admin_only(user: Annotated[User, Depends(require_roles(UserRole.quan_tri))]):
    """Endpoint demo RBAC — chỉ quản trị mới vào được."""
    return {"ok": True, "code": user.code}

from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from .config import settings


def hash_password(password: str) -> str:
    """Băm mật khẩu bằng bcrypt (giới hạn 72 byte của bcrypt)."""
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """So khớp mật khẩu thô với hash đã lưu."""
    return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))


def create_access_token(subject: str, role: str) -> str:
    """Tạo JWT với sub=user.code và role."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Giải mã & verify JWT. Trả None nếu token sai/hết hạn."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None

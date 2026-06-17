import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.document import Document


def compute_hash(data: bytes) -> str:
    """SHA-256 của nội dung file."""
    return hashlib.sha256(data).hexdigest()


async def find_duplicate(db: AsyncSession, content_hash: str) -> Document | None:
    """Tìm tài liệu đã tồn tại cùng content_hash (chống lưu trùng)."""
    result = await db.execute(select(Document).where(Document.content_hash == content_hash))
    return result.scalar_one_or_none()

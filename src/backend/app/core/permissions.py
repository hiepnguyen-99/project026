from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.access_request import AccessRequest, AccessStatus
from ..models.document import Document, Visibility
from ..models.user import User, UserRole


async def can_access_document(db: AsyncSession, user: User, doc: Document) -> bool:
    """Quyền xem/tải 1 tài liệu: Public, chủ sở hữu, quản trị, hoặc đã được duyệt xin quyền."""
    if doc.visibility == Visibility.public:
        return True
    if doc.owner_code == user.code:
        return True
    if user.role == UserRole.quan_tri:
        return True
    stmt = select(AccessRequest).where(
        AccessRequest.document_id == doc.id,
        AccessRequest.requester_code == user.code,
        AccessRequest.status == AccessStatus.approved,
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None

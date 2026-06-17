from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.access_request import AccessRequest, AccessStatus
from ..models.chunk import Chunk
from ..models.document import Document, Visibility
from ..models.user import User
from . import embeddings


def _permission_condition(user: User):
    """Public OR của mình OR đã được duyệt xin quyền. (NGUYÊN TẮC 1: gác quyền ở SQL)"""
    approved = select(AccessRequest.document_id).where(
        AccessRequest.requester_code == user.code,
        AccessRequest.status == AccessStatus.approved,
    )
    return or_(
        Document.visibility == Visibility.public,
        Document.owner_code == user.code,
        Document.id.in_(approved),
    )


async def retrieve(db: AsyncSession, query: str, user: User, k: int = 5) -> list[dict]:
    """Vector search có GÁC QUYỀN NGAY TRONG SQL.

    NGUYÊN TẮC 1: quyền enforce bằng WHERE, KHÔNG nhờ LLM lọc.
    """
    qvec = embeddings.embed_texts([query])[0]
    permission = _permission_condition(user)
    stmt = (
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(permission)
    )
    # Vector ordering chỉ chạy trên Postgres (pgvector). SQLite (test) bỏ qua.
    if db.bind.dialect.name == "postgresql":
        stmt = stmt.order_by(Chunk.embedding.cosine_distance(qvec))
    stmt = stmt.limit(k)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "content": chunk.content,
            "title": doc.title,
            "storage_uri": doc.storage_uri,
            "page_ref": chunk.page_ref,
        }
        for chunk, doc in rows
    ]


async def find_restricted(db: AsyncSession, user: User, limit: int = 5) -> list[dict]:
    """Tài liệu Private của người KHÁC — CHỈ trả metadata, KHÔNG nội dung.

    Để hiển thị nút 'xin quyền' ở frontend.
    """
    approved = select(AccessRequest.document_id).where(
        AccessRequest.requester_code == user.code,
        AccessRequest.status == AccessStatus.approved,
    )
    stmt = (
        select(Document)
        .where(Document.visibility == Visibility.private)
        .where(Document.owner_code != user.code)
        .where(Document.id.notin_(approved))
        .limit(limit)
    )
    docs = (await db.execute(stmt)).scalars().all()
    return [
        {
            "file": doc.title,
            "owner": doc.owner_code,
            "visibility": doc.visibility.value,
            "action": "request_access",
        }
        for doc in docs
    ]

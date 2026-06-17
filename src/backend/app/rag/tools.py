import json

from langchain_core.tools import BaseTool, tool
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chunk import Chunk
from ..models.document import Document, Visibility
from ..models.user import User
from .retriever import retrieve


def build_tools(db: AsyncSession, user: User, citations_sink: list[dict]) -> list[BaseTool]:
    """Tạo tool gắn sẵn (db, user). MỖI tool tự lọc quyền bằng SQL.

    KHÔNG tool nào trả nội dung Private của người khác.
    citations_sink: list chia sẻ để gom citation khi agent gọi search_documents.
    """

    def _permission():
        return or_(Document.visibility == Visibility.public, Document.owner_code == user.code)

    @tool
    async def search_documents(query: str) -> str:
        """Tìm đoạn tài liệu liên quan tới truy vấn. Chỉ trả tài liệu bạn được phép xem."""
        contexts = await retrieve(db, query, user)
        citations_sink.extend(contexts)
        if not contexts:
            return "Không tìm thấy tài liệu liên quan."
        return json.dumps(
            [{"title": c["title"], "page": c["page_ref"], "content": c["content"]} for c in contexts],
            ensure_ascii=False,
        )

    @tool
    async def list_documents() -> str:
        """Liệt kê tên các tài liệu bạn được phép xem (Public hoặc của chính bạn)."""
        stmt = select(Document.title).where(_permission()).limit(50)
        titles = (await db.execute(stmt)).scalars().all()
        return json.dumps(titles, ensure_ascii=False)

    @tool
    async def summarize_document(document_title: str) -> str:
        """Lấy nội dung 1 tài liệu để tóm tắt (chỉ khi bạn được phép xem)."""
        stmt = select(Document).where(Document.title == document_title).where(_permission()).limit(1)
        doc = (await db.execute(stmt)).scalar_one_or_none()
        if doc is None:
            return "Không tìm thấy tài liệu hoặc bạn không có quyền xem."
        cstmt = select(Chunk.content).where(Chunk.document_id == doc.id).limit(5)
        contents = (await db.execute(cstmt)).scalars().all()
        return "\n".join(contents)[:2000] or "(tài liệu chưa có nội dung)"

    @tool
    async def request_access(document_title: str) -> str:
        """Gợi ý gửi yêu cầu xin quyền truy cập 1 tài liệu Private (không lộ nội dung)."""
        return (
            f"Tài liệu '{document_title}' là Private của người khác. "
            "Hãy gửi yêu cầu xin quyền qua chức năng 'Xin quyền'."
        )

    return [search_documents, list_documents, summarize_document, request_access]

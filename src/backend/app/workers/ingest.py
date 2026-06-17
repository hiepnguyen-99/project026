import asyncio
import io
import logging
import uuid

from docx import Document as DocxDocument
from pypdf import PdfReader
from sqlalchemy import delete

from ..db.session import AsyncSessionLocal
from ..models.chunk import Chunk
from ..models.document import DocStatus, Document
from ..rag import embeddings
from ..services.storage import get_storage

logger = logging.getLogger(__name__)


def parse_document(data: bytes, filename: str) -> list[tuple[str | None, str]]:
    """Trả list (page_ref, text). PDF giữ số trang; DOCX/TXT page_ref=None."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        reader = PdfReader(io.BytesIO(data))
        return [(str(i), page.extract_text() or "") for i, page in enumerate(reader.pages, start=1)]
    if ext == "docx":
        doc = DocxDocument(io.BytesIO(data))
        return [(None, "\n".join(p.text for p in doc.paragraphs))]
    return [(None, data.decode("utf-8", errors="replace"))]


def chunk_text(text: str, chunk_words: int = 400, overlap_words: int = 80) -> list[str]:
    """Cắt text thành các đoạn ~chunk_words từ, overlap ~overlap_words từ."""
    words = text.split()
    if not words:
        return []
    step = max(chunk_words - overlap_words, 1)
    chunks = []
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_words])
        if chunk.strip():
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


async def _run_ingest(document_id: str) -> None:
    storage = get_storage()
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, uuid.UUID(document_id))
        if doc is None:
            logger.warning("ingest: không tìm thấy document %s", document_id)
            return
        try:
            doc.status = DocStatus.processing
            await db.commit()

            data = storage.get_object(doc.storage_uri)
            pages = parse_document(data, doc.title)

            # Xóa chunk cũ để có thể reindex lại an toàn.
            await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))

            pending = [
                (page_ref, c)
                for page_ref, text in pages
                for c in chunk_text(text)
            ]
            if pending:
                vectors = embeddings.embed_texts([c for _, c in pending])
                for (page_ref, content), vec in zip(pending, vectors, strict=True):
                    db.add(Chunk(document_id=doc.id, content=content, page_ref=page_ref, embedding=vec))

            doc.status = DocStatus.ready
            await db.commit()
            logger.info("ingest: document %s -> ready (%d chunks)", document_id, len(pending))
        except Exception:
            await db.rollback()
            doc.status = DocStatus.failed
            await db.commit()
            logger.exception("ingest: document %s thất bại", document_id)
            raise


def run_ingest(document_id: str) -> None:
    """Wrapper sync cho Celery task."""
    asyncio.run(_run_ingest(document_id))

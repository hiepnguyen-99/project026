import uuid

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..core.config import settings
from ..db.base import Base
from ..db.types import VectorType


class Chunk(Base):
    """Đoạn văn bản đã tách + embedding (index HNSW trên Postgres)."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), index=True, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(VectorType(settings.EMBEDDING_DIM), nullable=False)

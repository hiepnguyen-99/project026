import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class Visibility(enum.StrEnum):
    public = "public"
    private = "private"


class DocStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    duplicate = "duplicate"
    failed = "failed"


class Document(Base):
    """Tài liệu trong kho. Metadata (doc_type, topic...) do AI gợi ý, người dùng xác nhận ở P6."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtopic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility: Mapped[Visibility] = mapped_column(
        SAEnum(Visibility, name="visibility"), default=Visibility.private, nullable=False
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    storage_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[DocStatus] = mapped_column(
        SAEnum(DocStatus, name="doc_status"), default=DocStatus.pending, nullable=False
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Version(Base):
    """Mỗi lần upload đè tạo 1 Version mới (versioning ở P6)."""

    __tablename__ = "versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), index=True, nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

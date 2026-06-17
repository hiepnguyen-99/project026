import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class AccessStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    denied = "denied"


class AccessRequest(Base):
    """Yêu cầu xin quyền truy cập 1 tài liệu Private (Human-in-the-loop)."""

    __tablename__ = "access_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), index=True, nullable=False
    )
    requester_code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    status: Mapped[AccessStatus] = mapped_column(
        SAEnum(AccessStatus, name="access_status"), default=AccessStatus.pending, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

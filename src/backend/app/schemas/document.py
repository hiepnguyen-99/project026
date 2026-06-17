import uuid

from pydantic import BaseModel

from ..models.document import Visibility


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    content_hash: str
    status: str
    message: str | None = None


class ConfirmRequest(BaseModel):
    doc_type: str | None = None
    topic: str | None = None
    subtopic: str | None = None
    author: str | None = None
    visibility: Visibility | None = None


class DownloadResponse(BaseModel):
    url: str

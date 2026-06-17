import uuid

from pydantic import BaseModel, ConfigDict

from ..models.access_request import AccessStatus


class AccessRequestCreate(BaseModel):
    document_id: uuid.UUID


class AccessRequestDecision(BaseModel):
    status: AccessStatus  # approved | denied


class AccessRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    requester_code: str
    status: AccessStatus

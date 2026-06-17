from pydantic import BaseModel

from ..models.user import UserRole


class PermissionUpdate(BaseModel):
    code: str
    role: UserRole

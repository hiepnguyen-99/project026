from pydantic import BaseModel, ConfigDict

from ..models.user import UserRole


class LoginRequest(BaseModel):
    code: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    full_name: str
    role: UserRole


class TokenResponse(BaseModel):
    token: str
    user: UserOut
    role: UserRole

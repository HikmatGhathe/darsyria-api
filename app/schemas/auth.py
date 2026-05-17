from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class MagicLinkRequest(BaseModel):
    email: EmailStr
    locale: str = Field(default="en", pattern="^(ar|de|en)$")


class MagicLinkVerifyRequest(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str | None
    locale: str
    is_admin: bool
    subscription_tier: str
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class GenericMessage(BaseModel):
    message: str

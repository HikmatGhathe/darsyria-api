from datetime import datetime
from typing import Optional
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
    phone: Optional[str] = None
    phone_public: bool = False
    locale: str
    is_admin: bool
    subscription_tier: str
    created_at: datetime

    account_type: Optional[str] = None
    company_name: Optional[str] = None
    company_about: Optional[str] = None
    company_website: Optional[str] = None
    company_address: Optional[str] = None
    verification_status: str = "unverified"


class AuthResponse(BaseModel):
    """
    The access/refresh tokens are never in this body — they're set as
    httpOnly cookies on the response instead, so they're not reachable
    from JS (XSS-resistant).
    """
    user: UserPublic


class GenericMessage(BaseModel):
    message: str


class UserUpdate(BaseModel):
    """Fields a user can update on their own profile."""
    full_name: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=40)
    phone_public: Optional[bool] = None
    locale: Optional[str] = Field(default=None, pattern="^(ar|de|en)$")

    account_type: Optional[str] = Field(default=None, pattern="^(individual|company)$")
    company_name: Optional[str] = Field(default=None, max_length=200)
    company_about: Optional[str] = Field(default=None, max_length=4000)
    company_website: Optional[str] = Field(default=None, max_length=300)
    company_address: Optional[str] = Field(default=None, max_length=2000)

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    """Full user representation returned from admin actions (ban/unban/promote/demote)."""
    id: UUID
    email: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    locale: str
    is_active: bool
    is_admin: bool
    ban_reason: Optional[str] = None
    banned_at: Optional[datetime] = None
    subscription_tier: str
    created_at: datetime
    last_login_at: Optional[datetime] = None
    account_type: Optional[str] = None
    company_name: Optional[str] = None
    verification_status: str = "unverified"

    model_config = ConfigDict(from_attributes=True)


class UserBanRequest(BaseModel):
    """Admin bans a user. Reason is stored and may be shown to the banned user."""
    reason: str = Field(min_length=10, max_length=1000)


class UserAdminListItem(BaseModel):
    """Lighter view of users for the admin dashboard."""
    id: UUID
    email: str
    full_name: Optional[str] = None
    locale: str
    is_active: bool
    is_admin: bool
    banned_at: Optional[datetime] = None
    ban_reason: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None
    # Quick stats — useful for admins eyeballing the list
    active_listings_count: int = 0
    account_type: Optional[str] = None
    company_name: Optional[str] = None
    verification_status: str = "unverified"

    model_config = ConfigDict(from_attributes=True)

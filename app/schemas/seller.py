from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.property import PropertyListItem


class SellerProfileOut(BaseModel):
    id: UUID
    display_name: Optional[str] = None
    account_type: Optional[str] = None
    verification_status: str
    member_since: datetime
    active_listing_count: int
    follower_count: int
    is_following: bool
    is_self: bool

    # Only populated when account_type == "company" — an individual's
    # phone/address stay private, surfaced only via the existing
    # mutual-consent reveal inside a conversation.
    company_about: Optional[str] = None
    company_website: Optional[str] = None
    company_address: Optional[str] = None
    phone: Optional[str] = None

    listings: list[PropertyListItem] = []

    model_config = ConfigDict(from_attributes=True)

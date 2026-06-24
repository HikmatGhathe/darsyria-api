from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.property import Property
from app.models.user import User


def seller_display_name(user: User) -> Optional[str]:
    """
    Display name for a seller in listings/search/profile pages.
    Companies show their company name; individuals fall back to the
    same convention used in conversations (full_name, then email
    local-part). Returns None for anonymized (GDPR-deleted) users.
    """
    if user.deleted_at is not None:
        return None
    if user.account_type == "company" and user.company_name:
        return user.company_name
    if user.full_name:
        return user.full_name
    if user.email:
        return user.email.split("@")[0]
    return None


def active_listing_count(db: Session, owner_id: UUID) -> int:
    return db.execute(
        select(func.count(Property.id)).where(
            Property.owner_id == owner_id, Property.status == "active"
        )
    ).scalar_one()

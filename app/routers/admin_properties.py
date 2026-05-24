"""
Admin endpoints for property moderation.

All routes require an authenticated admin user (is_admin=True).
Prefix: /admin/properties
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.property import Property
from app.models.user import User
from app.schemas.property import PropertyRejectRequest, PropertyAdminListItem
from app.services.email_service import send_rejection_notification, EmailError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/properties", tags=["admin-properties"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_property_or_404(db: Session, property_id: UUID) -> Property:
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    return prop


# ---------------------------------------------------------------------------
# GET /admin/properties  — paginated list with optional status filter
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PropertyAdminListItem])
def admin_list_properties(
    prop_status: Optional[str] = Query(default=None, alias="status"),
    flagged_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """
    List all properties for admin moderation.

    - Filter by status (draft, active, removed) via ?status=
    - Filter to only flagged listings via ?flagged_only=true
    - Paginate with ?limit=&offset=
    """
    q = select(Property)

    if prop_status:
        q = q.where(Property.status == prop_status)

    if flagged_only:
        q = q.where(Property.flagged_at.is_not(None))

    q = q.order_by(Property.created_at.desc()).offset(offset).limit(limit)

    properties = db.execute(q).scalars().all()
    return properties


# ---------------------------------------------------------------------------
# POST /admin/properties/{id}/approve  — set status active + stamp reviewed_at
# ---------------------------------------------------------------------------

@router.post("/{property_id}/approve", response_model=PropertyAdminListItem)
def admin_approve_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Approve (publish) a property listing.
    Sets status → active, clears any rejection_reason, stamps reviewed_at.
    """
    prop = _get_property_or_404(db, property_id)

    if prop.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Property is already active",
        )

    prop.status = "active"
    prop.rejection_reason = None
    prop.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(prop)

    logger.info("Admin %s approved property %s", admin.id, property_id)
    return prop


# ---------------------------------------------------------------------------
# POST /admin/properties/{id}/reject  — set status removed + send email
# ---------------------------------------------------------------------------

@router.post("/{property_id}/reject", response_model=PropertyAdminListItem)
def admin_reject_property(
    property_id: UUID,
    body: PropertyRejectRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Remove a property listing with a reason.
    Sets status → removed, stores rejection_reason, stamps reviewed_at.
    Sends an email to the owner in their preferred locale.
    """
    prop = _get_property_or_404(db, property_id)

    if prop.status == "removed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Property is already removed",
        )

    prop.status = "rejected"
    prop.rejection_reason = body.reason
    prop.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(prop)

    logger.info("Admin %s rejected property %s: %s", admin.id, property_id, body.reason[:80])

    # Send email notification to owner — non-blocking failure
    owner = db.get(User, prop.owner_id)
    if owner:
        try:
            send_rejection_notification(
                to_email=owner.email,
                property_title=prop.title,
                reason=body.reason,
                locale=getattr(owner, "locale", "en") or "en",
            )
        except EmailError:
            logger.warning(
                "Could not send rejection email to owner %s for property %s",
                owner.id,
                property_id,
            )

    return prop


# ---------------------------------------------------------------------------
# POST /admin/properties/{id}/flag  — mark as needing review
# ---------------------------------------------------------------------------

@router.post("/{property_id}/flag", response_model=PropertyAdminListItem)
def admin_flag_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Flag a property for review without changing its visibility.
    Sets flagged_at to now. Idempotent if already flagged.
    """
    prop = _get_property_or_404(db, property_id)

    if prop.flagged_at is None:
        prop.flagged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(prop)
        logger.info("Admin %s flagged property %s", admin.id, property_id)
    # If already flagged, return current state without error (idempotent)

    return prop


# ---------------------------------------------------------------------------
# POST /admin/properties/{id}/unflag  — clear the flag
# ---------------------------------------------------------------------------

@router.post("/{property_id}/unflag", response_model=PropertyAdminListItem)
def admin_unflag_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Clear the flag on a property. Idempotent if not currently flagged.
    """
    prop = _get_property_or_404(db, property_id)

    if prop.flagged_at is not None:
        prop.flagged_at = None
        db.commit()
        db.refresh(prop)
        logger.info("Admin %s unflagged property %s", admin.id, property_id)

    return prop

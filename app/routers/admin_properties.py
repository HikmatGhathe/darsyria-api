"""
Admin endpoints for property moderation.

All routes require an authenticated admin user (is_admin=True).
Prefix: /admin/properties
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.property import Property
from app.models.user import User
from app.models.verification_document import VerificationDocument
from app.schemas.property import PropertyRejectRequest, PropertyAdminListItem
from app.schemas.verification import (
    AdminListingVerificationItem,
    AdminPresignedDocument,
    RejectRequest,
)
from app.services.email_service import send_rejection_notification, EmailError
from app.services.r2_storage import StorageError, generate_presigned_url

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


def _send_rejection_email(
    to_email: str,
    property_title: str,
    reason: str,
    locale: str,
    owner_id: UUID,
    property_id: UUID,
) -> None:
    """Runs as a background task — must not raise, non-fatal on failure."""
    try:
        send_rejection_notification(
            to_email=to_email,
            property_title=property_title,
            reason=reason,
            locale=locale,
        )
    except EmailError:
        logger.warning(
            "Could not send rejection email to owner %s for property %s",
            owner_id,
            property_id,
        )


# ---------------------------------------------------------------------------
# GET /admin/properties  — paginated list with optional status filter
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PropertyAdminListItem])
def admin_list_properties(
    prop_status: Optional[str] = Query(default=None, alias="status"),
    flagged_only: bool = Query(default=False),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """
    List all properties for admin moderation.

    - Filter by status (draft, active, rejected, removed) via ?status=
    - Filter to only flagged listings via ?flagged_only=true
    - Full-text search across title and owner email via ?search=
    - Paginate with ?limit=&offset=
    """
    q = select(Property)

    if prop_status:
        q = q.where(Property.status == prop_status)

    if flagged_only:
        q = q.where(Property.flagged_at.is_not(None))

    if search:
        like = f"%{search}%"
        q = q.join(User, Property.owner_id == User.id).where(
            or_(Property.title.ilike(like), User.email.ilike(like))
        )

    q = q.order_by(Property.created_at.desc()).offset(offset).limit(limit)
    properties = db.execute(q).scalars().all()

    # Build items with owner_email — N+1 is fine at our scale
    items = []
    for prop in properties:
        owner = db.get(User, prop.owner_id)
        items.append(PropertyAdminListItem(
            id=prop.id,
            owner_id=prop.owner_id,
            owner_email=owner.email if owner else None,
            title=prop.title,
            city=prop.city,
            price_amount=prop.price_amount,
            price_currency=prop.price_currency,
            status=prop.status,
            document_status=prop.document_status,
            flagged_at=prop.flagged_at,
            reviewed_at=prop.reviewed_at,
            rejection_reason=prop.rejection_reason,
            created_at=prop.created_at,
        ))
    return items


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
    background_tasks: BackgroundTasks,
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

    # Send email notification to owner in the background — doesn't block the response
    owner = db.get(User, prop.owner_id)
    if owner:
        background_tasks.add_task(
            _send_rejection_email,
            to_email=owner.email,
            property_title=prop.title,
            reason=body.reason,
            locale=getattr(owner, "locale", "en") or "en",
            owner_id=owner.id,
            property_id=property_id,
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


# ---------------------------------------------------------------------------
# Listing ownership verification (individual sellers)
# ---------------------------------------------------------------------------

@router.get("/verification/pending", response_model=list[AdminListingVerificationItem])
def admin_list_pending_listing_verifications(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Listings whose owner has submitted ownership documents awaiting review."""
    props = db.execute(
        select(Property)
        .where(Property.verification_status == "pending")
        .order_by(Property.updated_at.desc())
    ).scalars().all()

    items = []
    for prop in props:
        owner = db.get(User, prop.owner_id)
        doc_count = db.execute(
            select(func.count(VerificationDocument.id)).where(
                VerificationDocument.property_id == prop.id,
                VerificationDocument.kind == "listing_ownership",
            )
        ).scalar() or 0
        submitted_at = db.execute(
            select(func.max(VerificationDocument.created_at)).where(
                VerificationDocument.property_id == prop.id,
                VerificationDocument.kind == "listing_ownership",
            )
        ).scalar()
        items.append(
            AdminListingVerificationItem(
                property_id=prop.id,
                title=prop.title,
                owner_id=prop.owner_id,
                owner_email=owner.email if owner else "",
                verification_status=prop.verification_status,
                document_count=doc_count,
                submitted_at=submitted_at,
            )
        )
    return items


@router.get(
    "/{property_id}/verification/documents",
    response_model=list[AdminPresignedDocument],
)
def admin_list_listing_verification_documents(
    property_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Presigned, short-lived URLs for a listing's ownership documents."""
    _get_property_or_404(db, property_id)

    docs = db.execute(
        select(VerificationDocument)
        .where(
            VerificationDocument.property_id == property_id,
            VerificationDocument.kind == "listing_ownership",
        )
        .order_by(VerificationDocument.created_at.desc())
    ).scalars().all()

    out = []
    for d in docs:
        try:
            url = generate_presigned_url(d.storage_key)
        except StorageError:
            continue
        out.append(
            AdminPresignedDocument(
                document_id=d.id,
                original_filename=d.original_filename,
                content_type=d.content_type,
                size_bytes=d.size_bytes,
                created_at=d.created_at,
                url=url,
            )
        )
    return out


@router.post("/{property_id}/verification/approve", response_model=PropertyAdminListItem)
def admin_approve_listing_verification(
    property_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Approve a listing's ownership verification → 'Ownership verified' badge."""
    prop = _get_property_or_404(db, property_id)

    prop.verification_status = "verified"
    prop.verification_rejection_reason = None
    prop.verification_reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(prop)

    logger.info("Admin %s approved ownership verification for %s", admin.id, property_id)
    return prop


@router.post("/{property_id}/verification/reject", response_model=PropertyAdminListItem)
def admin_reject_listing_verification(
    property_id: UUID,
    body: RejectRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Reject a listing's ownership verification, with a reason for the owner."""
    prop = _get_property_or_404(db, property_id)

    prop.verification_status = "rejected"
    prop.verification_rejection_reason = body.reason
    prop.verification_reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(prop)

    logger.info("Admin %s rejected ownership verification for %s", admin.id, property_id)
    return prop

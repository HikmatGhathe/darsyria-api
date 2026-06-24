"""
Admin endpoints for user moderation.
All require is_admin=True.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.property import Property
from app.models.user import User
from app.schemas.user import (
    UserAdminListItem,
    UserBanRequest,
    UserOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/users", tags=["admin"])


@router.get("", response_model=list[UserAdminListItem])
def list_all_users(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
    search: Optional[str] = Query(default=None, max_length=200),
    banned_only: bool = Query(default=False),
    admins_only: bool = Query(default=False),
    pending_verification_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    List all users for admin moderation.
    Filters: search (email, full_name, or company_name), banned_only,
    admins_only, pending_verification_only.
    Default sort: newest first.
    """
    stmt = select(User)

    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                User.email.ilike(like),
                User.full_name.ilike(like),
                User.company_name.ilike(like),
            )
        )
    if banned_only:
        stmt = stmt.where(User.is_active.is_(False))
    if admins_only:
        stmt = stmt.where(User.is_admin.is_(True))
    if pending_verification_only:
        stmt = stmt.where(User.verification_status == "pending")

    stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)

    users = db.execute(stmt).scalars().all()

    # Compute active_listings_count per user. N+1 here is fine at our scale.
    items = []
    for u in users:
        active_count = db.execute(
            select(func.count(Property.id))
            .where(Property.owner_id == u.id, Property.status == "active")
        ).scalar_one()
        items.append(UserAdminListItem(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            locale=u.locale,
            is_active=u.is_active,
            is_admin=u.is_admin,
            banned_at=u.banned_at,
            ban_reason=u.ban_reason,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            active_listings_count=active_count,
            account_type=u.account_type,
            company_name=u.company_name,
            verification_status=u.verification_status,
        ))

    return items


@router.post("/{user_id}/ban", response_model=UserOut)
def ban_user(
    user_id: UUID,
    payload: UserBanRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Ban a user.
    Sets is_active=false, stores ban_reason and banned_at.
    Auto-removes all their active listings (sets status="removed").
    Admin cannot ban themselves.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot ban yourself")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_active:
        # Already banned. Idempotent — just update reason if it changed.
        user.ban_reason = payload.reason.strip()
        db.commit()
        db.refresh(user)
        return user

    user.is_active = False
    user.ban_reason = payload.reason.strip()
    user.banned_at = datetime.now(timezone.utc)

    # Auto-remove their active listings
    active_listings = db.execute(
        select(Property).where(
            Property.owner_id == user_id,
            Property.status == "active",
        )
    ).scalars().all()

    removed_count = 0
    for prop in active_listings:
        prop.status = "removed"
        removed_count += 1

    db.commit()
    db.refresh(user)

    logger.info(
        "User %s (%s) banned by admin %s. Reason: %s. Removed %d listings.",
        user.id,
        user.email,
        admin.id,
        payload.reason[:50],
        removed_count,
    )
    return user


@router.post("/{user_id}/unban", response_model=UserOut)
def unban_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Restore a banned user's access. Their removed listings stay removed
    (they can republish manually).
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_active:
        return user  # already active, idempotent

    user.is_active = True
    user.ban_reason = None
    user.banned_at = None

    db.commit()
    db.refresh(user)

    logger.info("User %s (%s) unbanned by admin %s", user.id, user.email, admin.id)
    return user


@router.post("/{user_id}/promote", response_model=UserOut)
def promote_to_admin(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Promote a user to admin. Banned users cannot be promoted."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_active:
        raise HTTPException(
            status_code=400,
            detail="Cannot promote a banned user. Unban them first.",
        )

    if user.is_admin:
        return user  # already admin, idempotent

    user.is_admin = True
    db.commit()
    db.refresh(user)

    logger.info("User %s (%s) promoted to admin by %s", user.id, user.email, admin.id)
    return user


@router.post("/{user_id}/demote", response_model=UserOut)
def demote_from_admin(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Demote an admin to regular user. Cannot demote yourself."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot demote yourself")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_admin:
        return user  # already not admin, idempotent

    user.is_admin = False
    db.commit()
    db.refresh(user)

    logger.info("User %s (%s) demoted by admin %s", user.id, user.email, admin.id)
    return user


@router.post("/{user_id}/verify", response_model=UserOut)
def verify_seller(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Mark a seller as verified. This only controls whether the "Verified
    seller" badge shows on their public profile — it never gates whether
    they can list properties or use the platform.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.verification_status == "verified":
        return user  # already verified, idempotent

    user.verification_status = "verified"
    db.commit()
    db.refresh(user)

    logger.info("User %s (%s) verified by admin %s", user.id, user.email, admin.id)
    return user


@router.post("/{user_id}/unverify", response_model=UserOut)
def unverify_seller(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Revoke a seller's verified status, e.g. if their info turns out to be false."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.verification_status != "verified":
        return user  # already not verified, idempotent

    user.verification_status = "pending"
    db.commit()
    db.refresh(user)

    logger.info("User %s (%s) unverified by admin %s", user.id, user.email, admin.id)
    return user

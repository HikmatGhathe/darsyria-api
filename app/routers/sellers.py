import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.models.follow import Follow
from app.models.property import Property
from app.models.property_image import PropertyImage
from app.models.user import User
from app.schemas.property import PropertyListItem
from app.schemas.seller import SellerProfileOut
from app.services.seller_helpers import active_listing_count, seller_display_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sellers", tags=["sellers"])


def _active_listings_for_owner(db: Session, owner: User) -> list[PropertyListItem]:
    # Cover image (position 0) joined in the same query — one query for the
    # whole profile instead of one extra lookup per listing.
    results = db.execute(
        select(Property, PropertyImage)
        .outerjoin(
            PropertyImage,
            and_(
                PropertyImage.property_id == Property.id,
                PropertyImage.position == 0,
            ),
        )
        .where(Property.owner_id == owner.id, Property.status == "active")
        .order_by(Property.created_at.desc())
    ).all()

    items = []
    for prop, cover in results:
        item = PropertyListItem.model_validate(prop)
        item.cover_image_url = cover.public_url if cover else None
        item.seller_display_name = seller_display_name(owner)
        item.seller_account_type = owner.account_type
        item.seller_verification_status = owner.verification_status
        items.append(item)
    return items


def _get_visible_seller(db: Session, user_id: UUID) -> User:
    seller = db.get(User, user_id)
    if not seller or seller.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Seller not found")
    return seller


@router.get("/{user_id}", response_model=SellerProfileOut)
def get_seller_profile(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Public seller/company profile. 404s for nonexistent or GDPR-anonymized
    users so a deleted account never resurfaces in a URL someone bookmarked.
    """
    seller = _get_visible_seller(db, user_id)
    is_company = seller.account_type == "company"

    follower_count = db.execute(
        select(func.count(Follow.id)).where(Follow.followed_user_id == user_id)
    ).scalar_one()

    is_following = False
    if current_user:
        is_following = db.execute(
            select(Follow.id).where(
                Follow.follower_id == current_user.id,
                Follow.followed_user_id == user_id,
            )
        ).scalar_one_or_none() is not None

    return SellerProfileOut(
        id=seller.id,
        display_name=seller_display_name(seller),
        account_type=seller.account_type,
        verification_status=seller.verification_status,
        member_since=seller.created_at,
        active_listing_count=active_listing_count(db, user_id),
        follower_count=follower_count,
        is_following=is_following,
        is_self=current_user is not None and current_user.id == seller.id,
        company_about=seller.company_about if is_company else None,
        company_website=seller.company_website if is_company else None,
        company_address=seller.company_address if is_company else None,
        phone=seller.phone if is_company else None,
        listings=_active_listings_for_owner(db, seller),
    )


@router.post("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def follow_seller(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't follow yourself")

    _get_visible_seller(db, user_id)

    existing = db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.followed_user_id == user_id,
        )
    ).scalar_one_or_none()
    if existing:
        return None

    follow = Follow(follower_id=current_user.id, followed_user_id=user_id)
    db.add(follow)
    try:
        db.flush()
    except IntegrityError:
        # Race: another request just created the same follow row.
        db.rollback()
    else:
        db.commit()
        logger.info("User %s followed seller %s", current_user.id, user_id)
    return None


@router.delete("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def unfollow_seller(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    follow = db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.followed_user_id == user_id,
        )
    ).scalar_one_or_none()
    if follow:
        db.delete(follow)
        db.commit()
        logger.info("User %s unfollowed seller %s", current_user.id, user_id)
    return None

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.favorite import Favorite
from app.models.property import Property
from app.models.property_image import PropertyImage
from app.models.user import User
from app.schemas.property import PropertyListItem
from app.services.seller_helpers import seller_display_name

logger = logging.getLogger(__name__)
router = APIRouter(tags=["favorites"])


@router.post("/properties/{property_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def add_favorite(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    existing = db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.property_id == property_id,
        )
    ).scalar_one_or_none()
    if existing:
        return None

    fav = Favorite(user_id=current_user.id, property_id=property_id)
    db.add(fav)
    try:
        db.flush()
    except IntegrityError:
        # Race: another request just saved the same favorite.
        db.rollback()
    else:
        db.commit()
        logger.info("User %s favorited property %s", current_user.id, property_id)
    return None


@router.delete("/properties/{property_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fav = db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.property_id == property_id,
        )
    ).scalar_one_or_none()
    if fav:
        db.delete(fav)
        db.commit()
    return None


@router.get("/favorites/ids", response_model=list[UUID])
def list_favorite_ids(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Just the IDs the current user has favorited — lets the client fill the
    right hearts without a request per card."""
    return db.execute(
        select(Favorite.property_id).where(Favorite.user_id == current_user.id)
    ).scalars().all()


@router.get("/favorites", response_model=list[PropertyListItem])
def list_favorites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The user's favorited active listings, most-recently-saved first."""
    stmt = (
        select(Property, User, PropertyImage)
        .join(Favorite, Favorite.property_id == Property.id)
        .join(User, Property.owner_id == User.id)
        .outerjoin(
            PropertyImage,
            and_(
                PropertyImage.property_id == Property.id,
                PropertyImage.position == 0,
            ),
        )
        .where(Favorite.user_id == current_user.id, Property.status == "active")
        .order_by(Favorite.created_at.desc())
    )
    results = db.execute(stmt).all()

    items = []
    for prop, owner, cover in results:
        item = PropertyListItem.model_validate(prop)
        item.cover_image_url = cover.public_url if cover else None
        item.seller_display_name = seller_display_name(owner)
        item.seller_account_type = owner.account_type
        item.seller_verification_status = owner.verification_status
        items.append(item)
    return items

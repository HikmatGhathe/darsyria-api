import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.models.property import Property
from app.models.property_image import PropertyImage
from app.models.user import User
from app.schemas.property import (
    PropertyCreate,
    PropertyUpdate,
    PropertyOut,
    PropertyListItem,
    PropertyImageOut,
)
from app.services.r2_storage import upload_property_image, delete_object, delete_property_images, StorageError
from app.services.seller_helpers import seller_display_name
from app.services.property_filters import apply_property_filters

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/properties", tags=["properties"])

MAX_IMAGES_PER_PROPERTY = 10


@router.post("", response_model=PropertyOut, status_code=status.HTTP_201_CREATED)
def create_property(
    payload: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new property listing. The current user becomes the owner.
    Status starts as 'draft'; the owner publishes via a separate endpoint
    (to be added in a future step).
    """
    prop = Property(
        owner_id=current_user.id,
        title=payload.title,
        description=payload.description,
        city=payload.city,
        neighborhood=payload.neighborhood,
        price_amount=payload.price_amount,
        price_currency=payload.price_currency,
        property_type=payload.property_type,
        rooms=payload.rooms,
        bathrooms=payload.bathrooms,
        area_sqm=payload.area_sqm,
        document_status=payload.document_status,
        status="draft",
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)

    logger.info("Property %s created by user %s", prop.id, current_user.id)
    return prop


_PROPERTY_SORTS = {
    "newest": (Property.created_at.desc(),),
    "oldest": (Property.created_at.asc(),),
    "price_asc": (Property.price_amount.asc(), Property.created_at.desc()),
    "price_desc": (Property.price_amount.desc(), Property.created_at.desc()),
}


@router.get("", response_model=list[PropertyListItem])
def list_properties(
    db: Session = Depends(get_db),
    city: Optional[str] = Query(default=None, max_length=100),
    property_type: Optional[str] = Query(
        default=None,
        pattern="^(apartment|house|land|commercial)$",
    ),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    rooms: Optional[int] = Query(default=None, ge=0, le=50),
    seller: Optional[str] = Query(default=None, max_length=200),
    sort: str = Query(default="newest", pattern="^(newest|oldest|price_asc|price_desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """
    Public listing browser. Only returns 'active' status.
    Filters: city, property_type, price range, rooms, seller/company name.
    Sort: newest (default), oldest, price_asc, price_desc.
    """
    # Cover image (position 0) is joined in the same query — one query for
    # the whole page instead of one extra lookup per listing.
    stmt = (
        select(Property, User, PropertyImage)
        .join(User, Property.owner_id == User.id)
        .outerjoin(
            PropertyImage,
            and_(
                PropertyImage.property_id == Property.id,
                PropertyImage.position == 0,
            ),
        )
    )
    stmt = apply_property_filters(
        stmt,
        city=city,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        rooms=rooms,
        seller=seller,
    )
    stmt = stmt.order_by(*_PROPERTY_SORTS[sort]).limit(limit).offset(offset)

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


@router.get("/count")
def count_properties(
    db: Session = Depends(get_db),
    city: Optional[str] = Query(default=None, max_length=100),
    property_type: Optional[str] = Query(
        default=None,
        pattern="^(apartment|house|land|commercial)$",
    ),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    rooms: Optional[int] = Query(default=None, ge=0, le=50),
    seller: Optional[str] = Query(default=None, max_length=200),
):
    """Total active listings matching the same filters as the list endpoint
    (used by the browse page for 'X results' and 'Page N of M')."""
    stmt = select(func.count(Property.id)).join(User, Property.owner_id == User.id)
    stmt = apply_property_filters(
        stmt,
        city=city,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        rooms=rooms,
        seller=seller,
    )
    return {"count": db.execute(stmt).scalar_one()}


@router.get("/{property_id}", response_model=PropertyOut)
def get_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Get a single property. Active properties are public.
    Drafts are visible only to their owner.
    """
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if prop.status != "active":
        if not current_user or prop.owner_id != current_user.id:
            raise HTTPException(status_code=404, detail="Property not found")

    images = db.execute(
        select(PropertyImage)
        .where(PropertyImage.property_id == prop.id)
        .order_by(PropertyImage.position)
    ).scalars().all()

    owner = db.get(User, prop.owner_id)

    out = PropertyOut.model_validate(prop)
    out.images = [PropertyImageOut.model_validate(img) for img in images]
    if owner:
        out.seller_display_name = seller_display_name(owner)
        out.seller_account_type = owner.account_type
        out.seller_verification_status = owner.verification_status
    return out


@router.post("/{property_id}/publish", response_model=PropertyOut)
def publish_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only publish your own listings")

    if prop.status not in ("draft",):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot publish a listing with status '{prop.status}'",
        )

    prop.status = "active"
    if prop.published_at is None:
        prop.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(prop)

    logger.info("Property %s published by %s", prop.id, current_user.id)
    return prop


@router.post("/{property_id}/unpublish", response_model=PropertyOut)
def unpublish_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only unpublish your own listings")

    if prop.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot unpublish a listing with status '{prop.status}'",
        )

    prop.status = "draft"
    db.commit()
    db.refresh(prop)

    logger.info("Property %s unpublished by %s", prop.id, current_user.id)
    return prop


@router.patch("/{property_id}", response_model=PropertyOut)
def update_property(
    property_id: UUID,
    payload: PropertyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own listings")

    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        return prop

    for field, value in updates.items():
        setattr(prop, field, value)

    db.commit()
    db.refresh(prop)

    logger.info("Property %s updated by %s (fields: %s)", prop.id, current_user.id, list(updates.keys()))
    return prop


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own listings")

    db.delete(prop)
    db.commit()

    # Clean up R2 objects after DB commit — DB cascade already deleted the rows
    try:
        deleted = delete_property_images(str(property_id))
        if deleted:
            logger.info("Deleted %d R2 objects for property %s", deleted, property_id)
    except StorageError:
        logger.exception("R2 cleanup failed for property %s — orphaned objects may remain", property_id)

    logger.info("Property %s deleted by %s", property_id, current_user.id)
    return None


# ---------------------------------------------------------------------------
# Image endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{property_id}/images",
    response_model=PropertyImageOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_image(
    property_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload one image for a property. Max 20 images per property."""
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only add images to your own listings")

    count = db.execute(
        select(PropertyImage).where(PropertyImage.property_id == property_id)
    ).scalars().all()
    if len(count) >= MAX_IMAGES_PER_PROPERTY:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_IMAGES_PER_PROPERTY} images per property",
        )

    raw_bytes = file.file.read()
    try:
        result = upload_property_image(
            property_id=str(property_id),
            raw_bytes=raw_bytes,
            original_filename=file.filename,
        )
    except StorageError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # New image goes to the end (highest position)
    next_position = len(count)

    image = PropertyImage(
        property_id=property_id,
        storage_key=result["storage_key"],
        public_url=result["public_url"],
        original_filename=result["original_filename"],
        size_bytes=result["size_bytes"],
        position=next_position,
    )
    db.add(image)
    db.commit()
    db.refresh(image)

    logger.info("Image %s uploaded for property %s", image.id, property_id)
    return image


@router.get("/{property_id}/images", response_model=list[PropertyImageOut])
def list_images(
    property_id: UUID,
    db: Session = Depends(get_db),
):
    """List all images for a property, ordered by position."""
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    images = db.execute(
        select(PropertyImage)
        .where(PropertyImage.property_id == property_id)
        .order_by(PropertyImage.position)
    ).scalars().all()
    return images


@router.delete(
    "/{property_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_image(
    property_id: UUID,
    image_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete one image. Reorders remaining images to fill the gap."""
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete images from your own listings")

    image = db.get(PropertyImage, image_id)
    if not image or image.property_id != property_id:
        raise HTTPException(status_code=404, detail="Image not found")

    storage_key = image.storage_key
    deleted_position = image.position

    db.delete(image)
    db.flush()

    # Shift positions down for images after the deleted one
    remaining = db.execute(
        select(PropertyImage)
        .where(
            PropertyImage.property_id == property_id,
            PropertyImage.position > deleted_position,
        )
        .order_by(PropertyImage.position)
    ).scalars().all()

    for img in remaining:
        img.position -= 1

    db.commit()

    try:
        delete_object(storage_key)
    except StorageError:
        logger.exception("R2 delete failed for key %s — orphaned object may remain", storage_key)

    logger.info("Image %s deleted from property %s", image_id, property_id)
    return None


@router.patch("/{property_id}/images/reorder", response_model=list[PropertyImageOut])
def reorder_images(
    property_id: UUID,
    image_ids: list[UUID],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Reorder images by supplying ALL image IDs in the desired order.
    First ID becomes position=0 (the cover image).
    """
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only reorder images on your own listings")

    existing = db.execute(
        select(PropertyImage).where(PropertyImage.property_id == property_id)
    ).scalars().all()

    existing_ids = {img.id for img in existing}
    if set(image_ids) != existing_ids:
        raise HTTPException(
            status_code=400,
            detail="image_ids must contain exactly all image IDs for this property",
        )

    id_to_image = {img.id: img for img in existing}
    for position, image_id in enumerate(image_ids):
        id_to_image[image_id].position = position

    db.commit()

    return sorted(existing, key=lambda img: img.position)

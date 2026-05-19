import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.property import Property
from app.models.user import User
from app.schemas.property import PropertyCreate, PropertyOut, PropertyListItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/properties", tags=["properties"])


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
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """
    Public listing browser. Only returns 'active' status.
    Filters: city, property_type, price range, rooms.
    """
    stmt = select(Property).where(Property.status == "active")

    if city:
        stmt = stmt.where(Property.city.ilike(f"%{city}%"))
    if property_type:
        stmt = stmt.where(Property.property_type == property_type)
    if min_price is not None:
        stmt = stmt.where(Property.price_amount >= min_price)
    if max_price is not None:
        stmt = stmt.where(Property.price_amount <= max_price)
    if rooms is not None:
        stmt = stmt.where(Property.rooms == rooms)

    stmt = stmt.order_by(Property.created_at.desc()).limit(limit).offset(offset)

    results = db.execute(stmt).scalars().all()
    return results


@router.get("/{property_id}", response_model=PropertyOut)
def get_property(
    property_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Get a single property by ID. Public, but only 'active' (or owned by viewer
    in a future step where we add ownership-based access to drafts).
    """
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.status != "active":
        raise HTTPException(status_code=404, detail="Property not found")
    return prop

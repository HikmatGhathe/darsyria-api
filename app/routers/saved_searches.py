import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.saved_search import SavedSearch
from app.models.user import User
from app.schemas.saved_search import SavedSearchCreate, SavedSearchOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])

MAX_SAVED_SEARCHES = 20


def build_label(data: SavedSearchCreate) -> str:
    """Compact, value-based summary shown in the list and the daily email."""
    parts: list[str] = []
    if data.city:
        parts.append(data.city)
    if data.property_type:
        parts.append(data.property_type.capitalize())
    if data.min_price is not None and data.max_price is not None:
        parts.append(f"€{int(data.min_price)}–€{int(data.max_price)}")
    elif data.min_price is not None:
        parts.append(f"≥ €{int(data.min_price)}")
    elif data.max_price is not None:
        parts.append(f"≤ €{int(data.max_price)}")
    if data.rooms is not None:
        parts.append(f"{data.rooms}+ rooms")
    if data.seller:
        parts.append(f"by {data.seller}")
    return " · ".join(parts) if parts else "All listings"


@router.post("", response_model=SavedSearchOut, status_code=status.HTTP_201_CREATED)
def create_saved_search(
    payload: SavedSearchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = db.execute(
        select(func.count(SavedSearch.id)).where(SavedSearch.user_id == current_user.id)
    ).scalar_one()
    if count >= MAX_SAVED_SEARCHES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You can save at most {MAX_SAVED_SEARCHES} searches.",
        )

    search = SavedSearch(
        user_id=current_user.id,
        city=payload.city,
        property_type=payload.property_type,
        min_price=payload.min_price,
        max_price=payload.max_price,
        rooms=payload.rooms,
        seller=payload.seller,
        label=build_label(payload),
    )
    db.add(search)
    db.commit()
    db.refresh(search)
    logger.info("User %s saved search %s (%s)", current_user.id, search.id, search.label)
    return search


@router.get("", response_model=list[SavedSearchOut])
def list_saved_searches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.execute(
        select(SavedSearch)
        .where(SavedSearch.user_id == current_user.id)
        .order_by(SavedSearch.created_at.desc())
    ).scalars().all()


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_search(
    search_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    search = db.get(SavedSearch, search_id)
    if search and search.user_id == current_user.id:
        db.delete(search)
        db.commit()
    return None

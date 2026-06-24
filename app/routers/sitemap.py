from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.property import Property
from app.models.user import User

router = APIRouter(prefix="/sitemap-data", tags=["sitemap"])


class SitemapEntry(BaseModel):
    id: str
    updated_at: datetime


class SitemapData(BaseModel):
    properties: list[SitemapEntry]
    sellers: list[SitemapEntry]


@router.get("", response_model=SitemapData)
def get_sitemap_data(db: Session = Depends(get_db)):
    """
    Minimal id + lastmod feed for the frontend sitemap generator. Only
    public, crawlable resources: active listings and the sellers who own
    them. Intentionally no joins/images — kept cheap since the sitemap is
    regenerated on a schedule by crawlers.
    """
    property_rows = db.execute(
        select(Property.id, Property.updated_at).where(Property.status == "active")
    ).all()

    # Distinct, non-deleted owners of at least one active listing.
    seller_rows = db.execute(
        select(User.id, User.updated_at)
        .where(
            User.deleted_at.is_(None),
            User.id.in_(
                select(Property.owner_id).where(Property.status == "active")
            ),
        )
    ).all()

    return SitemapData(
        properties=[
            SitemapEntry(id=str(pid), updated_at=updated) for pid, updated in property_rows
        ],
        sellers=[
            SitemapEntry(id=str(sid), updated_at=updated) for sid, updated in seller_rows
        ],
    )

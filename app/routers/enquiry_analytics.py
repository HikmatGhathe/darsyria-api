from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.enquiry import EnquiryAnalyticsOut
from app.services.enquiry_service import mark_unanswered_threads

router = APIRouter(prefix="/admin/enquiries", tags=["admin-enquiries"])


@router.get("/analytics", response_model=EnquiryAnalyticsOut)
def enquiry_analytics(
    property_id: Optional[UUID] = None,
    seller_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Return count, reply rate, and median first response for any scope."""
    mark_unanswered_threads(db)

    filters = []
    if property_id:
        filters.append(Conversation.property_id == property_id)
    if seller_id:
        filters.append(Conversation.seller_id == seller_id)

    total = db.execute(
        select(func.count(Conversation.id)).where(*filters)
    ).scalar_one()
    replied = db.execute(
        select(func.count(Conversation.id)).where(
            *filters, Conversation.first_reply_at.is_not(None)
        )
    ).scalar_one()
    unanswered = db.execute(
        select(func.count(Conversation.id)).where(
            *filters, Conversation.status == "unanswered"
        )
    ).scalar_one()
    median = db.execute(
        select(
            func.percentile_cont(0.5).within_group(
                func.extract(
                    "epoch", Conversation.first_reply_at - Conversation.created_at
                )
            )
        ).where(*filters, Conversation.first_reply_at.is_not(None))
    ).scalar_one_or_none()

    return EnquiryAnalyticsOut(
        property_id=property_id,
        seller_id=seller_id,
        enquiries_received=total,
        replied_enquiries=replied,
        unanswered_enquiries=unanswered,
        reply_rate=(replied / total) if total else 0.0,
        median_first_reply_seconds=float(median) if median is not None else None,
    )

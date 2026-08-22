from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class EnquiryAnalyticsOut(BaseModel):
    property_id: Optional[UUID] = None
    seller_id: Optional[UUID] = None
    enquiries_received: int
    replied_enquiries: int
    unanswered_enquiries: int
    reply_rate: float
    median_first_reply_seconds: Optional[float] = None

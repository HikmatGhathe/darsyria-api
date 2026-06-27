from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BillingConfig(BaseModel):
    """Whether listings currently require payment, and the current price."""

    payment_required: bool
    price_amount: Decimal
    price_currency: str


class InvoiceOut(BaseModel):
    id: UUID
    property_id: UUID
    amount: Decimal
    currency: str
    status: str
    provider: str
    created_at: datetime
    due_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AdminInvoiceItem(BaseModel):
    id: UUID
    property_id: UUID
    property_title: str
    owner_id: UUID
    owner_email: str
    amount: Decimal
    currency: str
    status: str
    provider: str
    created_at: datetime
    due_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BillingSettingsUpdate(BaseModel):
    payment_required: Optional[bool] = None
    price_amount: Optional[Decimal] = Field(default=None, gt=0)
    price_currency: Optional[str] = Field(default=None, pattern="^(USD|EUR|SYP)$")

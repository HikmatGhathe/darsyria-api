from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SavedSearchCreate(BaseModel):
    city: Optional[str] = Field(default=None, max_length=100)
    property_type: Optional[str] = Field(
        default=None, pattern="^(apartment|house|land|commercial)$"
    )
    min_price: Optional[Decimal] = Field(default=None, ge=0)
    max_price: Optional[Decimal] = Field(default=None, ge=0)
    rooms: Optional[int] = Field(default=None, ge=0, le=50)
    seller: Optional[str] = Field(default=None, max_length=200)


class SavedSearchOut(BaseModel):
    id: UUID
    city: Optional[str] = None
    property_type: Optional[str] = None
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
    rooms: Optional[int] = None
    seller: Optional[str] = None
    label: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

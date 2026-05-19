from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# What the client sends to create a property
class PropertyCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=20, max_length=10000)

    city: str = Field(min_length=2, max_length=100)
    neighborhood: Optional[str] = Field(default=None, max_length=150)

    price_amount: Decimal = Field(gt=0)
    price_currency: str = Field(default="USD", pattern="^(USD|EUR|SYP)$")

    property_type: str = Field(pattern="^(apartment|house|land|commercial)$")
    rooms: Optional[int] = Field(default=None, ge=0, le=50)
    bathrooms: Optional[int] = Field(default=None, ge=0, le=20)
    area_sqm: Optional[int] = Field(default=None, gt=0, le=100000)

    document_status: str = Field(
        default="none",
        pattern="^(none|claimed|documents_provided)$",
    )


# What the API returns (a single property)
class PropertyOut(BaseModel):
    id: UUID
    owner_id: UUID
    title: str
    description: str
    country: str
    city: str
    neighborhood: Optional[str]
    price_amount: Decimal
    price_currency: str
    property_type: str
    rooms: Optional[int]
    bathrooms: Optional[int]
    area_sqm: Optional[int]
    status: str
    document_status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Lightweight version for list endpoints (less data over the wire)
class PropertyListItem(BaseModel):
    id: UUID
    title: str
    city: str
    neighborhood: Optional[str]
    price_amount: Decimal
    price_currency: str
    property_type: str
    rooms: Optional[int]
    area_sqm: Optional[int]
    document_status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class PropertyImageOut(BaseModel):
    id: UUID
    property_id: UUID
    public_url: str
    original_filename: Optional[str]
    size_bytes: int
    position: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    rejection_reason: Optional[str] = None
    flagged_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    images: list[PropertyImageOut] = []

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
    cover_image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# Update schema: all fields optional, only what's sent gets changed
class PropertyUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=5, max_length=200)
    description: Optional[str] = Field(default=None, min_length=20, max_length=10000)

    city: Optional[str] = Field(default=None, min_length=2, max_length=100)
    neighborhood: Optional[str] = Field(default=None, max_length=150)

    price_amount: Optional[Decimal] = Field(default=None, gt=0)
    price_currency: Optional[str] = Field(default=None, pattern="^(USD|EUR|SYP)$")

    property_type: Optional[str] = Field(default=None, pattern="^(apartment|house|land|commercial)$")
    rooms: Optional[int] = Field(default=None, ge=0, le=50)
    bathrooms: Optional[int] = Field(default=None, ge=0, le=20)
    area_sqm: Optional[int] = Field(default=None, gt=0, le=100000)

    document_status: Optional[str] = Field(
        default=None,
        pattern="^(none|claimed|documents_provided)$",
    )


# ---------------------------------------------------------------------------
# Admin-only schemas
# ---------------------------------------------------------------------------

class PropertyRejectRequest(BaseModel):
    """Body for the admin reject/remove endpoint."""
    reason: str = Field(min_length=10, max_length=2000)


class PropertyAdminListItem(BaseModel):
    """Lightweight row for the admin listings dashboard."""
    id: UUID
    owner_id: UUID
    owner_email: Optional[str] = None
    title: str
    city: str
    price_amount: Decimal
    price_currency: str
    status: str
    document_status: str
    flagged_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

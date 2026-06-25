from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Seller-facing ──────────────────────────────────────────────────────────


class VerificationMe(BaseModel):
    """A user's own company-verification state (no document URLs)."""

    account_type: Optional[str] = None
    verification_status: str  # unverified | pending | verified
    has_company_document: bool = False


class DocumentUploadResponse(BaseModel):
    """Returned after a seller uploads a verification document."""

    document_id: UUID
    kind: str  # company | listing_ownership
    # New status of the thing being verified (user or listing).
    status: str


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


# ── Admin ──────────────────────────────────────────────────────────────────


class AdminPresignedDocument(BaseModel):
    document_id: UUID
    original_filename: Optional[str] = None
    content_type: str
    size_bytes: int
    created_at: datetime
    url: str  # short-lived presigned GET URL


class AdminCompanyVerificationItem(BaseModel):
    user_id: UUID
    email: str
    company_name: Optional[str] = None
    company_website: Optional[str] = None
    verification_status: str
    document_count: int
    submitted_at: Optional[datetime] = None  # newest document's created_at

    model_config = ConfigDict(from_attributes=True)


class AdminListingVerificationItem(BaseModel):
    property_id: UUID
    title: str
    owner_id: UUID
    owner_email: str
    verification_status: str
    document_count: int
    submitted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

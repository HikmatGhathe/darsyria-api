import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Numeric,
    DateTime,
    ForeignKey,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Property(Base):
    __tablename__ = "properties"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Owner — required. CASCADE so a deleted user's listings disappear.
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Listing content
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)

    # Location. Country is restricted to "SY" for now. city/neighborhood are
    # free text; governorate is a structured key (one of Syria's 14) added
    # later, nullable so existing rows are unaffected. latitude/longitude are
    # an optional seller-dropped map pin.
    country = Column(String(2), nullable=False, default="SY")
    governorate = Column(String(40), nullable=True)       # e.g. "damascus", "aleppo"
    city = Column(String(100), nullable=False)            # e.g. "Damascus"
    neighborhood = Column(String(150), nullable=True)     # e.g. "Mezzeh"
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)

    # Price as decimal — kept in USD for v1 because SYP is unstable.
    # Currency stored separately so we can extend later.
    price_amount = Column(Numeric(12, 2), nullable=False)
    price_currency = Column(String(3), nullable=False, default="USD")

    # Physical attributes
    property_type = Column(String(30), nullable=False)    # "apartment", "house", "land", "commercial"
    rooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    area_sqm = Column(Integer, nullable=True)

    # Listing lifecycle
    # draft   - owner is editing, not visible
    # active  - publicly visible
    # sold    - taken off market, kept for record
    # removed - admin-removed (e.g. policy violation) or owner-removed
    status = Column(String(20), nullable=False, default="draft", index=True)

    # Honesty framing — owner declares what documents they have.
    # We DO NOT claim "verified" until we have a verification process.
    # Values: "claimed", "documents_provided", "none"
    document_status = Column(String(30), nullable=False, default="none")

    # Admin-reviewed *ownership* verification for THIS listing (individual
    # sellers only — a company's listings derive trust from the company's own
    # User.verification_status instead). Trust badge only; never gates listing.
    # Values: "unverified" | "pending" | "verified" | "rejected"
    verification_status = Column(
        String(20), nullable=False, default="unverified", server_default="unverified"
    )
    verification_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    verification_rejection_reason = Column(Text, nullable=True)

    # Admin moderation fields
    # rejection_reason: set when an admin rejects/removes a listing
    # flagged_at: timestamp when listing was flagged for review
    # reviewed_at: timestamp when an admin last reviewed the listing
    rejection_reason = Column(Text, nullable=True)
    flagged_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # Set the first time this listing goes draft -> active. Distinct from
    # created_at: a draft can sit unpublished for days, and the "new listing"
    # digest for followers keys off this, not creation time.
    published_at = Column(DateTime(timezone=True), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Property {self.id} {self.title!r} status={self.status}>"


# Composite index for the common "browse" query: city + status + recent
Index(
    "ix_properties_city_status_created",
    Property.city,
    Property.status,
    Property.created_at.desc(),
)

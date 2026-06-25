import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class SavedSearch(Base):
    """
    A buyer's stored set of browse filters, re-runnable with one click and
    matched daily against new listings for the combined daily-update email.
    last_alerted_at is the per-search watermark: a listing is "new" for this
    search when Property.published_at > COALESCE(last_alerted_at, created_at).
    """
    __tablename__ = "saved_searches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Criteria — mirror the browse filters (all optional).
    city = Column(String(100), nullable=True)
    property_type = Column(String(30), nullable=True)
    min_price = Column(Numeric(12, 2), nullable=True)
    max_price = Column(Numeric(12, 2), nullable=True)
    rooms = Column(Integer, nullable=True)
    seller = Column(String(200), nullable=True)

    # Human-readable summary, generated at creation (e.g. "Damascus · Apartment").
    label = Column(String(300), nullable=False)

    last_alerted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SavedSearch user={self.user_id} label={self.label!r}>"

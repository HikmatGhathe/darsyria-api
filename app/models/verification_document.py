import uuid

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class VerificationDocument(Base):
    """A privately-stored document submitted for verification.

    One table serves both verification tracks:
    - ``kind="company"``        — a business-registration document a company
      uploads once at the account level; ``property_id`` is NULL.
    - ``kind="listing_ownership"`` — a title deed / tabu an individual uploads
      for one specific listing; ``property_id`` is set.

    These are sensitive (deeds, IDs, licenses), so the object lives under a
    non-public R2 key prefix and is never given a public URL — admins read it
    only via a short-lived presigned URL.
    """

    __tablename__ = "verification_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    kind = Column(String(30), nullable=False)  # "company" | "listing_ownership"

    # Uploader / owner. CASCADE so a deleted user's documents go with them.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Set only for listing-ownership documents.
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Object key in R2 (under the private "verification/" prefix). No public URL.
    storage_key = Column(String(500), nullable=False)

    original_filename = Column(String(255), nullable=True)
    size_bytes = Column(Integer, nullable=False)
    content_type = Column(String(100), nullable=False)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<VerificationDocument {self.id} kind={self.kind} user={self.user_id}>"

import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class PropertyImage(Base):
    __tablename__ = "property_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Object key in R2 — the path inside the bucket
    storage_key = Column(String(500), nullable=False)

    # Public URL (cached) — computed from R2_PUBLIC_URL + storage_key
    public_url = Column(String(800), nullable=False)

    # Original filename for reference
    original_filename = Column(String(255), nullable=True)

    # File size in bytes (after compression)
    size_bytes = Column(Integer, nullable=False)

    # Display order — lower numbers appear first
    position = Column(Integer, nullable=False, default=0, index=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<PropertyImage {self.id} property={self.property_id} pos={self.position}>"

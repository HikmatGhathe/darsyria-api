import uuid

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class MagicLinkToken(Base):
    __tablename__ = "magic_link_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Email the link was sent to (lowercased on creation)
    email = Column(String(320), nullable=False, index=True)

    # SHA-256 hash of the actual token. The raw token only ever lives
    # in the email link and the verify request - never in the database.
    token_hash = Column(String(64), nullable=False, unique=True, index=True)

    # Lifecycle
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    # Audit
    requested_ip = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<MagicLinkToken email={self.email} used={self.used_at is not None}>"

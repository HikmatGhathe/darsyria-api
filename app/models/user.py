import uuid

from sqlalchemy import Boolean, Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), unique=True, nullable=False, index=True)
    full_name = Column(String(200), nullable=True)
    phone = Column(String(40), nullable=True)
    locale = Column(String(5), nullable=False, default="en")

    # Profile / role
    is_active = Column(Boolean, nullable=False, default=True)
    is_admin = Column(Boolean, nullable=False, default=False)

    # Moderation — set when an admin bans the account
    ban_reason = Column(Text, nullable=True)
    banned_at = Column(DateTime(timezone=True), nullable=True)

    # Set when the user self-deletes their account (GDPR erasure request).
    # The row is kept (not hard-deleted) so other users' conversations with
    # this person stay intact — email/full_name/phone are blanked instead.
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # OAuth provider info (for Google login)
    oauth_provider = Column(String(50), nullable=True)  # "google" or null for magic link
    oauth_subject = Column(String(255), nullable=True)  # provider's user ID

    # Monetization placeholder
    subscription_tier = Column(String(20), nullable=False, default="free")

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<User {self.email}>"

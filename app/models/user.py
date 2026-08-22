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
    # When True, an individual seller has chosen to show their phone publicly
    # on their seller profile. Default False — individuals stay private and
    # only share via the mutual-consent reveal in conversations. Companies
    # show their phone regardless of this flag.
    phone_public = Column(Boolean, nullable=False, default=False, server_default="false")
    locale = Column(String(5), nullable=False, default="en")
    language_preference = Column(String(5), nullable=True)

    # Buyer legal profile. The boolean stays nullable so "not answered" is
    # distinguishable from an explicit "no".
    nationality = Column(String(100), nullable=True)
    country_of_residence = Column(String(100), nullable=True)
    has_dual_citizenship = Column(Boolean, nullable=True)

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

    # Seller identity. account_type is set the first time a user goes to
    # list a property — buyers who never list anything never touch these.
    account_type = Column(String(20), nullable=True)  # "individual" | "company" | NULL
    company_name = Column(String(200), nullable=True)
    company_about = Column(Text, nullable=True)
    company_website = Column(String(300), nullable=True)
    # Required when account_type == "company". Shown publicly on the seller
    # profile (unlike an individual's phone, which stays behind the
    # mutual-consent reveal in conversations) since a business wants to be
    # found and called.
    company_address = Column(Text, nullable=True)

    # Admin-reviewed trust badge — never gates listing/using the platform,
    # only controls whether the "Verified seller" badge shows.
    verification_status = Column(String(20), nullable=False, default="unverified")  # unverified | pending | verified

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

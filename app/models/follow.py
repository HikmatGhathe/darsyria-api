import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Follow(Base):
    """
    A buyer following a seller/company to be notified of new listings.
    last_digest_at is the per-follow watermark: "new" for this follow means
    Property.published_at > COALESCE(last_digest_at, created_at).
    """
    __tablename__ = "follows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    follower_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    followed_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    last_digest_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("follower_id", "followed_user_id", name="uq_follow_follower_followed"),
        # "Who follows seller X" — the query the digest job runs per seller.
        Index("ix_follows_followed_follower", "followed_user_id", "follower_id"),
    )

    def __repr__(self) -> str:
        return f"<Follow follower={self.follower_id} followed={self.followed_user_id}>"

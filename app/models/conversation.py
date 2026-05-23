import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Conversation(Base):
    """
    A messaging thread between exactly two users about exactly one property.
    Per-property threading: (property, buyer, seller) is unique.
    """
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The listing this thread is about. CASCADE: if the property is deleted,
    # the conversation goes too. The messages cascade with it.
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The buyer (the one who started the conversation)
    buyer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The seller (the property owner at the time of conversation creation)
    # NOTE: we snapshot this at creation time. If property ownership transfers
    # later, the conversation stays with the original seller.
    seller_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # PII reveal handshake.
    # When buyer clicks "share my contact": buyer_revealed_at is set.
    # When seller clicks the same: seller_revealed_at is set.
    # Phone numbers are visible to BOTH only when BOTH timestamps are non-null.
    buyer_revealed_at = Column(DateTime(timezone=True), nullable=True)
    seller_revealed_at = Column(DateTime(timezone=True), nullable=True)

    # Bookkeeping. last_message_at is denormalized for cheap sorting in the inbox.
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_message_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Relationships (for SQLAlchemy convenience, not enforced in DB)
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    __table_args__ = (
        # Enforce per-property threading: one conversation per (property, buyer, seller).
        # If the same buyer asks the same seller about the same property again,
        # they get the same existing thread (not a new one).
        UniqueConstraint(
            "property_id", "buyer_id", "seller_id",
            name="uq_conversation_property_buyer_seller",
        ),
        # Fast inbox query: "give me my conversations sorted by last activity"
        Index("ix_conversations_buyer_last_msg", "buyer_id", "last_message_at"),
        Index("ix_conversations_seller_last_msg", "seller_id", "last_message_at"),
    )

    @property
    def both_revealed(self) -> bool:
        """Are phone numbers currently shared between the two parties?"""
        return self.buyer_revealed_at is not None and self.seller_revealed_at is not None

    def __repr__(self) -> str:
        return (
            f"<Conversation {self.id} property={self.property_id} "
            f"buyer={self.buyer_id} seller={self.seller_id}>"
        )

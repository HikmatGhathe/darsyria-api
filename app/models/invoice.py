import uuid

from sqlalchemy import Column, String, Text, Numeric, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Invoice(Base):
    """A charge raised when a seller publishes a listing (while payment is
    required). Payment confirmation is manual for now — an admin marks it paid —
    with a provider field reserved for a real processor (Stripe) later.
    """

    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")

    # unpaid | paid | void
    status = Column(String(20), nullable=False, default="unpaid", index=True)
    # manual (admin-confirmed) for now; "stripe" etc. later.
    provider = Column(String(30), nullable=False, default="manual")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    due_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    paid_by_admin_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Invoice {self.id} {self.amount} {self.currency} status={self.status}>"

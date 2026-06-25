import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Report(Base):
    """
    A user-submitted report of a suspicious listing or seller. Exactly one of
    property_id / reported_user_id is set (enforced at the endpoint). Reports
    feed the admin Reports queue; a reported listing is also auto-flagged into
    the existing moderation flow. A report never auto-hides anything — it marks
    something for human review.
    """
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    reporter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Targets — exactly one is non-null.
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    reported_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    reason = Column(String(20), nullable=False)  # scam | spam | offensive | inaccurate | other
    details = Column(Text, nullable=True)

    status = Column(String(20), nullable=False, default="open", index=True)  # open | resolved | dismissed
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # "Open reports for target X" — the dedup lookup and the admin queue.
        Index("ix_reports_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Report {self.reason} status={self.status}>"

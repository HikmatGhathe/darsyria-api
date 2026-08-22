import uuid

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class InboundEmailEvent(Base):
    """Short-lived audit record for inbound Resend processing."""

    __tablename__ = "inbound_email_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_message_id = Column(String(100), nullable=False, unique=True, index=True)
    webhook_id = Column(String(100), nullable=True, index=True)
    raw_payload = Column(JSONB, nullable=False)
    processing_status = Column(String(30), nullable=False, default="pending")
    rejection_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.conversation import Conversation
from app.models.inbound_email_event import InboundEmailEvent
from app.models.message import Message
from app.models.property import Property
from app.models.user import User
from app.schemas.conversation import BuyerLegalProfile
from app.services.email_service import EmailError
from app.services.enquiry_email_service import send_seller_enquiry, seller_email_locale

logger = logging.getLogger(__name__)

MAX_NEW_THREADS_PER_24_HOURS = 5
MAX_MESSAGES_PER_THREAD_PER_24_HOURS = 20


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def apply_legal_profile(user: User, profile: Optional[BuyerLegalProfile]) -> None:
    if profile is None:
        return
    user.nationality = " ".join(profile.nationality.split())
    user.country_of_residence = " ".join(profile.country_of_residence.split())
    user.has_dual_citizenship = profile.has_dual_citizenship


def has_complete_legal_profile(user: User) -> bool:
    return bool(
        user.nationality
        and user.nationality.strip()
        and user.country_of_residence
        and user.country_of_residence.strip()
        and user.has_dual_citizenship is not None
    )


def new_reply_token() -> str:
    return secrets.token_hex(32)


def reply_token_expiry(now: Optional[datetime] = None) -> datetime:
    return (now or utcnow()) + timedelta(days=settings.reply_token_ttl_days)


def renew_reply_token(conversation: Conversation, now: Optional[datetime] = None) -> None:
    current = now or utcnow()
    if not conversation.reply_token:
        conversation.reply_token = new_reply_token()
    conversation.reply_token_expires_at = reply_token_expiry(current)


def count_recent_buyer_threads(db: Session, buyer_id: UUID, now: datetime) -> int:
    return db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.buyer_id == buyer_id,
            Conversation.created_at >= now - timedelta(hours=24),
        )
    ).scalar_one()


def count_recent_thread_messages(
    db: Session, conversation_id: UUID, now: datetime
) -> int:
    return db.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id,
            Message.created_at >= now - timedelta(hours=24),
        )
    ).scalar_one()


def mark_unanswered_threads(db: Session, now: Optional[datetime] = None) -> int:
    cutoff = (now or utcnow()) - timedelta(days=14)
    result = db.execute(
        update(Conversation)
        .where(
            Conversation.first_reply_at.is_(None),
            Conversation.created_at <= cutoff,
            Conversation.status.in_(("sent", "delivered")),
        )
        .values(status="unanswered")
    )
    db.commit()
    return result.rowcount or 0


def purge_expired_inbound_events(
    db: Session, now: Optional[datetime] = None
) -> int:
    result = db.execute(
        delete(InboundEmailEvent).where(
            InboundEmailEvent.expires_at <= (now or utcnow())
        )
    )
    db.commit()
    return result.rowcount or 0


def relay_buyer_message(message_id: UUID) -> None:
    """Background task that sends one persisted buyer message to the seller."""
    with SessionLocal() as db:
        message = db.get(Message, message_id)
        if not message or message.direction != "buyer_to_seller":
            return
        if message.outbound_email_id or message.delivery_status in {"sent", "delivered"}:
            return

        conversation = db.get(Conversation, message.conversation_id)
        if not conversation:
            return
        seller = db.get(User, conversation.seller_id)
        buyer = db.get(User, conversation.buyer_id)
        prop = db.get(Property, conversation.property_id)
        if not seller or not seller.email or not buyer or not prop:
            message.delivery_status = "failed"
            db.commit()
            logger.error("Cannot relay enquiry message %s: participant or listing missing", message.id)
            return

        if not has_complete_legal_profile(buyer):
            message.delivery_status = "failed"
            db.commit()
            logger.error("Cannot relay enquiry message %s: buyer legal profile incomplete", message.id)
            return

        locale = seller_email_locale(seller.language_preference)
        listing_url = f"{settings.frontend_url}/{locale}/properties/{prop.id}"
        try:
            outbound_id = send_seller_enquiry(
                to_email=seller.email,
                property_title=prop.title,
                buyer_message=message.body,
                buyer_email=buyer.email,
                nationality=buyer.nationality,
                country_of_residence=buyer.country_of_residence,
                has_dual_citizenship=buyer.has_dual_citizenship,
                reply_token=conversation.reply_token,
                listing_url=listing_url,
                locale=locale,
                message_id=str(message.id),
            )
        except EmailError:
            message.delivery_status = "failed"
            db.commit()
            return

        # A fast webhook may have updated this row while the API call was in
        # flight. Refresh before writing so a delivered/failed event is never
        # downgraded back to sent.
        db.refresh(message)
        db.refresh(conversation)
        if not message.outbound_email_id:
            message.outbound_email_id = outbound_id
        if message.delivery_status == "pending":
            message.delivery_status = "sent"
        db.commit()
        logger.info("Relayed enquiry message %s for conversation %s", message.id, conversation.id)

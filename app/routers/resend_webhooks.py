import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Optional
from uuid import UUID

import resend
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal
from app.models.conversation import Conversation
from app.models.inbound_email_event import InboundEmailEvent
from app.models.message import Message
from app.models.property import Property
from app.models.user import User
from app.services.email_reply_service import extract_latest_reply
from app.services.email_service import EmailError
from app.services.enquiry_email_service import (
    buyer_email_locale,
    send_buyer_reply_notification,
)
from app.services.enquiry_service import (
    MAX_MESSAGES_PER_THREAD_PER_24_HOURS,
    count_recent_thread_messages,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

THREAD_ADDRESS = re.compile(r"^thread-([0-9a-f]{64})$")
DELIVERY_STATUS_BY_EVENT = {
    "email.sent": "sent",
    "email.delivered": "delivered",
    "email.delivery_delayed": "delayed",
    "email.failed": "failed",
    "email.bounced": "failed",
}
DELIVERY_STATUS_RANK = {
    "pending": 0,
    "sent": 1,
    "delayed": 2,
    "delivered": 3,
    "failed": 4,
}


class InboundFetchError(Exception):
    pass


def _normalized_email(value: Optional[str]) -> str:
    if not value:
        return ""
    return parseaddr(value)[1].strip().lower()


def _thread_token(recipients: Any) -> Optional[str]:
    values = recipients if isinstance(recipients, list) else [recipients]
    for value in values:
        address = _normalized_email(str(value))
        if "@" not in address:
            continue
        local, domain = address.rsplit("@", 1)
        if domain != settings.inbound_email_domain.lower():
            continue
        match = THREAD_ADDRESS.fullmatch(local)
        if match:
            return match.group(1)
    return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _tag_value(tags: Any, name: str) -> Optional[str]:
    if isinstance(tags, dict):
        value = tags.get(name)
        return str(value) if value is not None else None
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict) and tag.get("name") == name:
                value = tag.get("value")
                return str(value) if value is not None else None
    return None


def _inbound_audit_record(
    db, *, provider_message_id: str, webhook_id: str, event: dict
) -> InboundEmailEvent:
    record = db.execute(
        select(InboundEmailEvent).where(
            InboundEmailEvent.provider_message_id == provider_message_id
        )
    ).scalar_one_or_none()
    if record:
        return record

    record = InboundEmailEvent(
        provider_message_id=provider_message_id,
        webhook_id=webhook_id or None,
        raw_payload=event,
        processing_status="pending",
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.inbound_event_retention_days),
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.execute(
            select(InboundEmailEvent).where(
                InboundEmailEvent.provider_message_id == provider_message_id
            )
        ).scalar_one()
    db.refresh(record)
    return record


def _reject_inbound(db, audit: InboundEmailEvent, reason: str) -> None:
    audit.processing_status = "rejected"
    audit.rejection_reason = reason
    audit.processed_at = datetime.now(timezone.utc)
    db.commit()
    logger.warning(
        "Rejected inbound email %s (%s)", audit.provider_message_id, reason
    )


def _handle_delivery_event(event_type: str, data: dict) -> None:
    outbound_id = data.get("email_id")
    if not outbound_id:
        return
    with SessionLocal() as db:
        message = db.execute(
            select(Message).where(
                Message.outbound_email_id == outbound_id,
                Message.direction == "buyer_to_seller",
            )
        ).scalar_one_or_none()
        if not message:
            tags = data.get("tags") or {}
            if _tag_value(tags, "category") != "seller_enquiry":
                return
            tagged_message_id = _tag_value(tags, "message_id")
            try:
                message = db.get(Message, UUID(str(tagged_message_id)))
            except (TypeError, ValueError, AttributeError):
                message = None
            if message and message.direction != "buyer_to_seller":
                message = None
            if message and not message.outbound_email_id:
                message.outbound_email_id = outbound_id
        if not message:
            return
        incoming_status = DELIVERY_STATUS_BY_EVENT[event_type]
        current_rank = DELIVERY_STATUS_RANK.get(message.delivery_status, -1)
        if DELIVERY_STATUS_RANK[incoming_status] >= current_rank:
            message.delivery_status = incoming_status
        conversation = db.get(Conversation, message.conversation_id)
        if (
            conversation
            and event_type == "email.delivered"
            and conversation.status not in {"replied", "unanswered"}
        ):
            conversation.status = "delivered"
        db.commit()


def _handle_received_event(event: dict, webhook_id: str) -> None:
    data = event.get("data") or {}
    provider_message_id = str(data.get("email_id") or "")
    if not provider_message_id:
        logger.warning("Discarded email.received webhook without email_id")
        return

    with SessionLocal() as db:
        audit = _inbound_audit_record(
            db,
            provider_message_id=provider_message_id,
            webhook_id=webhook_id,
            event=event,
        )
        # Serialize duplicate webhook deliveries on the retained audit row.
        audit = db.execute(
            select(InboundEmailEvent)
            .where(InboundEmailEvent.id == audit.id)
            .with_for_update()
        ).scalar_one()
        if audit.processing_status in {"processed", "rejected"}:
            return

        existing_message = db.execute(
            select(Message).where(Message.inbound_message_id == provider_message_id)
        ).scalar_one_or_none()
        if existing_message:
            audit.processing_status = "processed"
            audit.processed_at = datetime.now(timezone.utc)
            db.commit()
            return

        token = _thread_token(data.get("to", []))
        if not token:
            _reject_inbound(db, audit, "unknown_recipient")
            return

        conversation = db.execute(
            select(Conversation)
            .where(Conversation.reply_token == token)
            .with_for_update()
        ).scalar_one_or_none()
        if not conversation:
            _reject_inbound(db, audit, "unknown_token")
            return

        now = datetime.now(timezone.utc)
        if (
            conversation.reply_token_expires_at
            and _aware(conversation.reply_token_expires_at) <= now
        ):
            _reject_inbound(db, audit, "expired_token")
            return

        seller = db.get(User, conversation.seller_id)
        sender_email = _normalized_email(data.get("from"))
        if not seller or not seller.email or sender_email != seller.email.strip().lower():
            _reject_inbound(db, audit, "sender_mismatch")
            return

        if (
            count_recent_thread_messages(db, conversation.id, now)
            >= MAX_MESSAGES_PER_THREAD_PER_24_HOURS
        ):
            _reject_inbound(db, audit, "thread_rate_limit")
            return

        try:
            received = resend.Emails.Receiving.get(provider_message_id)
        except Exception as exc:
            audit.processing_status = "fetch_failed"
            audit.rejection_reason = "provider_fetch_failed"
            db.commit()
            logger.exception("Could not retrieve inbound email %s", provider_message_id)
            raise InboundFetchError from exc

        body = extract_latest_reply(
            text=received.get("text") if isinstance(received, dict) else None,
            html=received.get("html") if isinstance(received, dict) else None,
        )
        if not body:
            _reject_inbound(db, audit, "empty_reply")
            return

        message = Message(
            conversation_id=conversation.id,
            sender_id=seller.id,
            direction="seller_to_buyer",
            body=body,
            delivery_status="received",
            inbound_message_id=provider_message_id,
        )
        db.add(message)
        conversation.last_message_at = now
        conversation.message_count = (conversation.message_count or 0) + 1
        if conversation.first_reply_at is None:
            conversation.first_reply_at = now
        conversation.status = "replied"
        audit.processing_status = "processed"
        audit.rejection_reason = None
        audit.processed_at = now
        db.commit()
        db.refresh(message)

        buyer = db.get(User, conversation.buyer_id)
        prop = db.get(Property, conversation.property_id)
        if buyer and buyer.email and prop:
            locale = buyer_email_locale(buyer.language_preference, buyer.locale)
            thread_url = f"{settings.frontend_url}/{locale}/inbox/{conversation.id}"
            try:
                send_buyer_reply_notification(
                    to_email=buyer.email,
                    property_title=prop.title,
                    thread_url=thread_url,
                    locale=locale,
                    message_id=str(message.id),
                )
            except EmailError:
                # The reply is already safely persisted; notification failure
                # must not trigger duplicate inbound-message processing.
                pass


def process_resend_event(event: dict, webhook_id: str) -> None:
    event_type = event.get("type")
    if event_type in DELIVERY_STATUS_BY_EVENT:
        _handle_delivery_event(event_type, event.get("data") or {})
    elif event_type == "email.received":
        _handle_received_event(event, webhook_id)


@router.post("/resend")
async def resend_webhook(request: Request):
    if not settings.resend_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook verification is not configured",
        )

    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
        resend.Webhooks.verify(
            {
                "payload": payload,
                "headers": {
                    "id": request.headers.get("svix-id", ""),
                    "timestamp": request.headers.get("svix-timestamp", ""),
                    "signature": request.headers.get("svix-signature", ""),
                },
                "webhook_secret": settings.resend_webhook_secret,
            }
        )
        event = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        logger.warning("Rejected invalid Resend webhook signature or payload")
        raise HTTPException(status_code=400, detail="Invalid webhook")

    try:
        await run_in_threadpool(
            process_resend_event, event, request.headers.get("svix-id", "")
        )
    except InboundFetchError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inbound email is temporarily unavailable",
        )

    return {"received": True}

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.property import Property
from app.models.property_image import PropertyImage
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListItem,
    ConversationOut,
    ConversationParticipant,
    MessageCreate,
    MessageOut,
)
from app.services.enquiry_service import (
    MAX_MESSAGES_PER_THREAD_PER_24_HOURS,
    MAX_NEW_THREADS_PER_24_HOURS,
    apply_legal_profile,
    count_recent_buyer_threads,
    count_recent_thread_messages,
    has_complete_legal_profile,
    mark_unanswered_threads,
    new_reply_token,
    relay_buyer_message,
    renew_reply_token,
    reply_token_expiry,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])

# Preview length for inbox
PREVIEW_LENGTH = 80


def _truncate(text: str, limit: int = PREVIEW_LENGTH) -> str:
    """Truncate a string to limit chars, adding ellipsis if cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _get_user_display_name(user: User) -> Optional[str]:
    """
    Return a display name for a user, if any.
    For now we just use name (we may add a `display_name` field later).
    Returns None if no name available — frontend shows "User" placeholder.
    """
    if user.deleted_at is not None:
        return None
    if user.full_name:
        return user.full_name
    # Do not derive a display name from the seller's private email address.
    return None


def _to_participant(user: User) -> ConversationParticipant:
    return ConversationParticipant(id=user.id, name=_get_user_display_name(user))


@router.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/hour")
def start_conversation(
    payload: ConversationCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a buyer enquiry and queue its first seller email."""
    prop = db.get(Property, payload.property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if prop.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Cannot start a conversation about a non-active property",
        )

    if prop.owner_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot start a conversation about your own property",
        )

    # Serialize creation per buyer so concurrent requests cannot bypass the
    # persisted 5-new-threads-per-24-hours limit.
    buyer = db.execute(
        select(User).where(User.id == current_user.id).with_for_update()
    ).scalar_one()
    apply_legal_profile(buyer, payload.legal_profile)
    if not has_complete_legal_profile(buyer):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "legal_profile_required",
                "message": "Complete nationality, country of residence, and dual-citizenship status before sending.",
            },
        )

    now = datetime.now(timezone.utc)
    seller_id = prop.owner_id
    existing = db.execute(
        select(Conversation)
        .where(
            Conversation.property_id == prop.id,
            Conversation.buyer_id == buyer.id,
            Conversation.seller_id == seller_id,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if existing is not None:
        conversation = existing
        if (
            count_recent_thread_messages(db, conversation.id, now)
            >= MAX_MESSAGES_PER_THREAD_PER_24_HOURS
        ):
            raise HTTPException(
                status_code=429,
                detail="This enquiry has reached its 20-message limit for the last 24 hours.",
            )
    else:
        if count_recent_buyer_threads(db, buyer.id, now) >= MAX_NEW_THREADS_PER_24_HOURS:
            raise HTTPException(
                status_code=429,
                detail="You can start at most 5 new enquiries in 24 hours.",
            )
        conversation = Conversation(
            property_id=prop.id,
            buyer_id=buyer.id,
            seller_id=seller_id,
            reply_token=new_reply_token(),
            reply_token_expires_at=reply_token_expiry(now),
            status="sent",
        )
        db.add(conversation)
        db.flush()

    msg = Message(
        conversation_id=conversation.id,
        sender_id=buyer.id,
        direction="buyer_to_seller",
        body=payload.body.strip(),
        delivery_status="pending",
    )
    db.add(msg)
    conversation.last_message_at = now
    conversation.message_count = (conversation.message_count or 0) + 1
    renew_reply_token(conversation, now)

    db.commit()
    db.refresh(conversation)
    db.refresh(msg)
    background_tasks.add_task(relay_buyer_message, msg.id)

    logger.info(
        "Conversation %s: %s sent initial message to %s about property %s",
        conversation.id,
        buyer.id,
        seller_id,
        prop.id,
    )

    return _build_conversation_out(db, conversation, current_user)


@router.get("", response_model=list[ConversationListItem])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List the current buyer's enquiries, most recently active first.
    """
    mark_unanswered_threads(db)
    stmt = (
        select(Conversation)
        .where(Conversation.buyer_id == current_user.id)
        .order_by(Conversation.last_message_at.desc())
    )
    conversations = db.execute(stmt).scalars().all()

    items: list[ConversationListItem] = []
    for conv in conversations:
        other_user_id = conv.seller_id
        other_user = db.get(User, other_user_id)

        # Property info
        prop = db.get(Property, conv.property_id)
        if prop is None:
            # Property was deleted but conversation cascade should have removed this.
            # Defensive skip.
            continue

        # Cover image
        cover = db.execute(
            select(PropertyImage)
            .where(
                PropertyImage.property_id == conv.property_id,
                PropertyImage.position == 0,
            )
        ).scalar_one_or_none()

        # Latest message for preview
        latest_msg = db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        # Has unread? — any messages in this conversation from the OTHER party with read_at=null
        unread_count = db.execute(
            select(func.count(Message.id))
            .where(
                Message.conversation_id == conv.id,
                Message.direction == "seller_to_buyer",
                Message.read_at.is_(None),
            )
        ).scalar_one()

        items.append(
            ConversationListItem(
                id=conv.id,
                property_id=conv.property_id,
                property_title=prop.title,
                property_cover_url=cover.public_url if cover else None,
                other_party=_to_participant(other_user) if other_user else ConversationParticipant(id=other_user_id),
                last_message_preview=_truncate(latest_msg.body) if latest_msg else None,
                last_message_at=conv.last_message_at,
                has_unread=unread_count > 0,
                status=conv.status,
                message_count=conv.message_count,
                first_reply_at=conv.first_reply_at,
                created_at=conv.created_at,
            )
        )

    return items


# Helper: build a ConversationOut response, including PII reveal handling
def _build_conversation_out(
    db: Session,
    conversation: Conversation,
    viewing_user: User,
) -> ConversationOut:
    """
    Build a ConversationOut, including all messages, with phone numbers
    populated only if both parties have revealed.
    """
    if viewing_user.id != conversation.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can view this enquiry")

    # Load property title
    prop = db.get(Property, conversation.property_id)
    property_title = prop.title if prop else "(removed property)"

    # Load all messages, ordered
    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    ).scalars().all()

    # Determine phone visibility
    both_revealed = (
        conversation.buyer_revealed_at is not None
        and conversation.seller_revealed_at is not None
    )

    buyer_phone = None
    seller_phone = None
    if both_revealed:
        buyer = db.get(User, conversation.buyer_id)
        seller = db.get(User, conversation.seller_id)
        # Users may or may not have a phone field — handle gracefully
        buyer_phone = getattr(buyer, "phone", None) if buyer else None
        seller_phone = getattr(seller, "phone", None) if seller else None

    return ConversationOut(
        id=conversation.id,
        property_id=conversation.property_id,
        property_title=property_title,
        buyer_id=conversation.buyer_id,
        seller_id=conversation.seller_id,
        status=conversation.status,
        message_count=conversation.message_count,
        first_reply_at=conversation.first_reply_at,
        buyer_revealed_at=conversation.buyer_revealed_at,
        seller_revealed_at=conversation.seller_revealed_at,
        both_revealed=both_revealed,
        buyer_phone=buyer_phone,
        seller_phone=seller_phone,
        messages=[MessageOut.model_validate(m) for m in messages],
        created_at=conversation.created_at,
        last_message_at=conversation.last_message_at,
    )


@router.get("/{conversation_id:uuid}", response_model=ConversationOut)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a buyer's enquiry thread with all its messages.
    """
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return _build_conversation_out(db, conv, current_user)


# ---------------------------------------------------------------------------
# Send message
# ---------------------------------------------------------------------------

@router.post(
    "/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("60/hour")
def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Send another buyer message and relay it under the same reply token.
    """
    conv = db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .with_for_update()
    ).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if current_user.id != conv.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can send from the web thread")

    if not has_complete_legal_profile(current_user):
        raise HTTPException(
            status_code=400,
            detail={"code": "legal_profile_required"},
        )

    now = datetime.now(timezone.utc)
    if (
        count_recent_thread_messages(db, conv.id, now)
        >= MAX_MESSAGES_PER_THREAD_PER_24_HOURS
    ):
        raise HTTPException(
            status_code=429,
            detail="This enquiry has reached its 20-message limit for the last 24 hours.",
        )

    msg = Message(
        conversation_id=conv.id,
        sender_id=current_user.id,
        direction="buyer_to_seller",
        body=payload.body.strip(),
        delivery_status="pending",
    )
    db.add(msg)

    conv.last_message_at = now
    conv.message_count = (conv.message_count or 0) + 1
    renew_reply_token(conv, now)

    db.commit()
    db.refresh(msg)
    background_tasks.add_task(relay_buyer_message, msg.id)

    logger.info(
        "Conversation %s: message %s sent by %s",
        conv.id,
        msg.id,
        current_user.id,
    )

    return msg


# ---------------------------------------------------------------------------
# Mark messages as read
# ---------------------------------------------------------------------------

@router.post(
    "/{conversation_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
)
def mark_conversation_read(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Mark all unread messages in this conversation as read by the current user.
    Specifically: marks messages from the OTHER party that have read_at=null.
    Idempotent.
    """
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if current_user.id != conv.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can read this enquiry")

    now = datetime.now(timezone.utc)

    # Bulk update: all messages in this conversation from the OTHER party that are unread
    result = db.execute(
        Message.__table__.update()
        .where(
            Message.conversation_id == conv.id,
            Message.direction == "seller_to_buyer",
            Message.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.commit()

    logger.info(
        "Conversation %s: %s marked %d messages as read",
        conv.id,
        current_user.id,
        result.rowcount,
    )
    return None


# ---------------------------------------------------------------------------
# Reveal phone number (consent handshake)
# ---------------------------------------------------------------------------

@router.post("/{conversation_id}/reveal", response_model=ConversationOut)
def reveal_contact(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Current user opts in to share their phone number with the other party.

    Reveal mechanics:
    - Sets buyer_revealed_at or seller_revealed_at (whichever role you have).
    - Both phones become visible in the response only when BOTH timestamps are set.
    - Idempotent: calling twice does nothing.
    - The endpoint always returns the updated conversation, so the frontend
      can immediately reflect "I revealed; waiting for them" or
      "we both revealed, here are the phones".
    """
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if current_user.id not in (conv.buyer_id, conv.seller_id):
        raise HTTPException(status_code=403, detail="Not a participant in this conversation")

    # Require the current user to have a phone number on file.
    # Without it, "revealing" is meaningless.
    if not getattr(current_user, "phone", None):
        raise HTTPException(
            status_code=400,
            detail="Add a phone number to your profile before you can share contacts",
        )

    now = func.now()

    if current_user.id == conv.buyer_id and conv.buyer_revealed_at is None:
        conv.buyer_revealed_at = now
        logger.info("Conversation %s: buyer %s revealed phone", conv.id, current_user.id)
    elif current_user.id == conv.seller_id and conv.seller_revealed_at is None:
        conv.seller_revealed_at = now
        logger.info("Conversation %s: seller %s revealed phone", conv.id, current_user.id)
    # else: already revealed by this party, idempotent no-op

    db.commit()
    db.refresh(conv)

    return _build_conversation_out(db, conv, current_user)


# ---------------------------------------------------------------------------
# Lookup conversation by property (for the "Contact seller" button)
# ---------------------------------------------------------------------------

@router.get("/by-property/{property_id}", response_model=Optional[ConversationOut])
def get_my_conversation_for_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the conversation between current_user (as buyer) and the property's
    owner (as seller), if one exists. Returns null if no conversation has been
    started yet.

    Used by the "Contact seller" button to decide between "Send message" (no
    existing thread) and "Open conversation" (existing thread).
    """
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    # If the current user is the owner, they're not a "buyer" — return null
    if prop.owner_id == current_user.id:
        return None

    conv = db.execute(
        select(Conversation).where(
            Conversation.property_id == property_id,
            Conversation.buyer_id == current_user.id,
            Conversation.seller_id == prop.owner_id,
        )
    ).scalar_one_or_none()

    if not conv:
        return None

    return _build_conversation_out(db, conv, current_user)

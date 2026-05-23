import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])

# Rate limits (per user, per hour)
MAX_CONVERSATIONS_PER_HOUR = 10
MAX_MESSAGES_PER_HOUR = 30

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
    if user.full_name:
        return user.full_name
    # Fall back to the local part of the email, never the full email
    if user.email:
        return user.email.split("@")[0]
    return None


def _to_participant(user: User) -> ConversationParticipant:
    return ConversationParticipant(id=user.id, name=_get_user_display_name(user))


@router.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
def start_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Start a new conversation by sending an initial message to a property owner.

    Behavior:
    - Buyer (current_user) sends a message about a property.
    - Seller is inferred from property.owner_id.
    - If a conversation already exists between this (property, buyer, seller),
      the new message is appended to it instead of creating a duplicate.
    - Buyer cannot start a conversation with themselves about their own property.
    - Property must be active (not draft).
    """
    # Look up the property
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

    # Rate limit: how many conversations has this user started in the last hour?
    from datetime import timedelta
    one_hour_ago = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)

    recent_conversation_count = db.execute(
        select(func.count(Conversation.id))
        .where(
            Conversation.buyer_id == current_user.id,
            Conversation.created_at >= one_hour_ago,
        )
    ).scalar_one()

    if recent_conversation_count >= MAX_CONVERSATIONS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="You have started too many conversations in the last hour. Try again later.",
        )

    seller_id = prop.owner_id

    # Try to find an existing conversation for (property, buyer, seller).
    # The unique constraint on the DB enforces this, but we look up first
    # to avoid raising IntegrityError on the common "already exists" path.
    existing = db.execute(
        select(Conversation).where(
            Conversation.property_id == prop.id,
            Conversation.buyer_id == current_user.id,
            Conversation.seller_id == seller_id,
        )
    ).scalar_one_or_none()

    if existing is not None:
        conversation = existing
    else:
        conversation = Conversation(
            property_id=prop.id,
            buyer_id=current_user.id,
            seller_id=seller_id,
        )
        db.add(conversation)
        try:
            db.flush()  # assigns conversation.id without committing
        except IntegrityError:
            # Race condition: another request inserted the same (property, buyer, seller).
            # Roll back and fetch the existing one.
            db.rollback()
            conversation = db.execute(
                select(Conversation).where(
                    Conversation.property_id == prop.id,
                    Conversation.buyer_id == current_user.id,
                    Conversation.seller_id == seller_id,
                )
            ).scalar_one()

    # Insert the initial message
    msg = Message(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        body=payload.body.strip(),
    )
    db.add(msg)

    # Touch the conversation's last_message_at
    conversation.last_message_at = func.now()

    db.commit()
    db.refresh(conversation)

    logger.info(
        "Conversation %s: %s sent initial message to %s about property %s",
        conversation.id,
        current_user.id,
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
    List all conversations the current user is part of (as buyer or seller).
    Sorted by most recent activity first.
    """
    # All conversations where the user is either buyer or seller
    stmt = (
        select(Conversation)
        .where(
            or_(
                Conversation.buyer_id == current_user.id,
                Conversation.seller_id == current_user.id,
            )
        )
        .order_by(Conversation.last_message_at.desc())
    )
    conversations = db.execute(stmt).scalars().all()

    items: list[ConversationListItem] = []
    for conv in conversations:
        # The other party
        is_buyer = conv.buyer_id == current_user.id
        other_user_id = conv.seller_id if is_buyer else conv.buyer_id
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
                Message.sender_id != current_user.id,
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
    # Authorize: viewing_user must be either buyer or seller
    if viewing_user.id not in (conversation.buyer_id, conversation.seller_id):
        raise HTTPException(status_code=403, detail="Not a participant in this conversation")

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
        buyer_revealed_at=conversation.buyer_revealed_at,
        seller_revealed_at=conversation.seller_revealed_at,
        both_revealed=both_revealed,
        buyer_phone=buyer_phone,
        seller_phone=seller_phone,
        messages=[MessageOut.model_validate(m) for m in messages],
        created_at=conversation.created_at,
        last_message_at=conversation.last_message_at,
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a conversation thread with all its messages.
    Only participants (buyer or seller) can view it.
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
def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Send a message in an existing conversation.
    Only participants can send. Rate-limited per user per hour.
    """
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if current_user.id not in (conv.buyer_id, conv.seller_id):
        raise HTTPException(status_code=403, detail="Not a participant in this conversation")

    # Rate limit: how many messages has this user sent across all conversations in the last hour?
    from datetime import timedelta
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    recent_message_count = db.execute(
        select(func.count(Message.id))
        .where(
            Message.sender_id == current_user.id,
            Message.created_at >= one_hour_ago,
        )
    ).scalar_one()

    if recent_message_count >= MAX_MESSAGES_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="You have sent too many messages in the last hour. Try again later.",
        )

    msg = Message(
        conversation_id=conv.id,
        sender_id=current_user.id,
        body=payload.body.strip(),
    )
    db.add(msg)

    # Update last_message_at on the conversation
    conv.last_message_at = func.now()

    db.commit()
    db.refresh(msg)

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

    if current_user.id not in (conv.buyer_id, conv.seller_id):
        raise HTTPException(status_code=403, detail="Not a participant in this conversation")

    now = datetime.now(timezone.utc)

    # Bulk update: all messages in this conversation from the OTHER party that are unread
    result = db.execute(
        Message.__table__.update()
        .where(
            Message.conversation_id == conv.id,
            Message.sender_id != current_user.id,
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

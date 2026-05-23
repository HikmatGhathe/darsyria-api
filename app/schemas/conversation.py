from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# ---------- Message ----------

class MessageOut(BaseModel):
    """A single message in a conversation thread."""
    id: UUID
    conversation_id: UUID
    sender_id: UUID
    body: str
    read_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    """Payload to send a new message in an existing conversation."""
    body: str = Field(min_length=1, max_length=4000)


# ---------- Conversation ----------

class ConversationParticipant(BaseModel):
    """
    Light view of a user shown as a participant in a conversation.
    We deliberately don't include email, phone, or any PII here —
    those are revealed separately via the consent handshake.
    """
    id: UUID
    name: Optional[str] = None  # display name, if user has set one

    model_config = ConfigDict(from_attributes=True)


class ConversationListItem(BaseModel):
    """
    Item in the user's inbox. Shows the OTHER party (not yourself) and the latest activity.
    """
    id: UUID
    property_id: UUID
    property_title: str
    property_cover_url: Optional[str] = None

    # The other party (buyer sees seller, seller sees buyer)
    other_party: ConversationParticipant

    # Latest message body, truncated for preview
    last_message_preview: Optional[str] = None
    last_message_at: datetime

    # Has this user read the latest message? Used to show unread badges.
    has_unread: bool

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationOut(BaseModel):
    """
    Full conversation view: the two parties, the property, all messages.
    Returned by GET /conversations/{id}.
    """
    id: UUID
    property_id: UUID
    property_title: str
    buyer_id: UUID
    seller_id: UUID

    # PII reveal state (one timestamp per party)
    buyer_revealed_at: Optional[datetime]
    seller_revealed_at: Optional[datetime]
    # Convenience flag for the frontend: are BOTH parties revealed?
    both_revealed: bool

    # Phone numbers — only included when both_revealed is True.
    # Otherwise these are None even if the users have phones on file.
    buyer_phone: Optional[str] = None
    seller_phone: Optional[str] = None

    messages: list[MessageOut]

    created_at: datetime
    last_message_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    """Payload to start a new conversation. The buyer sends an initial message."""
    property_id: UUID
    body: str = Field(min_length=1, max_length=4000)

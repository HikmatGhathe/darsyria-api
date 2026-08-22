from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------- Message ----------

class MessageOut(BaseModel):
    """A single message in a conversation thread."""
    id: UUID
    conversation_id: UUID
    sender_id: UUID
    direction: str
    body: str
    delivery_status: str
    read_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    """Payload to send a new message in an existing conversation."""
    body: str = Field(min_length=10, max_length=2000)

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Message must contain at least 10 characters")
        return value


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
    status: str
    message_count: int
    first_reply_at: Optional[datetime] = None

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
    status: str
    message_count: int
    first_reply_at: Optional[datetime] = None

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


class BuyerLegalProfile(BaseModel):
    nationality: str = Field(min_length=2, max_length=100)
    country_of_residence: str = Field(min_length=2, max_length=100)
    has_dual_citizenship: bool

    @field_validator("nationality", "country_of_residence")
    @classmethod
    def normalize_profile_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Profile value must contain at least 2 characters")
        return value


class ConversationCreate(BaseModel):
    """Payload to start a new conversation. The buyer sends an initial message."""
    property_id: UUID
    body: str = Field(min_length=10, max_length=2000)
    legal_profile: Optional[BuyerLegalProfile] = None

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        return MessageCreate(body=value).body

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class ChatMessageInput(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=10000)


class ChatRequest(BaseModel):
    conversation_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="en", pattern="^(ar|de|en)$")
    history: list[ChatMessageInput] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    conversation_id: UUID
    content: str
    model: str
    created_at: datetime

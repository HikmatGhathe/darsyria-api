import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_optional_user
from app.models.chat_message import ChatMessage
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ollama_service import generate_chat_response, OllamaError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def post_chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Send a message to the AI assistant.
    Anonymous users (no JWT) are allowed in v1.0.
    All messages are logged to the database for audit and improvement.
    """
    user_id = current_user.id if current_user else None

    # Persist the user's message
    user_msg = ChatMessage(
        user_id=user_id,
        conversation_id=payload.conversation_id,
        role="user",
        content=payload.message,
        locale=payload.locale,
    )
    db.add(user_msg)
    db.commit()

    # Convert history to plain dicts for Ollama
    history = [{"role": m.role, "content": m.content} for m in payload.history]

    # Call Ollama
    try:
        result = await generate_chat_response(
            user_message=payload.message,
            history=history,
            locale=payload.locale,
        )
    except OllamaError as e:
        logger.error("Ollama failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI assistant is temporarily unavailable. Please try again shortly."
        )

    # Persist the assistant's reply
    assistant_msg = ChatMessage(
        user_id=user_id,
        conversation_id=payload.conversation_id,
        role="assistant",
        content=result["content"],
        locale=payload.locale,
        model=result["model"],
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        latency_ms=result["latency_ms"],
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    return ChatResponse(
        conversation_id=payload.conversation_id,
        content=result["content"],
        model=result["model"],
        created_at=assistant_msg.created_at,
    )

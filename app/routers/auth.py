import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    GenericMessage,
    MagicLinkRequest,
    MagicLinkVerifyRequest,
    UserPublic,
)
from app.services.auth_service import (
    create_access_token,
    create_magic_link_token,
    verify_magic_link_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/magic-link/request", response_model=GenericMessage)
def request_magic_link(
    payload: MagicLinkRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Send a magic login link to the given email.
    Always returns success and does not reveal whether the email exists.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    raw_token = create_magic_link_token(
        db,
        email=payload.email,
        requested_ip=client_ip,
        user_agent=user_agent,
    )

    magic_link = (
        f"{settings.frontend_url}/{payload.locale}/auth/verify"
        f"?token={raw_token}"
    )

    logger.warning("=" * 70)
    logger.warning("MAGIC LINK (development only - would be sent via email)")
    logger.warning("To:    %s", payload.email)
    logger.warning("Link:  %s", magic_link)
    logger.warning("Expires in %d minutes", settings.magic_link_expiration_minutes)
    logger.warning("=" * 70)

    return GenericMessage(message="If the email is valid, a login link has been sent.")


@router.post("/magic-link/verify", response_model=AuthResponse)
def verify_magic_link(
    payload: MagicLinkVerifyRequest,
    db: Session = Depends(get_db),
):
    """Verify a magic link token and return a JWT."""
    user = verify_magic_link_token(db, payload.token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    access_token = create_access_token(user)
    return AuthResponse(
        access_token=access_token,
        user=UserPublic.model_validate(user),
    )


@router.get("/me", response_model=UserPublic)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return UserPublic.model_validate(current_user)


@router.post("/logout", response_model=GenericMessage)
def logout(current_user: User = Depends(get_current_user)):
    """
    Stateless logout: the frontend simply discards the JWT.
    This endpoint exists for symmetry and for future server-side
    session revocation if we ever add it.
    """
    return GenericMessage(message="Logged out")

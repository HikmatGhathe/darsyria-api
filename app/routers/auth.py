import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    GenericMessage,
    MagicLinkRequest,
    MagicLinkVerifyRequest,
    UserPublic,
    UserUpdate,
)
from app.services.auth_service import (
    create_access_token,
    create_magic_link_token,
    verify_magic_link_token,
)
from app.services.email_service import send_magic_link, EmailError
from app.services.google_oauth_service import (
    build_authorization_url,
    consume_oauth_state,
    create_oauth_state,
    exchange_code_for_userinfo,
    find_or_create_google_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _send_magic_link_email(to_email: str, magic_link_url: str, locale: str) -> None:
    """
    Try to send the magic-link email. If it fails, log the link as a
    fallback so the user can still complete sign-in during development.
    Runs as a background task — must not raise, since there's no request
    left to return an error response to.
    """
    try:
        send_magic_link(to_email=to_email, magic_link_url=magic_link_url, locale=locale)
        logger.info("Magic link email sent to %s", to_email)
    except EmailError as e:
        logger.error(
            "Email send failed for %s — falling back to terminal: %s",
            to_email,
            e,
        )
        logger.warning("=" * 70)
        logger.warning("MAGIC LINK (email failed - fallback to terminal)")
        logger.warning("To:    %s", to_email)
        logger.warning("Link:  %s", magic_link_url)
        logger.warning("Expires in %d minutes", settings.magic_link_expiration_minutes)
        logger.warning("=" * 70)


@router.post("/magic-link/request", response_model=GenericMessage)
@limiter.limit("5/hour")
def request_magic_link(
    payload: MagicLinkRequest,
    request: Request,
    background_tasks: BackgroundTasks,
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

    # Send in the background so a slow/down email provider doesn't block
    # the response — the endpoint always returns success immediately.
    background_tasks.add_task(
        _send_magic_link_email,
        to_email=payload.email,
        magic_link_url=magic_link,
        locale=payload.locale,
    )

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


@router.patch("/me", response_model=UserPublic)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update the current user's profile. Only full_name and phone are updatable.
    Other fields (email, is_admin, etc.) are not editable through this endpoint.
    """
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        return current_user

    # Defensive: ignore any keys that aren't in the allow-list
    allowed = {"full_name", "phone", "locale"}
    for field, value in updates.items():
        if field not in allowed:
            continue
        # Normalize empty strings to None so the DB stores NULL instead of ""
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                value = None
        setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)

    logger.info(
        "User %s updated profile (fields: %s)",
        current_user.id,
        list(updates.keys()),
    )
    return current_user


@router.post("/logout", response_model=GenericMessage)
def logout(current_user: User = Depends(get_current_user)):
    """
    Stateless logout: the frontend simply discards the JWT.
    This endpoint exists for symmetry and for future server-side
    session revocation if we ever add it.
    """
    return GenericMessage(message="Logged out")


@router.get("/google/login")
def google_login(locale: str = "en", db: Session = Depends(get_db)):
    """
    Start the Google OAuth flow.
    Returns the URL the frontend should redirect the user to.
    """
    if locale not in ("ar", "de", "en"):
        locale = "en"

    state = create_oauth_state(db, locale=locale)
    url = build_authorization_url(state)
    return {"authorization_url": url}


@router.get("/google/callback")
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Finish Google OAuth, issue our JWT, and redirect back to the frontend.
    """
    if error or not code or not state:
        return RedirectResponse(
            url=f"{settings.frontend_url}/en/auth/verify?error=oauth_failed",
            status_code=302,
        )

    locale = consume_oauth_state(db, state)
    if not locale:
        return RedirectResponse(
            url=f"{settings.frontend_url}/en/auth/verify?error=invalid_state",
            status_code=302,
        )

    userinfo = exchange_code_for_userinfo(code)
    if not userinfo or "sub" not in userinfo or "email" not in userinfo:
        return RedirectResponse(
            url=f"{settings.frontend_url}/{locale}/auth/verify?error=oauth_failed",
            status_code=302,
        )

    user = find_or_create_google_user(db, userinfo)
    if not user.is_active:
        return RedirectResponse(
            url=f"{settings.frontend_url}/{locale}/auth/verify?error=account_disabled",
            status_code=302,
        )

    access_token = create_access_token(user)
    return RedirectResponse(
        url=f"{settings.frontend_url}/{locale}/auth/verify#access_token={access_token}",
        status_code=302,
    )

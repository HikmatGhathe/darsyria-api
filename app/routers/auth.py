import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.cookies import REFRESH_TOKEN_COOKIE, clear_auth_cookies, set_auth_cookies
from app.database import get_db
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.conversation import Conversation
from app.models.property import Property
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
    anonymize_and_delete_account,
    create_access_token,
    create_magic_link_token,
    create_refresh_token,
    revoke_refresh_token,
    verify_and_rotate_refresh_token,
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
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify a magic link token and set the auth cookies."""
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
    refresh_token = create_refresh_token(db, user)
    set_auth_cookies(response, access_token, refresh_token)

    return AuthResponse(user=UserPublic.model_validate(user))


@router.post("/refresh", response_model=AuthResponse)
def refresh_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Exchange a valid refresh-token cookie for a new access token (and a
    rotated refresh token). Called by the frontend when an API request
    comes back 401 because the short-lived access token expired.
    """
    raw_refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not raw_refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    result = verify_and_rotate_refresh_token(db, raw_refresh_token)
    if result is None:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user, new_refresh_token = result
    access_token = create_access_token(user)
    set_auth_cookies(response, access_token, new_refresh_token)

    return AuthResponse(user=UserPublic.model_validate(user))


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
    Update the current user's profile. Only a fixed allow-list of fields is
    editable. Other fields (email, is_admin, verification_status, etc.) are
    not editable through this endpoint.
    """
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        return current_user

    # Defensive: ignore any keys that aren't in the allow-list
    allowed = {
        "full_name", "phone", "locale",
        "account_type", "company_name", "company_about",
        "company_website", "company_address",
    }
    for field, value in updates.items():
        if field not in allowed:
            continue
        # Normalize empty strings to None so the DB stores NULL instead of ""
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                value = None
        setattr(current_user, field, value)

    # Companies are public-facing — name, address, and a phone number are
    # required so the seller profile says something useful, and so the
    # number is real before it's shown to buyers with no consent gate
    # (unlike an individual's phone, which stays behind conversation reveal).
    if current_user.account_type == "company":
        missing = [
            label for label, val in (
                ("company_name", current_user.company_name),
                ("company_address", current_user.company_address),
                ("phone", current_user.phone),
            )
            if not val
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company accounts require: {', '.join(missing)}",
            )
        # First time all required fields are present, queue for admin review.
        if current_user.verification_status == "unverified":
            current_user.verification_status = "pending"

    db.commit()
    db.refresh(current_user)

    logger.info(
        "User %s updated profile (fields: %s)",
        current_user.id,
        list(updates.keys()),
    )
    return current_user


@router.get("/me/export")
def export_my_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GDPR Article 20 (right to data portability): a JSON dump of this
    user's own profile, listings, and conversations (including the
    other party's messages within those conversations, since this user
    was a legitimate recipient of them).
    """
    properties = db.query(Property).filter(Property.owner_id == current_user.id).all()

    conversations = (
        db.query(Conversation)
        .filter(or_(Conversation.buyer_id == current_user.id, Conversation.seller_id == current_user.id))
        .all()
    )

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "id": str(current_user.id),
            "email": current_user.email,
            "full_name": current_user.full_name,
            "phone": current_user.phone,
            "locale": current_user.locale,
            "created_at": current_user.created_at.isoformat(),
            "last_login_at": current_user.last_login_at.isoformat() if current_user.last_login_at else None,
        },
        "properties": [
            {
                "id": str(p.id),
                "title": p.title,
                "city": p.city,
                "price_amount": str(p.price_amount),
                "price_currency": p.price_currency,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
            }
            for p in properties
        ],
        "conversations": [
            {
                "id": str(c.id),
                "property_id": str(c.property_id),
                "role": "buyer" if c.buyer_id == current_user.id else "seller",
                "created_at": c.created_at.isoformat(),
                "messages": [
                    {
                        "sender_id": str(m.sender_id),
                        "sent_by_me": m.sender_id == current_user.id,
                        "body": m.body,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in c.messages
                ],
            }
            for c in conversations
        ],
    }


@router.delete("/me", response_model=GenericMessage)
def delete_my_account(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Self-service account deletion (GDPR right to erasure). Anonymizes the
    user's personal data and unpublishes their listings rather than hard
    deleting the row, so other users' conversations with them stay intact.
    """
    anonymize_and_delete_account(db, current_user)
    clear_auth_cookies(response)

    logger.info("User %s deleted their account", current_user.id)
    return GenericMessage(message="Account deleted")


@router.post("/logout", response_model=GenericMessage)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Revoke the refresh token server-side (so it can't be replayed even if
    leaked) and clear both auth cookies.
    """
    raw_refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if raw_refresh_token:
        revoke_refresh_token(db, raw_refresh_token)

    clear_auth_cookies(response)
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
    refresh_token = create_refresh_token(db, user)

    # Set cookies directly on the redirect response — no token in the URL,
    # so it never appears in browser history or referrer headers.
    redirect = RedirectResponse(
        url=f"{settings.frontend_url}/{locale}/auth/verify?oauth=success",
        status_code=302,
    )
    set_auth_cookies(redirect, access_token, refresh_token)
    return redirect

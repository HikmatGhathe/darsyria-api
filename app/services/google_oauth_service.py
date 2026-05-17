import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.oauth_state import OAuthState
from app.models.user import User


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

STATE_LIFETIME_MINUTES = 10


def create_oauth_state(db: Session, locale: str = "en") -> str:
    """Create a short-lived state value for CSRF protection."""
    state = secrets.token_urlsafe(32)
    db_state = OAuthState(
        state=state,
        provider="google",
        locale=locale,
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=STATE_LIFETIME_MINUTES),
    )
    db.add(db_state)
    db.commit()
    return state


def consume_oauth_state(db: Session, state: str) -> Optional[str]:
    """Consume a valid Google OAuth state and return its locale."""
    db_state = (
        db.query(OAuthState)
        .filter(OAuthState.state == state, OAuthState.provider == "google")
        .with_for_update()
        .first()
    )
    if not db_state:
        return None

    if db_state.expires_at < datetime.now(timezone.utc):
        db.delete(db_state)
        db.commit()
        return None

    locale = db_state.locale
    db.delete(db_state)
    db.commit()
    return locale


def build_authorization_url(state: str) -> str:
    """Build the URL the user is sent to for Google login."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "state": state,
        "prompt": "select_account",
    }
    return str(httpx.URL(GOOGLE_AUTH_URL).copy_merge_params(params))


def exchange_code_for_userinfo(code: str) -> Optional[dict]:
    """
    Exchange Google's authorization code for the user's profile info.
    Returns a dict with at least "sub" and "email", optionally "name".
    """
    with httpx.Client(timeout=10.0) as client:
        token_response = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code != 200:
            return None

        access_token = token_response.json().get("access_token")
        if not access_token:
            return None

        userinfo_response = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_response.status_code != 200:
            return None

        return userinfo_response.json()


def find_or_create_google_user(db: Session, userinfo: dict) -> User:
    """
    Match a Google user to our user table.
    Match priority:
      1. oauth_subject - same Google account
      2. email - link an existing magic-link account
      3. create a new user
    """
    google_sub = userinfo["sub"]
    email = userinfo["email"].strip().lower()
    name = userinfo.get("name")

    user = (
        db.query(User)
        .filter(
            User.oauth_provider == "google",
            User.oauth_subject == google_sub,
        )
        .first()
    )

    if user is None:
        user = db.query(User).filter(User.email == email).first()
        if user is not None:
            user.oauth_provider = "google"
            user.oauth_subject = google_sub

    if user is None:
        user = User(
            email=email,
            full_name=name,
            oauth_provider="google",
            oauth_subject=google_sub,
        )
        db.add(user)

    if not user.full_name and name:
        user.full_name = name

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user

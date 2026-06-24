import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.magic_link_token import MagicLinkToken
from app.models.refresh_token import RefreshToken
from app.models.user import User


# ----- Token hashing -----

def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest. Used to store tokens safely."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# ----- Magic link tokens -----

def create_magic_link_token(
    db: Session,
    email: str,
    requested_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """
    Generate a one-time token for the given email.
    Returns the raw token to be sent in the email link.
    Only the hash is stored.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.magic_link_expiration_minutes
    )

    db_token = MagicLinkToken(
        email=email.strip().lower(),
        token_hash=token_hash,
        expires_at=expires_at,
        requested_ip=requested_ip,
        user_agent=user_agent,
    )
    db.add(db_token)
    db.commit()
    db.refresh(db_token)

    return raw_token


def verify_magic_link_token(db: Session, raw_token: str) -> Optional[User]:
    """
    Verify a raw token. If valid, mark it used, find or create the user,
    and return the user. Returns None on any failure.
    Also opportunistically deletes long-expired tokens.
    """
    now = datetime.now(timezone.utc)

    # Keep recent tokens for short-term audit value, then discard old noise.
    cutoff = now - timedelta(days=7)
    db.query(MagicLinkToken).filter(MagicLinkToken.created_at < cutoff).delete(
        synchronize_session=False
    )

    token_hash = hash_token(raw_token)
    db_token = (
        db.query(MagicLinkToken)
        .filter(MagicLinkToken.token_hash == token_hash)
        .with_for_update()
        .first()
    )
    if not db_token:
        db.commit()
        return None
    if db_token.used_at is not None:
        db.commit()
        return None
    if db_token.expires_at < now:
        db.commit()
        return None

    # Mark the token used while the row is locked to keep verification single-use.
    db_token.used_at = now

    user = db.query(User).filter(User.email == db_token.email).first()
    if user is None:
        user = User(email=db_token.email)
        db.add(user)

    user.last_login_at = now
    db.commit()
    db.refresh(user)

    return user


# ----- JWT session tokens -----

def create_access_token(user: User) -> str:
    """Create a signed JWT for an authenticated session."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "is_admin": user.is_admin,
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.jwt_expiration_minutes)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT. Returns the payload or None if invalid or expired."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None


def get_user_from_token(db: Session, token: str) -> Optional[User]:
    """Decode a JWT and load the corresponding user from the database."""
    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    try:
        parsed_user_id = UUID(user_id)
    except (TypeError, ValueError):
        return None

    return db.query(User).filter(User.id == parsed_user_id).first()


# ----- Refresh tokens -----

def create_refresh_token(db: Session, user: User) -> str:
    """
    Create a new opaque refresh token for the user.
    Returns the raw token to be set in the httpOnly cookie. Only the hash
    is stored.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expiration_days
    )

    db_token = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_token)
    db.commit()

    return raw_token


def verify_and_rotate_refresh_token(
    db: Session, raw_token: str
) -> Optional[Tuple[User, str]]:
    """
    Validate a raw refresh token. If valid, revoke it and issue a new one
    (rotation limits the damage if a token is ever intercepted/replayed).
    Returns (user, new_raw_token) or None if invalid/expired/revoked/user missing.
    """
    now = datetime.now(timezone.utc)
    token_hash = hash_token(raw_token)

    db_token = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .with_for_update()
        .first()
    )
    if not db_token:
        return None
    if db_token.revoked_at is not None:
        return None
    if db_token.expires_at < now:
        return None

    user = db.query(User).filter(User.id == db_token.user_id).first()
    if user is None or not user.is_active:
        return None

    db_token.revoked_at = now
    db.commit()

    new_raw_token = create_refresh_token(db, user)
    return user, new_raw_token


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """Revoke a refresh token (used on logout). Silently no-ops if not found."""
    token_hash = hash_token(raw_token)
    db_token = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if db_token and db_token.revoked_at is None:
        db_token.revoked_at = datetime.now(timezone.utc)
        db.commit()

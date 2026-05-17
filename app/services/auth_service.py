import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.magic_link_token import MagicLinkToken
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

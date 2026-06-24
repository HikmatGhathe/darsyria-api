from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.cookies import ACCESS_TOKEN_COOKIE
from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_user_from_token


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Require a valid access token from the httpOnly cookie. Returns the user.
    Raises 401 if missing, invalid, expired, or user not found.
    """
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = get_user_from_token(db, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "account_suspended",
                "reason": user.ban_reason or "Your account has been suspended.",
            },
        )

    return user


def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require a valid access token and admin privileges."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Return the current user if a valid access token cookie is present,
    otherwise None.
    """
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if token is None:
        return None

    user = get_user_from_token(db, token)
    if user is None or not user.is_active:
        return None

    return user

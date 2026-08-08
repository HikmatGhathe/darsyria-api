from fastapi import Response

from app.config import settings

ACCESS_TOKEN_COOKIE = "darsyria_access_token"
REFRESH_TOKEN_COOKIE = "darsyria_refresh_token"


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set both auth cookies on the response. httpOnly — never readable from JS."""
    domain = settings.cookie_domain
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_expiration_minutes * 60,
        path="/",
        domain=domain,
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.refresh_token_expiration_days * 24 * 60 * 60,
        # Scoped to /auth only — the refresh token is never needed outside
        # the refresh/logout endpoints, so don't send it on every request.
        path="/auth",
        domain=domain,
    )


def clear_auth_cookies(response: Response) -> None:
    domain = settings.cookie_domain
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE, path="/", domain=domain)
    response.delete_cookie(key=REFRESH_TOKEN_COOKIE, path="/auth", domain=domain)

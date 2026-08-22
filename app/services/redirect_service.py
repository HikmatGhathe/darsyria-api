from typing import Optional
from urllib.parse import urlsplit


def sanitize_next_path(value: Optional[str]) -> Optional[str]:
    """Accept an internal path only, preventing login-flow open redirects."""
    if not value or len(value) > 500 or not value.startswith("/"):
        return None
    if value.startswith("//") or "\\" in value or any(ord(char) < 32 for char in value):
        return None

    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return None

    result = parsed.path
    if parsed.query:
        result += f"?{parsed.query}"
    return result

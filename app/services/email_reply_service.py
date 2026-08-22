import re
from typing import Optional

from bs4 import BeautifulSoup
from mailparser_reply import EmailReplyParser


MAX_INBOUND_BODY_LENGTH = 2000

ARABIC_QUOTE_HEADERS = (
    re.compile(r"^في\s+.+\s+كتب(?:ت)?\s+.+:\s*$", re.IGNORECASE),
    re.compile(r"^بتاريخ\s+.+\s+كتب(?:ت)?\s+.+:\s*$", re.IGNORECASE),
    re.compile(r"^من:\s*.+$"),
)
GENERIC_QUOTE_HEADERS = (
    re.compile(r"^-{2,}\s*(?:Original Message|Ursprüngliche Nachricht)\s*-{2,}$", re.IGNORECASE),
    re.compile(r"^On\s+.+\s+wrote:\s*$", re.IGNORECASE),
    re.compile(r"^Am\s+.+\s+schrieb\s+.+:\s*$", re.IGNORECASE),
)
SIGNATURE_MARKERS = (
    re.compile(r"^--\s*$"),
    re.compile(r"^Sent from my (?:iPhone|Android).*$", re.IGNORECASE),
    re.compile(r"^Von meinem .+ gesendet$", re.IGNORECASE),
    re.compile(r"^(?:أُرسل|تم الإرسال|مرسل) من .+$"),
)


def html_to_text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for node in soup.select(
        "blockquote, .gmail_quote, .gmail_signature, #divRplyFwdMsg, "
        "[data-smartmail='gmail_signature'], script, style"
    ):
        node.decompose()
    for node in soup.find_all("br"):
        node.replace_with("\n")
    for node in soup.find_all(["p", "div", "li", "tr"]):
        node.append("\n")
    return soup.get_text(" ")


def _cut_known_history(value: str) -> str:
    kept: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if any(pattern.match(stripped) for pattern in (*ARABIC_QUOTE_HEADERS, *GENERIC_QUOTE_HEADERS)):
            break
        if any(pattern.match(stripped) for pattern in SIGNATURE_MARKERS):
            break
        kept.append(line)
    return "\n".join(kept)


def _normalize(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def extract_latest_reply(*, text: Optional[str], html: Optional[str]) -> str:
    """Prefer plain text, then strip common English, German, and Arabic history."""
    source = text.strip() if text and text.strip() else html_to_text(html or "")
    source = _normalize(source)
    if not source:
        return ""

    source = _cut_known_history(source)
    try:
        parsed = EmailReplyParser(languages=["en", "de"]).parse_reply(text=source)
    except Exception:
        parsed = source

    parsed = _normalize(_cut_known_history(parsed or source))
    if len(parsed) > MAX_INBOUND_BODY_LENGTH:
        parsed = parsed[:MAX_INBOUND_BODY_LENGTH].rstrip()
    return parsed

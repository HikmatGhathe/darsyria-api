import html
import logging
import re
from typing import Optional

import resend

from app.config import settings
from app.services.email_service import EmailError

logger = logging.getLogger(__name__)

SUPPORTED_LOCALES = {"ar", "de", "en"}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def seller_email_locale(preference: Optional[str]) -> str:
    return preference if preference in SUPPORTED_LOCALES else "ar"


def buyer_email_locale(preference: Optional[str], account_locale: Optional[str]) -> str:
    if preference in SUPPORTED_LOCALES:
        return preference
    return account_locale if account_locale in SUPPORTED_LOCALES else "en"


def redact_email_addresses(text: str, protected_email: Optional[str] = None) -> str:
    if protected_email:
        text = re.sub(
            re.escape(protected_email),
            "[email hidden by DarSyria]",
            text,
            flags=re.IGNORECASE,
        )
    return EMAIL_PATTERN.sub("[email hidden by DarSyria]", text)


def legal_context_text(
    nationality: str,
    country_of_residence: str,
    has_dual_citizenship: bool,
    locale: str,
) -> str:
    if locale == "de":
        dual = "Ja" if has_dual_citizenship else "Nein"
        return (
            f"Staatsangehörigkeit: {nationality}. Wohnsitzland: {country_of_residence}. "
            f"Doppelte Staatsangehörigkeit: {dual}. Die kaufinteressierte Person hat "
            "die für ihren Status geltenden Eigentumsregeln und erforderlichen "
            "Unterlagen geprüft."
        )
    if locale == "ar":
        dual = "نعم" if has_dual_citizenship else "لا"
        return (
            f"الجنسية: {nationality}. بلد الإقامة: {country_of_residence}. "
            f"يحمل جنسية مزدوجة: {dual}. راجع المشتري قواعد التملك التي تنطبق "
            "على وضعه والمستندات المطلوبة."
        )
    dual = "Yes" if has_dual_citizenship else "No"
    return (
        f"Nationality: {nationality}. Country of residence: {country_of_residence}. "
        f"Dual citizenship: {dual}. The buyer has reviewed the ownership rules "
        "that apply to their status and the required documents."
    )


def _seller_copy(locale: str) -> dict[str, str]:
    copy = {
        "en": {
            "subject": "DarSyria enquiry: {title}",
            "message": "Buyer's message",
            "legal": "Buyer legal context",
            "listing": "View listing",
            "reply": "Reply to this email to answer the buyer through DarSyria.",
            "footer": "DarSyria keeps both email addresses private.",
        },
        "de": {
            "subject": "DarSyria-Anfrage: {title}",
            "message": "Nachricht der kaufinteressierten Person",
            "legal": "Rechtlicher Kontext der kaufinteressierten Person",
            "listing": "Inserat ansehen",
            "reply": "Antworten Sie auf diese E-Mail, um über DarSyria zu antworten.",
            "footer": "DarSyria hält beide E-Mail-Adressen privat.",
        },
        "ar": {
            "subject": "استفسار عبر دار سوريا: {title}",
            "message": "رسالة المشتري",
            "legal": "الوضع القانوني للمشتري",
            "listing": "عرض الإعلان",
            "reply": "اضغط على «رد» في بريدك للإجابة على المشتري عبر دار سوريا.",
            "footer": "تحافظ دار سوريا على خصوصية عنواني البريد الإلكتروني.",
        },
    }
    return copy[locale]


def _seller_enquiry_html(
    *, locale: str, message: str, legal_context: str, listing_url: str
) -> str:
    c = _seller_copy(locale)
    direction = "rtl" if locale == "ar" else "ltr"
    alignment = "right" if locale == "ar" else "left"
    safe_message = html.escape(message).replace("\n", "<br>")
    safe_context = html.escape(legal_context)
    safe_url = html.escape(listing_url, quote=True)
    return f"""<!doctype html>
<html lang="{locale}" dir="{direction}">
<body style="margin:0;background:#f5f6f7;font-family:Arial,sans-serif;color:#172033;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border:1px solid #dfe3e8;border-radius:8px;">
      <tr><td style="padding:28px;text-align:{alignment};">
        <h2 style="font-size:14px;margin:0 0 10px;color:#536070;">{c['message']}</h2>
        <div style="font-size:16px;line-height:1.65;white-space:normal;margin-bottom:28px;">{safe_message}</div>
        <h2 style="font-size:14px;margin:0 0 10px;color:#536070;">{c['legal']}</h2>
        <p style="font-size:14px;line-height:1.65;margin:0 0 28px;">{safe_context}</p>
        <a href="{safe_url}" style="display:inline-block;padding:11px 18px;background:#18324a;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;">{c['listing']}</a>
        <p style="font-size:13px;line-height:1.55;margin:28px 0 8px;color:#536070;">{c['reply']}</p>
        <p style="font-size:12px;line-height:1.55;margin:0;color:#7a8491;">{c['footer']}</p>
      </td></tr>
    </table>
  </td></tr></table>
</body></html>"""


def _seller_enquiry_text(
    *, locale: str, message: str, legal_context: str, listing_url: str
) -> str:
    c = _seller_copy(locale)
    return (
        f"{c['message']}\n\n{message}\n\n"
        f"{c['legal']}\n\n{legal_context}\n\n"
        f"{c['listing']}: {listing_url}\n\n{c['reply']}\n{c['footer']}"
    )


def _result_id(result: object) -> str:
    if isinstance(result, dict) and result.get("id"):
        return str(result["id"])
    getter = getattr(result, "get", None)
    if getter and getter("id"):
        return str(getter("id"))
    raise EmailError("Resend did not return an email id")


def send_seller_enquiry(
    *,
    to_email: str,
    property_title: str,
    buyer_message: str,
    buyer_email: str,
    nationality: str,
    country_of_residence: str,
    has_dual_citizenship: bool,
    reply_token: str,
    listing_url: str,
    locale: str,
    message_id: str,
) -> str:
    """Relay a buyer message without exposing the buyer's email address."""
    locale = seller_email_locale(locale)
    c = _seller_copy(locale)
    safe_message = redact_email_addresses(buyer_message, buyer_email)
    legal_context = redact_email_addresses(
        legal_context_text(
            nationality, country_of_residence, has_dual_citizenship, locale
        ),
        buyer_email,
    )
    from_address = f"{settings.email_from_name} <{settings.email_from}>"
    reply_to = f"thread-{reply_token}@{settings.inbound_email_domain}"

    try:
        result = resend.Emails.send(
            {
                "from": from_address,
                "to": to_email,
                "reply_to": reply_to,
                "subject": c["subject"].format(title=property_title),
                "html": _seller_enquiry_html(
                    locale=locale,
                    message=safe_message,
                    legal_context=legal_context,
                    listing_url=listing_url,
                ),
                "text": _seller_enquiry_text(
                    locale=locale,
                    message=safe_message,
                    legal_context=legal_context,
                    listing_url=listing_url,
                ),
                "tags": [
                    {"name": "category", "value": "seller_enquiry"},
                    {"name": "message_id", "value": message_id},
                ],
            },
            {"idempotency_key": f"seller-enquiry-{message_id}"},
        )
    except Exception as exc:
        logger.exception("Resend failed to relay enquiry message %s", message_id)
        raise EmailError(f"Could not relay seller enquiry: {exc}") from exc

    return _result_id(result)


def send_buyer_reply_notification(
    *,
    to_email: str,
    property_title: str,
    thread_url: str,
    locale: str,
    message_id: str,
) -> str:
    copy = {
        "en": {
            "subject": "The seller replied on DarSyria: {title}",
            "body": "The seller has replied to your enquiry.",
            "action": "Open enquiry",
        },
        "de": {
            "subject": "Der Verkäufer hat auf DarSyria geantwortet: {title}",
            "body": "Der Verkäufer hat auf Ihre Anfrage geantwortet.",
            "action": "Anfrage öffnen",
        },
        "ar": {
            "subject": "ردّ البائع عبر دار سوريا: {title}",
            "body": "وصل رد من البائع على استفسارك.",
            "action": "فتح الاستفسار",
        },
    }
    locale = locale if locale in SUPPORTED_LOCALES else "en"
    c = copy[locale]
    direction = "rtl" if locale == "ar" else "ltr"
    alignment = "right" if locale == "ar" else "left"
    safe_url = html.escape(thread_url, quote=True)
    html_body = f"""<!doctype html><html lang="{locale}" dir="{direction}"><body style="font-family:Arial,sans-serif;text-align:{alignment};"><p>{c['body']}</p><p><a href="{safe_url}">{c['action']}</a></p></body></html>"""
    text_body = f"{c['body']}\n\n{c['action']}: {thread_url}"

    try:
        result = resend.Emails.send(
            {
                "from": f"{settings.email_from_name} <{settings.email_from}>",
                "to": to_email,
                "subject": c["subject"].format(title=property_title),
                "html": html_body,
                "text": text_body,
                "tags": [
                    {"name": "category", "value": "buyer_reply_notification"},
                    {"name": "message_id", "value": message_id},
                ],
            },
            {"idempotency_key": f"buyer-reply-notification-{message_id}"},
        )
    except Exception as exc:
        logger.exception("Resend failed to notify buyer for message %s", message_id)
        raise EmailError(f"Could not notify buyer: {exc}") from exc

    return _result_id(result)

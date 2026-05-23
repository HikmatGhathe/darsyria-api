"""
Email service. Wraps Resend's SDK for transactional emails.

Currently only one email type: magic link sign-in.
More types (welcome, message notifications, etc.) added later.
"""
import logging
from typing import Optional

import resend

from app.config import settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Raised when sending an email fails."""


# Initialize the Resend client once at import time
resend.api_key = settings.resend_api_key


# Subject lines per locale
SUBJECTS = {
    "en": "Sign in to DarSyria",
    "de": "Bei DarSyria anmelden",
    "ar": "تسجيل الدخول إلى دار سوريا",
}


def _magic_link_html(locale: str, magic_link_url: str) -> str:
    """
    Render the magic link email body for the given locale.
    Plain HTML — no external CSS dependencies, renders consistently in all mail clients.
    """
    is_rtl = locale == "ar"
    dir_attr = "rtl" if is_rtl else "ltr"
    text_align = "right" if is_rtl else "left"

    copy = {
        "en": {
            "heading": "Sign in to DarSyria",
            "body": "Click the button below to sign in. This link expires in 15 minutes and can only be used once.",
            "button": "Sign in",
            "fallback": "If the button doesn't work, copy and paste this link into your browser:",
            "footer": "If you didn't request this email, you can safely ignore it.",
            "signature": "— The DarSyria team",
        },
        "de": {
            "heading": "Bei DarSyria anmelden",
            "body": "Klicken Sie auf die Schaltfläche unten, um sich anzumelden. Dieser Link läuft in 15 Minuten ab und kann nur einmal verwendet werden.",
            "button": "Anmelden",
            "fallback": "Falls die Schaltfläche nicht funktioniert, kopieren Sie diesen Link in Ihren Browser:",
            "footer": "Falls Sie diese E-Mail nicht angefordert haben, können Sie sie ignorieren.",
            "signature": "— Das DarSyria-Team",
        },
        "ar": {
            "heading": "تسجيل الدخول إلى دار سوريا",
            "body": "اضغط على الزر أدناه لتسجيل الدخول. ينتهي هذا الرابط خلال ١٥ دقيقة ويمكن استخدامه مرة واحدة فقط.",
            "button": "تسجيل الدخول",
            "fallback": "إذا لم يعمل الزر، انسخ هذا الرابط والصقه في متصفحك:",
            "footer": "إذا لم تطلب هذه الرسالة، يمكنك تجاهلها.",
            "signature": "— فريق دار سوريا",
        },
    }
    c = copy.get(locale, copy["en"])

    return f"""<!DOCTYPE html>
<html dir="{dir_attr}" lang="{locale}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f6f6f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f6f6f6;padding:40px 20px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background-color:#ffffff;border-radius:8px;border:1px solid #e5e5e5;overflow:hidden;">
          <tr>
            <td style="padding:32px;text-align:{text_align};color:#111111;">
              <h1 style="font-size:20px;font-weight:600;margin:0 0 16px 0;color:#111111;">{c['heading']}</h1>
              <p style="font-size:15px;line-height:1.55;margin:0 0 24px 0;color:#444444;">{c['body']}</p>
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background-color:#2563eb;border-radius:6px;">
                    <a href="{magic_link_url}" style="display:inline-block;padding:12px 24px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:500;">{c['button']}</a>
                  </td>
                </tr>
              </table>
              <p style="font-size:13px;line-height:1.5;margin:32px 0 8px 0;color:#888888;">{c['fallback']}</p>
              <p style="font-size:12px;line-height:1.4;margin:0 0 32px 0;color:#2563eb;word-break:break-all;">
                <a href="{magic_link_url}" style="color:#2563eb;text-decoration:none;">{magic_link_url}</a>
              </p>
              <hr style="border:none;border-top:1px solid #e5e5e5;margin:24px 0;">
              <p style="font-size:13px;line-height:1.5;margin:0 0 8px 0;color:#888888;">{c['footer']}</p>
              <p style="font-size:13px;line-height:1.5;margin:0;color:#888888;">{c['signature']}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _magic_link_text(locale: str, magic_link_url: str) -> str:
    """Plain-text version for clients that don't render HTML."""
    copy = {
        "en": f"Sign in to DarSyria\n\nClick this link to sign in (expires in 15 minutes):\n\n{magic_link_url}\n\nIf you didn't request this email, you can safely ignore it.\n\n— The DarSyria team",
        "de": f"Bei DarSyria anmelden\n\nKlicken Sie auf diesen Link zum Anmelden (läuft in 15 Minuten ab):\n\n{magic_link_url}\n\nFalls Sie diese E-Mail nicht angefordert haben, können Sie sie ignorieren.\n\n— Das DarSyria-Team",
        "ar": f"تسجيل الدخول إلى دار سوريا\n\nاضغط على هذا الرابط لتسجيل الدخول (ينتهي خلال ١٥ دقيقة):\n\n{magic_link_url}\n\nإذا لم تطلب هذه الرسالة، يمكنك تجاهلها.\n\n— فريق دار سوريا",
    }
    return copy.get(locale, copy["en"])


def send_magic_link(to_email: str, magic_link_url: str, locale: str = "en") -> None:
    """
    Send a magic-link sign-in email.

    Raises EmailError if Resend rejects the send.
    """
    if locale not in SUBJECTS:
        locale = "en"

    from_address = f"{settings.email_from_name} <{settings.email_from}>"

    try:
        result = resend.Emails.send({
            "from": from_address,
            "to": to_email,
            "subject": SUBJECTS[locale],
            "html": _magic_link_html(locale, magic_link_url),
            "text": _magic_link_text(locale, magic_link_url),
        })
    except Exception as e:
        logger.exception("Resend send failed for %s", to_email)
        raise EmailError(f"Could not send email: {e}") from e

    logger.info(
        "Magic link email sent to %s (resend_id=%s, locale=%s)",
        to_email,
        result.get("id") if isinstance(result, dict) else "?",
        locale,
    )

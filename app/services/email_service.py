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


# ---------------------------------------------------------------------------
# Message notification email
# ---------------------------------------------------------------------------

MESSAGE_SUBJECTS = {
    "en": "New message about {property_title}",
    "de": "Neue Nachricht zu {property_title}",
    "ar": "رسالة جديدة حول {property_title}",
}


def _message_notification_html(
    locale: str,
    sender_name: str,
    property_title: str,
    message_preview: str,
    conversation_url: str,
) -> str:
    """Render the new-message notification email body for the given locale."""
    is_rtl = locale == "ar"
    dir_attr = "rtl" if is_rtl else "ltr"
    text_align = "right" if is_rtl else "left"

    copy = {
        "en": {
            "heading": f"{sender_name} sent you a message",
            "context": f"About: {property_title}",
            "button": "View conversation",
            "footer": "You're receiving this because someone messaged you on DarSyria. Reply on the platform to keep your contact information private.",
            "signature": "— DarSyria",
        },
        "de": {
            "heading": f"{sender_name} hat Ihnen eine Nachricht gesendet",
            "context": f"Zu: {property_title}",
            "button": "Konversation ansehen",
            "footer": "Sie erhalten diese E-Mail, weil Ihnen jemand auf DarSyria geschrieben hat. Antworten Sie über die Plattform, um Ihre Kontaktdaten privat zu halten.",
            "signature": "— DarSyria",
        },
        "ar": {
            "heading": f"{sender_name} أرسل لك رسالة",
            "context": f"بخصوص: {property_title}",
            "button": "عرض المحادثة",
            "footer": "تستلم هذه الرسالة لأن شخصاً قد راسلك عبر دار سوريا. ردّ عبر المنصة للحفاظ على خصوصية معلومات الاتصال الخاصة بك.",
            "signature": "— دار سوريا",
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
              <h1 style="font-size:20px;font-weight:600;margin:0 0 8px 0;color:#111111;">{c['heading']}</h1>
              <p style="font-size:13px;color:#888888;margin:0 0 24px 0;">{c['context']}</p>
              <div style="background-color:#f9fafb;border-{('right' if is_rtl else 'left')}:3px solid #2563eb;padding:16px;border-radius:4px;margin:0 0 24px 0;">
                <p style="font-size:15px;line-height:1.55;margin:0;color:#374151;white-space:pre-wrap;">{message_preview}</p>
              </div>
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background-color:#2563eb;border-radius:6px;">
                    <a href="{conversation_url}" style="display:inline-block;padding:12px 24px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:500;">{c['button']}</a>
                  </td>
                </tr>
              </table>
              <hr style="border:none;border-top:1px solid #e5e5e5;margin:32px 0 16px 0;">
              <p style="font-size:12px;line-height:1.5;margin:0 0 8px 0;color:#888888;">{c['footer']}</p>
              <p style="font-size:12px;line-height:1.5;margin:0;color:#888888;">{c['signature']}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _message_notification_text(
    locale: str,
    sender_name: str,
    property_title: str,
    message_preview: str,
    conversation_url: str,
) -> str:
    """Plain-text version for clients that don't render HTML."""
    if locale == "de":
        return (
            f"{sender_name} hat Ihnen eine Nachricht gesendet\n"
            f"Zu: {property_title}\n\n"
            f"{message_preview}\n\n"
            f"Antworten:\n{conversation_url}\n\n"
            f"— DarSyria"
        )
    if locale == "ar":
        return (
            f"{sender_name} أرسل لك رسالة\n"
            f"بخصوص: {property_title}\n\n"
            f"{message_preview}\n\n"
            f"اضغط هنا للرد:\n{conversation_url}\n\n"
            f"— دار سوريا"
        )
    return (
        f"{sender_name} sent you a message\n"
        f"About: {property_title}\n\n"
        f"{message_preview}\n\n"
        f"Reply:\n{conversation_url}\n\n"
        f"— DarSyria"
    )


def send_message_notification(
    to_email: str,
    sender_name: str,
    property_title: str,
    message_preview: str,
    conversation_url: str,
    locale: str = "en",
) -> None:
    """
    Send a notification email about a new message in a conversation.

    `message_preview` should already be truncated by the caller (~200 chars).
    `conversation_url` is the full URL to view the conversation on the platform.

    Raises EmailError if Resend rejects the send.
    """
    if locale not in MESSAGE_SUBJECTS:
        locale = "en"

    from_address = f"{settings.email_from_name} <{settings.email_from}>"
    subject = MESSAGE_SUBJECTS[locale].format(property_title=property_title)

    try:
        result = resend.Emails.send({
            "from": from_address,
            "to": to_email,
            "subject": subject,
            "html": _message_notification_html(
                locale, sender_name, property_title, message_preview, conversation_url
            ),
            "text": _message_notification_text(
                locale, sender_name, property_title, message_preview, conversation_url
            ),
        })
    except Exception as e:
        logger.exception("Resend send failed for message notification to %s", to_email)
        raise EmailError(f"Could not send notification email: {e}") from e

    logger.info(
        "Message notification sent to %s (resend_id=%s, locale=%s)",
        to_email,
        result.get("id") if isinstance(result, dict) else "?",
        locale,
    )


# ---------------------------------------------------------------------------
# Listing rejection / removal email
# ---------------------------------------------------------------------------

REJECTION_SUBJECTS = {
    "en": "Your DarSyria listing has been removed",
    "de": "Ihr DarSyria-Inserat wurde entfernt",
    "ar": "تم إزالة إعلانك على دار سوريا",
}


def _rejection_html(locale: str, property_title: str, reason: str) -> str:
    """Render the listing-rejection email body for the given locale."""
    is_rtl = locale == "ar"
    dir_attr = "rtl" if is_rtl else "ltr"
    text_align = "right" if is_rtl else "left"

    copy = {
        "en": {
            "heading": "Your listing has been removed",
            "intro": f"Your listing <strong>{property_title}</strong> has been removed by a DarSyria moderator.",
            "reason_label": "Reason:",
            "footer": "If you believe this decision was made in error, please contact support.",
            "signature": "— The DarSyria team",
        },
        "de": {
            "heading": "Ihr Inserat wurde entfernt",
            "intro": f"Ihr Inserat <strong>{property_title}</strong> wurde von einem DarSyria-Moderator entfernt.",
            "reason_label": "Grund:",
            "footer": "Wenn Sie der Meinung sind, dass diese Entscheidung irrtümlich getroffen wurde, wenden Sie sich bitte an den Support.",
            "signature": "— Das DarSyria-Team",
        },
        "ar": {
            "heading": "تم إزالة إعلانك",
            "intro": f"تم إزالة إعلانك <strong>{property_title}</strong> من قبل أحد مشرفي دار سوريا.",
            "reason_label": "السبب:",
            "footer": "إذا كنت تعتقد أن هذا القرار كان خطأً، يرجى التواصل مع الدعم.",
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
              <p style="font-size:15px;line-height:1.55;margin:0 0 16px 0;color:#444444;">{c['intro']}</p>
              <p style="font-size:13px;font-weight:600;margin:0 0 8px 0;color:#111111;">{c['reason_label']}</p>
              <div style="background-color:#fef2f2;border-left:3px solid #dc2626;padding:12px 16px;border-radius:4px;margin:0 0 24px 0;">
                <p style="font-size:14px;line-height:1.55;margin:0;color:#7f1d1d;white-space:pre-wrap;">{reason}</p>
              </div>
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


def _rejection_text(locale: str, property_title: str, reason: str) -> str:
    """Plain-text rejection email."""
    if locale == "de":
        return (
            f"Ihr Inserat wurde entfernt\n\n"
            f"Ihr Inserat \"{property_title}\" wurde von einem DarSyria-Moderator entfernt.\n\n"
            f"Grund:\n{reason}\n\n"
            f"Wenn Sie der Meinung sind, dass dies irrtümlich war, wenden Sie sich bitte an den Support.\n\n"
            f"— Das DarSyria-Team"
        )
    if locale == "ar":
        return (
            f"تم إزالة إعلانك\n\n"
            f"تم إزالة إعلانك \"{property_title}\" من قبل أحد مشرفي دار سوريا.\n\n"
            f"السبب:\n{reason}\n\n"
            f"إذا كنت تعتقد أن هذا كان خطأً، يرجى التواصل مع الدعم.\n\n"
            f"— فريق دار سوريا"
        )
    return (
        f"Your listing has been removed\n\n"
        f"Your listing \"{property_title}\" has been removed by a DarSyria moderator.\n\n"
        f"Reason:\n{reason}\n\n"
        f"If you believe this was an error, please contact support.\n\n"
        f"— The DarSyria team"
    )


def send_rejection_notification(
    to_email: str,
    property_title: str,
    reason: str,
    locale: str = "en",
) -> None:
    """
    Notify a property owner that their listing has been removed by an admin.

    `reason` is the plain-text explanation supplied by the moderator.
    Raises EmailError if Resend rejects the send.
    """
    if locale not in REJECTION_SUBJECTS:
        locale = "en"

    from_address = f"{settings.email_from_name} <{settings.email_from}>"
    subject = REJECTION_SUBJECTS[locale]

    try:
        result = resend.Emails.send({
            "from": from_address,
            "to": to_email,
            "subject": subject,
            "html": _rejection_html(locale, property_title, reason),
            "text": _rejection_text(locale, property_title, reason),
        })
    except Exception as e:
        logger.exception("Resend send failed for rejection notification to %s", to_email)
        raise EmailError(f"Could not send rejection email: {e}") from e

    logger.info(
        "Rejection notification sent to %s (resend_id=%s, locale=%s)",
        to_email,
        result.get("id") if isinstance(result, dict) else "?",
        locale,
    )


# ---------------------------------------------------------------------------
# Combined daily-update email (followed sellers + saved-search matches)
# ---------------------------------------------------------------------------

DAILY_UPDATE_SUBJECTS = {
    "en": "Your DarSyria daily update",
    "de": "Ihr DarSyria-Tagesupdate",
    "ar": "تحديثك اليومي من دار سوريا",
}

# Group headings for the two kinds of section.
_FOLLOW_GROUP_HEADING = {
    "en": "New from sellers you follow",
    "de": "Neu von Verkäufern, denen Sie folgen",
    "ar": "جديد من البائعين الذين تتابعهم",
}
_SEARCH_GROUP_HEADING = {
    "en": "New matches for your saved searches",
    "de": "Neue Treffer für Ihre gespeicherten Suchen",
    "ar": "نتائج جديدة لعمليات البحث المحفوظة",
}
_MORE_LABEL = {"en": "+{n} more", "de": "+{n} weitere", "ar": "+{n} أخرى"}


def _render_sections_html(locale: str, sections: list[dict]) -> str:
    is_rtl = locale == "ar"
    border_side = "right" if is_rtl else "left"
    more_label = _MORE_LABEL[locale]

    blocks = []
    for section in sections:
        items = "".join(
            f"""<div style="padding:10px 0;border-top:1px solid #eeeeee;">
                  <a href="{listing['url']}" style="font-size:14px;font-weight:600;color:#111111;text-decoration:none;">{listing['title']}</a>
                  <p style="font-size:13px;color:#888888;margin:2px 0 0 0;">{listing['location']} · {listing['price']}</p>
                </div>"""
            for listing in section["listings"]
        )
        more = (
            f"""<p style="font-size:12px;color:#888888;margin:8px 0 0 0;">{more_label.format(n=section['more_count'])}</p>"""
            if section["more_count"] > 0
            else ""
        )
        blocks.append(f"""
          <div style="margin:0 0 20px 0;border-{border_side}:3px solid #2563eb;padding:4px 16px;">
            <h3 style="font-size:15px;font-weight:600;margin:0 0 4px 0;color:#111111;">{section['label']}</h3>
            {items}
            {more}
          </div>""")
    return "".join(blocks)


def _render_group_html(locale: str, heading: str, sections: list[dict]) -> str:
    if not sections:
        return ""
    return f"""
      <h2 style="font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;color:#888888;margin:0 0 12px 0;">{heading}</h2>
      {_render_sections_html(locale, sections)}"""


def _daily_update_html(
    locale: str, follow_sections: list[dict], search_sections: list[dict], frontend_url: str
) -> str:
    is_rtl = locale == "ar"
    dir_attr = "rtl" if is_rtl else "ltr"
    text_align = "right" if is_rtl else "left"

    copy = {
        "en": {
            "heading": "Your daily update",
            "button": "Browse all listings",
            "footer": "You're receiving this because you follow sellers or have saved searches on DarSyria. Manage them in your account.",
            "signature": "— The DarSyria team",
        },
        "de": {
            "heading": "Ihr Tagesupdate",
            "button": "Alle Inserate ansehen",
            "footer": "Sie erhalten diese E-Mail, weil Sie Verkäufern folgen oder gespeicherte Suchen auf DarSyria haben. Verwalten Sie diese in Ihrem Konto.",
            "signature": "— Das DarSyria-Team",
        },
        "ar": {
            "heading": "تحديثك اليومي",
            "button": "تصفح جميع الإعلانات",
            "footer": "تستلم هذه الرسالة لأنك تتابع بائعين أو لديك عمليات بحث محفوظة على دار سوريا. يمكنك إدارتها من حسابك.",
            "signature": "— فريق دار سوريا",
        },
    }
    c = copy.get(locale, copy["en"])

    groups = (
        _render_group_html(locale, _FOLLOW_GROUP_HEADING[locale], follow_sections)
        + _render_group_html(locale, _SEARCH_GROUP_HEADING[locale], search_sections)
    )

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
              <h1 style="font-size:20px;font-weight:600;margin:0 0 20px 0;color:#111111;">{c['heading']}</h1>
              {groups}
              <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:8px;">
                <tr>
                  <td style="background-color:#2563eb;border-radius:6px;">
                    <a href="{frontend_url}/{locale}/properties" style="display:inline-block;padding:12px 24px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:500;">{c['button']}</a>
                  </td>
                </tr>
              </table>
              <hr style="border:none;border-top:1px solid #e5e5e5;margin:32px 0 16px 0;">
              <p style="font-size:12px;line-height:1.5;margin:0 0 8px 0;color:#888888;">{c['footer']}</p>
              <p style="font-size:12px;line-height:1.5;margin:0;color:#888888;">{c['signature']}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _render_sections_text(locale: str, sections: list[dict]) -> str:
    more_label = _MORE_LABEL[locale]
    lines = []
    for section in sections:
        lines.append(f"\n{section['label']}")
        for listing in section["listings"]:
            lines.append(f"  - {listing['title']} ({listing['location']}, {listing['price']})\n    {listing['url']}")
        if section["more_count"] > 0:
            lines.append(f"  {more_label.format(n=section['more_count'])}")
    return "\n".join(lines)


def _daily_update_text(
    locale: str, follow_sections: list[dict], search_sections: list[dict], frontend_url: str
) -> str:
    parts = []
    if follow_sections:
        parts.append(_FOLLOW_GROUP_HEADING[locale] + "\n" + _render_sections_text(locale, follow_sections))
    if search_sections:
        parts.append(_SEARCH_GROUP_HEADING[locale] + "\n" + _render_sections_text(locale, search_sections))
    body = "\n\n".join(parts)
    browse_url = f"{frontend_url}/{locale}/properties"

    if locale == "de":
        return f"Ihr Tagesupdate\n\n{body}\n\nAlle Inserate ansehen:\n{browse_url}\n\n— Das DarSyria-Team"
    if locale == "ar":
        return f"تحديثك اليومي\n\n{body}\n\nتصفح جميع الإعلانات:\n{browse_url}\n\n— فريق دار سوريا"
    return f"Your daily update\n\n{body}\n\nBrowse all listings:\n{browse_url}\n\n— The DarSyria team"


def send_daily_update(
    to_email: str,
    follow_sections: list[dict],
    search_sections: list[dict],
    locale: str = "en",
) -> None:
    """
    Send the combined daily-update email. `follow_sections` and
    `search_sections` are each a list of:
        {"label": str, "listings": [{"title", "url", "location", "price"}, ...], "more_count": int}
    At least one group should be non-empty. Raises EmailError on send failure.
    """
    if locale not in DAILY_UPDATE_SUBJECTS:
        locale = "en"

    from_address = f"{settings.email_from_name} <{settings.email_from}>"

    try:
        result = resend.Emails.send({
            "from": from_address,
            "to": to_email,
            "subject": DAILY_UPDATE_SUBJECTS[locale],
            "html": _daily_update_html(locale, follow_sections, search_sections, settings.frontend_url),
            "text": _daily_update_text(locale, follow_sections, search_sections, settings.frontend_url),
        })
    except Exception as e:
        logger.exception("Resend send failed for daily update to %s", to_email)
        raise EmailError(f"Could not send daily update email: {e}") from e

    logger.info(
        "Daily update sent to %s (resend_id=%s, locale=%s, follow=%d, search=%d)",
        to_email,
        result.get("id") if isinstance(result, dict) else "?",
        locale,
        len(follow_sections),
        len(search_sections),
    )

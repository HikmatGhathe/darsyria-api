import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError


REQUIRED_ENV = {
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "SECRET_KEY": "test-secret",
    "JWT_SECRET": "test-jwt-secret",
    "R2_ACCOUNT_ID": "test",
    "R2_ACCESS_KEY_ID": "test",
    "R2_SECRET_ACCESS_KEY": "test",
    "R2_BUCKET_NAME": "test",
    "R2_ENDPOINT_URL": "https://example.invalid",
    "R2_PUBLIC_URL": "https://example.invalid",
    "RESEND_API_KEY": "test",
    "EMAIL_FROM": "test@example.invalid",
}
for key, value in REQUIRED_ENV.items():
    os.environ.setdefault(key, value)


from app.models.user import User
from app.routers.resend_webhooks import _normalized_email, _tag_value, _thread_token
from app.schemas.conversation import BuyerLegalProfile, ConversationCreate, MessageCreate
from app.services.email_reply_service import MAX_INBOUND_BODY_LENGTH, extract_latest_reply
from app.services.enquiry_email_service import (
    legal_context_text,
    redact_email_addresses,
    seller_email_locale,
    send_buyer_reply_notification,
    send_seller_enquiry,
)
from app.services.enquiry_service import (
    apply_legal_profile,
    has_complete_legal_profile,
    new_reply_token,
)
from app.services.redirect_service import sanitize_next_path


class EnquiryRelayTests(unittest.TestCase):
    def test_reply_tokens_are_256_bit_lowercase_hex(self):
        first = new_reply_token()
        second = new_reply_token()
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertNotEqual(first, second)

    def test_legal_profile_requires_an_explicit_dual_citizenship_answer(self):
        user = User(
            email="buyer@example.com",
            nationality="German",
            country_of_residence="Germany",
            has_dual_citizenship=None,
        )
        self.assertFalse(has_complete_legal_profile(user))
        apply_legal_profile(
            user,
            BuyerLegalProfile(
                nationality=" German ",
                country_of_residence=" Germany ",
                has_dual_citizenship=False,
            ),
        )
        self.assertTrue(has_complete_legal_profile(user))
        self.assertEqual(user.nationality, "German")

    def test_buyer_message_contract_is_10_to_2000_characters(self):
        with self.assertRaises(ValidationError):
            MessageCreate(body="too short")
        with self.assertRaises(ValidationError):
            MessageCreate(body=" " * 10)
        MessageCreate(body="x" * 10)
        with self.assertRaises(ValidationError):
            ConversationCreate(property_id=uuid4(), body="x" * 2001)

    def test_return_path_rejects_open_redirects(self):
        self.assertEqual(
            sanitize_next_path("/properties/abc?contact=1"),
            "/properties/abc?contact=1",
        )
        self.assertIsNone(sanitize_next_path("https://evil.example/path"))
        self.assertIsNone(sanitize_next_path("//evil.example/path"))
        self.assertIsNone(sanitize_next_path("/safe\\evil"))

    def test_thread_address_requires_the_configured_domain_and_token_shape(self):
        token = "a" * 64
        self.assertEqual(_thread_token([f"DarSyria <thread-{token}@mail.darsyria.me>"]), token)
        self.assertIsNone(_thread_token([f"thread-{token}@example.com"]))
        self.assertIsNone(_thread_token(["thread-short@mail.darsyria.me"]))
        self.assertEqual(_normalized_email("Seller <SELLER@example.com>"), "seller@example.com")

    def test_resend_tags_support_current_and_legacy_webhook_shapes(self):
        self.assertEqual(_tag_value({"message_id": "123"}, "message_id"), "123")
        self.assertEqual(
            _tag_value([{"name": "message_id", "value": "456"}], "message_id"),
            "456",
        )
        self.assertIsNone(_tag_value([], "message_id"))

    def test_reply_parser_strips_english_german_and_arabic_history(self):
        english = "Yes, it is available.\n\nOn Fri, Buyer wrote:\n> Is it available?"
        german = "Ja, die Wohnung ist frei.\n\nAm Freitag schrieb Buyer:\n> Ist sie frei?"
        arabic = "نعم، العقار متاح.\n\nفي 22 آب 2026 كتب المشتري:\n> هل هو متاح؟"
        self.assertEqual(
            extract_latest_reply(text=english, html=None), "Yes, it is available."
        )
        self.assertEqual(
            extract_latest_reply(text=german, html=None), "Ja, die Wohnung ist frei."
        )
        self.assertEqual(
            extract_latest_reply(text=arabic, html=None), "نعم، العقار متاح."
        )

    def test_reply_parser_converts_html_and_ignores_quote_and_signature(self):
        value = """
        <div>Still available.<br>Viewing on Sunday works.</div>
        <div class="gmail_signature">Seller<br>+49 123</div>
        <blockquote>Earlier message</blockquote>
        """
        parsed = extract_latest_reply(text=None, html=value)
        self.assertIn("Still available.", parsed)
        self.assertIn("Viewing on Sunday works.", parsed)
        self.assertNotIn("Earlier message", parsed)
        self.assertNotIn("+49", parsed)

    def test_reply_parser_caps_persisted_body(self):
        parsed = extract_latest_reply(text="x" * (MAX_INBOUND_BODY_LENGTH + 50), html=None)
        self.assertEqual(len(parsed), MAX_INBOUND_BODY_LENGTH)

    def test_legal_context_is_deterministic_and_seller_defaults_to_arabic(self):
        self.assertEqual(seller_email_locale(None), "ar")
        context = legal_context_text("German", "Germany", True, "en")
        self.assertIn("Nationality: German", context)
        self.assertIn("Dual citizenship: Yes", context)

    def test_seller_email_uses_thread_reply_to_and_redacts_addresses(self):
        token = "b" * 64
        with patch(
            "app.services.enquiry_email_service.resend.Emails.send",
            return_value={"id": "email_123"},
        ) as send:
            result = send_seller_enquiry(
                to_email="seller@example.com",
                property_title="Damascus apartment",
                buyer_message="Please reply to buyer@example.com about the viewing.",
                buyer_email="buyer@example.com",
                nationality="German buyer@example.com",
                country_of_residence="Germany",
                has_dual_citizenship=False,
                reply_token=token,
                listing_url="https://darsyria.me/en/properties/123",
                locale="en",
                message_id=str(uuid4()),
            )

        self.assertEqual(result, "email_123")
        payload = send.call_args.args[0]
        self.assertEqual(payload["reply_to"], f"thread-{token}@mail.darsyria.me")
        self.assertNotIn("buyer@example.com", payload["html"])
        self.assertNotIn("buyer@example.com", payload["text"])
        self.assertLess(payload["text"].index("Buyer's message"), payload["text"].index("Buyer legal context"))
        self.assertLess(payload["text"].index("Buyer legal context"), payload["text"].index("View listing"))
        self.assertEqual(
            redact_email_addresses("buyer@example.com"), "[email hidden by DarSyria]"
        )

    def test_buyer_notification_contains_a_link_but_not_the_reply_body(self):
        with patch(
            "app.services.enquiry_email_service.resend.Emails.send",
            return_value={"id": "email_456"},
        ) as send:
            send_buyer_reply_notification(
                to_email="buyer@example.com",
                property_title="Damascus apartment",
                thread_url="https://darsyria.me/en/inbox/thread-123",
                locale="en",
                message_id=str(uuid4()),
            )

        payload = send.call_args.args[0]
        self.assertIn("https://darsyria.me/en/inbox/thread-123", payload["text"])
        self.assertNotIn("seller reply body", payload["text"])
        self.assertEqual(
            dict((tag["name"], tag["value"]) for tag in payload["tags"])["category"],
            "buyer_reply_notification",
        )


if __name__ == "__main__":
    unittest.main()

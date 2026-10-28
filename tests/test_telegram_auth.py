"""Regression checks for Telegram HMAC authentication.

Run after installing requirements: python -m unittest discover -s tests
No real Telegram token, Telegram ID or Neon database is used.
"""
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, parse_qsl

from fastapi import HTTPException
import server

TEST_BOT_TOKEN = "123456789:local-fixture-not-a-real-telegram-secret"


def signed_init_data(extra=None, *, timestamp=None):
    fields = {
        "auth_date": str(int(time.time()) if timestamp is None else timestamp),
        "user": json.dumps({"id": 92001, "first_name": "Test Explorer"}, separators=(",", ":")),
    }
    fields.update(extra or {})
    secret = hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode(), hashlib.sha256).digest()
    payload = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class TelegramInitDataTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"BOT_TOKEN": TEST_BOT_TOKEN})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_basic_signed_user(self):
        person = server.telegram_identity(signed_init_data())
        self.assertEqual(person["id"], 92001)
        self.assertEqual(person["first_name"], "Test Explorer")

    def test_signed_telegram_avatar_and_privacy_fallback(self):
        user = {"id": 92001, "first_name": "Test Explorer",
                "photo_url": "https://t.me/i/userpic/320/example.jpg"}
        signed = signed_init_data({"user": json.dumps(user, separators=(",", ":"))})
        person = server.telegram_identity(signed)
        self.assertEqual(person["photo_url"], user["photo_url"])

        # Authenticated but absent or restricted photos must become placeholders.
        self.assertIsNone(server.telegram_identity(signed_init_data())["photo_url"])
        for url in ("https://example.org/track.png", "http://t.me/i/userpic/a.jpg",
                    "https://t.me.evil.org/picture.jpg", "javascript:alert(1)",
                    "https://user:pass@t.me/image.jpg", "https://t.me:8443/i/a.jpg"):
            self.assertIsNone(server.trusted_telegram_photo(url), url)

        # Tampering with signed avatar data is rejected, not silently accepted.
        data = dict(parse_qsl(signed))
        user["photo_url"] = "https://example.org/track.png"
        data["user"] = json.dumps(user, separators=(",", ":"))
        with self.assertRaises(HTTPException):
            server.telegram_identity(urlencode(data))

    def test_signature_field_kept_in_bot_hmac(self):
        # Modern Telegram can include Ed25519 signature in initData.
        # Bot-token HMAC includes this field; third-party validation excludes it.
        person = server.telegram_identity(
            signed_init_data({"signature": "ed25519-example-fixture"})
        )
        self.assertEqual(person["id"], 92001)

    def test_tampered_signature_field_is_rejected(self):
        signed = signed_init_data({"signature": "correct"})
        data = dict(parse_qsl(signed))
        data["signature"] = "tampered"
        with self.assertRaises(HTTPException) as exc:
            server.telegram_identity(urlencode(data))
        self.assertEqual(exc.exception.status_code, 401)

    def test_missing_token_is_rejected(self):
        with patch.dict(os.environ, {"BOT_TOKEN": ""}):
            with self.assertRaises(HTTPException) as exc:
                server.telegram_identity(signed_init_data())
        self.assertEqual(exc.exception.status_code, 503)

    def test_expired_timestamp_is_rejected(self):
        with self.assertRaises(HTTPException) as exc:
            server.telegram_identity(signed_init_data(timestamp=int(time.time()) - 172800))
        self.assertEqual(exc.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()

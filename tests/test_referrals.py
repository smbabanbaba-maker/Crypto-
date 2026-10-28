"""PostgreSQL-backed security, referral and reward regression tests.

All users, bot tokens and database records here are ephemeral CI fixtures.
Runs against an isolated PostgreSQL service, NEVER production Neon.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from test_telegram_auth import TEST_BOT_TOKEN, signed_init_data


INVITER = 92001001
INVITEE = 92001002
SECOND_INVITER = 92001003


def headers(user_id, start_param=None):
    from urllib.parse import urlencode
    from test_telegram_auth import signed_init_data as sign
    import hashlib
    import hmac
    import json

    data = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Explorer"}, separators=(",", ":")),
    }
    if start_param:
        data["start_param"] = start_param
    signature_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, signature_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(data)}


class RewardsAndReferrals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.environ.get("DATABASE_URL", "")
        if not dsn:
            raise unittest.SkipTest("DATABASE_URL not provided; PostgreSQL integration test requires isolated CI service")
        # These tests TRUNCATE their database. Fail closed if someone has copied
        # real Neon/Vercel credentials into their local environment by mistake.
        from urllib.parse import urlsplit
        parsed = urlsplit(dsn)
        if (os.environ.get("ZENQORY_ALLOW_DESTRUCTIVE_TESTS") != "1"
                or parsed.scheme not in ("postgres", "postgresql")
                or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                or parsed.path != "/zenqory_test"):
            raise RuntimeError(
                "Refusing destructive integration tests: use only the local "
                "zenqory_test PostgreSQL database with explicit test opt-in"
            )
        os.environ["BOT_TOKEN"] = TEST_BOT_TOKEN
        os.environ["BOT_USERNAME"] = "ZenqoryTestBot"
        server._schema_ready = False
        with server.connect() as conn:
            server.schema(conn)

    def setUp(self):
        self.client = TestClient(server.app)
        with server.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "TRUNCATE zen_referral_intents, zen_activity, zen_tasks, zen_users RESTART IDENTITY CASCADE"
                )

    def test_auth_required_for_rewards(self):
        r = self.client.get("/api/me")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/farm/start")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")

    def test_direct_miniapp_referral_first_claim_only(self):
        inv = self.client.get("/api/me", headers=headers(INVITER))
        self.assertEqual(inv.status_code, 200, inv.text)
        self.assertEqual(inv.json()["refCount"], 0)
        self.assertEqual(
            inv.json()["referralLink"],
            f"https://t.me/ZenqoryTestBot?startapp=ref_{INVITER}"
        )
        self.assertEqual(
            inv.json()["referralBotLink"],
            f"https://t.me/ZenqoryTestBot?start=ref_{INVITER}"
        )
        joined = self.client.get(
            "/api/me", headers=headers(INVITEE, f"ref_{INVITER}")
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        stats = self.client.get("/api/me", headers=headers(INVITER)).json()
        self.assertEqual(stats["refCount"], 1)
        self.assertEqual(stats["activeRefCount"], 0)
        started = self.client.post("/api/farm/start", headers=headers(INVITEE))
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(
            self.client.post("/api/farm/claim", headers=headers(INVITEE)).status_code, 409
        )
        future = int(time.time() * 1000) + server.FARM_MS + 2000
        with patch.object(server, "utc_ms", return_value=future):
            claimed = self.client.post("/api/farm/claim", headers=headers(INVITEE))
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(claimed.json()["balance"], server.FARM_REWARD)
        sponsor = self.client.get("/api/me", headers=headers(INVITER)).json()
        self.assertEqual(sponsor["refCount"], 1)
        self.assertEqual(sponsor["activeRefCount"], 1)
        self.assertEqual(sponsor["refPoints"], server.REFERRAL_REWARD)
        self.assertEqual(sponsor["balance"], server.REFERRAL_REWARD)
        with patch.object(server, "utc_ms", return_value=future + 1):
            self.assertEqual(self.client.post("/api/farm/claim", headers=headers(INVITEE)).status_code, 409)
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITER)).json()["refPoints"], 10)

    def test_bot_start_invitation_fallback_and_first_touch(self):
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITER)).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=headers(SECOND_INVITER)).status_code, 200)
        # Only real Telegram can reach this webhook in production due to secret header.
        secret = server._bot_webhook_secret(TEST_BOT_TOKEN)
        def webhook(ref):
            return self.client.post(
                "/api/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": secret},
                json={"message": {
                    "chat": {"id": INVITEE, "type": "private"},
                    "from": {"id": INVITEE, "first_name": "Friend"},
                    "text": f"/start ref_{ref}"
                }},
            )
        msg = webhook(INVITER)
        self.assertEqual(msg.status_code, 200, msg.text)
        self.assertIn("invitation has been registered", msg.json()["text"])
        self.assertEqual(webhook(SECOND_INVITER).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITEE)).status_code, 200)
        # A later malicious or mistaken referral link cannot rewrite the first sponsor.
        self.assertEqual(
            self.client.get("/api/me", headers=headers(INVITEE, f"ref_{SECOND_INVITER}")).status_code, 200
        )
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITER)).json()["refCount"], 1)
        self.assertEqual(self.client.get("/api/me", headers=headers(SECOND_INVITER)).json()["refCount"], 0)

    def test_first_bot_invite_wins_over_later_direct_link(self):
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITER)).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=headers(SECOND_INVITER)).status_code, 200)
        self.assertTrue(server.remember_bot_invite(INVITEE, f"ref_{INVITER}"))
        # The new user opens a second person's direct Mini App URL later.
        signed_later = self.client.get("/api/me", headers=headers(INVITEE, f"ref_{SECOND_INVITER}"))
        self.assertEqual(signed_later.status_code, 200, signed_later.text)
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITER)).json()["refCount"], 1)
        self.assertEqual(self.client.get("/api/me", headers=headers(SECOND_INVITER)).json()["refCount"], 0)

    def test_invalid_or_self_referral_not_attributed(self):
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITER, f"ref_{INVITER}")).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITEE, "ref_99999999999")).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITER)).json()["refCount"], 0)
        self.assertEqual(self.client.get("/api/me", headers=headers(INVITEE)).json()["refCount"], 0)

    def test_claim_daily_and_task_are_single_use(self):
        hdr = headers(INVITER)
        self.assertEqual(self.client.get("/api/me", headers=hdr).status_code, 200)
        daily = self.client.post("/api/daily", headers=hdr)
        self.assertEqual(daily.status_code, 200, daily.text)
        self.assertEqual(self.client.post("/api/daily", headers=hdr).status_code, 409)
        # Mere clicks cannot generate rewards. Server-recorded progress is required.
        for task_id in server.TASK_REWARDS:
            self.assertEqual(self.client.post(f"/api/tasks/{task_id}", headers=hdr).status_code, 409)
        self.assertEqual(self.client.post("/api/farm/start", headers=hdr).status_code, 200)
        task = self.client.post("/api/tasks/welcome", headers=hdr)
        self.assertEqual(task.status_code, 200, task.text)
        self.assertEqual(self.client.post("/api/tasks/welcome", headers=hdr).status_code, 409)
        self.assertEqual(self.client.post("/api/tasks/safety", headers=hdr).status_code, 409)
        self.assertEqual(self.client.post("/api/tasks/profile", headers=hdr).status_code, 409)
        self.assertEqual(self.client.post("/api/tasks/unknown", headers=hdr).status_code, 404)
        balance = self.client.get("/api/me", headers=hdr).json()["balance"]
        self.assertEqual(balance, server.DAILY_REWARD + server.TASK_REWARDS["welcome"])

    def test_verified_mission_progress_and_rewards(self):
        inviter = headers(INVITER)
        invitee = headers(INVITEE, f"ref_{INVITER}")
        self.assertEqual(self.client.get("/api/me", headers=inviter).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=invitee).status_code, 200)
        self.assertEqual(self.client.post("/api/tasks/safety", headers=inviter).status_code, 409)
        self.assertEqual(self.client.post("/api/tasks/profile", headers=inviter).status_code, 409)
        initial = self.client.get("/api/me", headers=inviter).json()
        self.assertFalse(initial["taskEligibility"]["welcome"])
        self.assertFalse(initial["taskEligibility"]["safety"])
        self.assertFalse(initial["taskEligibility"]["profile"])

        self.assertEqual(self.client.post("/api/farm/start", headers=inviter).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=inviter).json()["taskEligibility"]["welcome"], True)
        self.assertEqual(self.client.post("/api/tasks/welcome", headers=inviter).status_code, 200)
        self.assertEqual(self.client.post("/api/tasks/safety", headers=inviter).status_code, 409)
        self.assertEqual(self.client.post("/api/farm/start", headers=invitee).status_code, 200)
        future = int(time.time() * 1000) + server.FARM_MS + 2500
        with patch.object(server, "utc_ms", return_value=future):
            self.assertEqual(self.client.post("/api/farm/claim", headers=inviter).status_code, 200)
            self.assertEqual(self.client.post("/api/farm/claim", headers=invitee).status_code, 200)
        self.assertEqual(self.client.post("/api/tasks/safety", headers=inviter).status_code, 200)
        self.assertEqual(self.client.post("/api/tasks/profile", headers=inviter).status_code, 200)
        self.assertEqual(self.client.post("/api/tasks/profile", headers=inviter).status_code, 409)
        state = self.client.get("/api/me", headers=inviter).json()
        self.assertEqual(state["activeRefCount"], 1)
        self.assertTrue(all(state["taskEligibility"].values()))
        self.assertEqual(state["balance"], 80 + 10 + 30 + 20 + 15)

    def test_referral_boost_is_capped_and_locked_when_cycle_starts(self):
        inviter = headers(INVITER)
        self.assertEqual(self.client.get("/api/me", headers=inviter).status_code, 200)
        started = self.client.post("/api/farm/start", headers=inviter)
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["farmReward"], 80)

        for idx in range(11):
            newcomer = headers(12000200 + idx, f"ref_{INVITER}")
            self.assertEqual(self.client.get("/api/me", headers=newcomer).status_code, 200)
            self.assertEqual(self.client.post("/api/farm/start", headers=newcomer).status_code, 200)
        future = int(time.time() * 1000) + server.FARM_MS + 2200
        with patch.object(server, "utc_ms", return_value=future):
            for idx in range(11):
                newcomer = headers(12000200 + idx)
                self.assertEqual(self.client.post("/api/farm/claim", headers=newcomer).status_code, 200)
            boosted = self.client.get("/api/me", headers=inviter).json()
            self.assertEqual(boosted["activeRefCount"], 11)
            self.assertEqual(boosted["miningBoostPercent"], 20)
            self.assertEqual(boosted["nextFarmReward"], 96)
            # Referral growth never changes an already active cycle's payout.
            self.assertEqual(boosted["farmReward"], 80)
            claimed = self.client.post("/api/farm/claim", headers=inviter)
            self.assertEqual(claimed.status_code, 200)
        self.assertEqual(claimed.json()["balance"], 80 + 11 * server.REFERRAL_REWARD)
        self.assertEqual(self.client.post("/api/farm/claim", headers=inviter).status_code, 409)
        restarted = self.client.post("/api/farm/start", headers=inviter)
        self.assertEqual(restarted.status_code, 200)
        self.assertEqual(restarted.json()["farmReward"], 96)
        self.assertEqual(restarted.json()["miningBoostPercent"], 20)

    def test_boost_reward_rounding_and_boundaries(self):
        self.assertEqual([server.boosted_farm_reward(i) for i in (0, 1, 3, 5, 10, 100)],
                         [80, 82, 85, 88, 96, 96])
        self.assertEqual(server.task_eligibility(None, 0, 0),
                         {"welcome": False, "safety": False, "profile": False})
        self.assertEqual(server.task_eligibility(100, 0, 0)["welcome"], True)
        self.assertEqual(server.task_eligibility(None, 1, 1),
                         {"welcome": True, "safety": True, "profile": True})

    def test_simultaneous_daily_claims_only_one_succeeds(self):
        hdr = headers(INVITER)
        self.assertEqual(self.client.get("/api/me", headers=hdr).status_code, 200)
        def do_claim(_):
            with TestClient(server.app) as client:
                return client.post("/api/daily", headers=hdr).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(do_claim, range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(self.client.get("/api/me", headers=hdr).json()["balance"], server.DAILY_REWARD)

    def test_simultaneous_farm_claims_only_one_succeeds(self):
        hdr = headers(INVITER)
        self.assertEqual(self.client.get("/api/me", headers=hdr).status_code, 200)
        self.assertEqual(self.client.post("/api/farm/start", headers=hdr).status_code, 200)
        future = int(time.time() * 1000) + server.FARM_MS + 2000

        def do_claim(_):
            with TestClient(server.app) as client:
                return client.post("/api/farm/claim", headers=hdr).status_code

        with patch.object(server, "utc_ms", return_value=future):
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(do_claim, range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        snapshot = self.client.get("/api/me", headers=hdr).json()
        self.assertEqual(snapshot["balance"], server.FARM_REWARD)
        self.assertEqual(snapshot["farmCount"], 1)

    def test_webhook_rejects_forged_requests(self):
        invalid = self.client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": INVITEE, "type": "private"}, "text": "/start"}},
        )
        self.assertEqual(invalid.status_code, 403)

    def test_database_health_is_authenticated(self):
        self.assertEqual(self.client.get("/api/db/status").status_code, 401)
        self.assertEqual(self.client.get("/api/telegram/status").status_code, 401)
        health = self.client.get("/api/db/status", headers=headers(INVITER))
        self.assertEqual(health.status_code, 200, health.text)
        self.assertTrue(health.json()["connected"])

    def test_bot_configuration_is_admin_only(self):
        # A signed normal account cannot reset webhooks or menu settings.
        response = self.client.post("/api/telegram/activate", headers=headers(INVITER))
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()

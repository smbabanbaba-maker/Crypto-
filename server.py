"""ZENQORY Telegram Mini App server for Vercel.

Pre-launch, off-chain reward points only. No token sale or withdrawal logic.
HMAC-authenticated Telegram identities; PostgreSQL-backed transactional claims.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from contextlib import contextmanager
from starlette.concurrency import run_in_threadpool
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
import re
import secrets
from typing import Literal
from pydantic import BaseModel, Field

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

HERE = Path(__file__).parent
FARM_MS = 8 * 60 * 60 * 1000
DAILY_MS = 24 * 60 * 60 * 1000
FARM_REWARD = 80
DAILY_REWARD = 20
REFERRAL_REWARD = 10
REFERRAL_PENDING_MS = 7 * 24 * 60 * 60 * 1000
MAX_TELEGRAM_ID = 9223372036854775807
# Existing mission IDs remain stable so earned rewards can never be claimed twice.
# A mission is claimable only when its server-observable condition is satisfied.
TASK_REWARDS = {"welcome": 30, "safety": 20, "profile": 15}
# Stable IDs protect previously redeemed missions; edits never delete claim history.
DEFAULT_MISSIONS = (
    ("welcome", "Start your first farming cycle",
     "Start a real 8-hour farming cycle to unlock the reward", "farm_start", 1, 30),
    ("safety", "Claim your first farming reward",
     "Complete your first 8-hour cycle and claim points", "farm_cycles", 1, 20),
    ("profile", "Activate your first invited friend",
     "Invite a friend who completes their first farming claim", "active_referrals", 1, 15),
)
MISSION_KINDS = {"farm_start", "farm_cycles", "active_referrals", "telegram_channel"}
BOOST_PER_ACTIVE_REFERRAL = 2
MAX_BOOST_PERCENT = 20


def boosted_farm_reward(active_referrals: int) -> int:
    """80 base points, +2% per active referral up to +20%; half-up to whole PTS."""
    active = max(0, min(int(active_referrals), MAX_BOOST_PERCENT // BOOST_PER_ACTIVE_REFERRAL))
    return FARM_REWARD + (FARM_REWARD * BOOST_PER_ACTIVE_REFERRAL * active + 50) // 100


def task_eligibility(farm_start: int | None, farm_count: int, active_referrals: int) -> dict:
    """Never award mission points based on an untrusted client-side click."""
    return {
        "welcome": farm_start is not None or farm_count > 0,
        "safety": farm_count > 0,
        "profile": active_referrals > 0,
    }

def is_admin_id(user_id: int) -> bool:
    """Strictly opt-in: nobody is an admin until the owner configures an ID."""
    admin_id = os.environ.get("ZENQORY_ADMIN_TELEGRAM_ID", "").strip()
    return admin_id.isdecimal() and str(user_id) == admin_id


def require_admin(init_data: str) -> dict:
    person = telegram_identity(init_data)
    if not is_admin_id(person["id"]):
        raise HTTPException(403, "Administrator access denied")
    return person


def mission_progress(kind: str, farm_start, farm_count: int, active_referrals: int) -> int:
    if kind == "farm_start":
        return int(farm_start is not None or farm_count > 0)
    if kind == "farm_cycles":
        return farm_count
    if kind == "active_referrals":
        return active_referrals
    return 0  # Telegram channel membership is always verified at claim time.


def valid_public_channel(value: str) -> tuple[str, str]:
    """Accept only public Telegram channels with verifiable @username."""
    raw = str(value or "").strip()
    if raw.startswith("https://t.me/"):
        raw = raw[len("https://t.me/"):].rstrip("/")
    raw = raw.lstrip("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", raw):
        raise HTTPException(422, "Use a public Telegram channel username, e.g. @MyChannel")
    return "@" + raw, "https://t.me/" + raw


class MissionCreate(BaseModel):
    name: str = Field(min_length=5, max_length=80)
    description: str = Field(min_length=10, max_length=220)
    kind: Literal["farm_cycles", "active_referrals", "telegram_channel"]
    target: int = Field(default=1, ge=1, le=10000)
    points: int = Field(ge=1, le=500)
    channel: str = Field(default="", max_length=120)


class MissionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=5, max_length=80)
    description: str | None = Field(default=None, min_length=10, max_length=220)
    points: int | None = Field(default=None, ge=1, le=500)
    enabled: bool | None = None


def trusted_telegram_photo(value) -> str | None:
    """Only Telegram HTTPS avatar URLs from cryptographically signed initData."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        allowed = (host in ("t.me", "telegram.org", "telegram-cdn.org", "cdn-telegram.org")
                   or host.endswith((".telegram.org", ".telegram-cdn.org", ".cdn-telegram.org")))
        if (parsed.scheme != "https" or not allowed or not parsed.path.startswith("/")
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.fragment):
            return None
        return value
    except ValueError:
        return None


app = FastAPI(title="ZENQORY Rewards", docs_url=None, redoc_url=None, openapi_url=None)
_schema_ready = False


def utc_ms() -> int:
    return int(time.time() * 1000)


def telegram_identity(raw: str) -> dict:
    """Never trust initDataUnsafe from JavaScript; verify Telegram signature."""
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "The Telegram bot has not been configured")
    if not raw or len(raw) > 8192:
        raise HTTPException(401, "Open ZENQORY from its official Telegram bot")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("Invalid duplicated fields")
        received = data["hash"]
        if len(received) != 64:
            raise ValueError("Invalid request signature")
        date = int(data["auth_date"])
        if abs(int(time.time()) - date) > 86400:
            raise ValueError("Your session expired; reopen the Telegram Mini App")
        secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        # Telegram bot-token HMAC covers ALL fields except hash, including
        # the newer Ed25519 "signature" field when Telegram supplies it.
        # Only third-party Ed25519 validation excludes both hash and signature.
        check_str = "\n".join(f"{k}={v}" for k, v in sorted(pairs) if k != "hash")
        expected = hmac.new(secret, check_str.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            raise ValueError("Invalid Telegram authentication")
        telegram_user = json.loads(data["user"])
        user_id = int(telegram_user["id"])
        if user_id <= 0 or user_id > MAX_TELEGRAM_ID or telegram_user.get("is_bot"):
            raise ValueError("A real Telegram user is required")
        return {
            "id": user_id,
            "first_name": str(telegram_user.get("first_name") or "Explorer")[:60],
            "photo_url": trusted_telegram_photo(telegram_user.get("photo_url")),
            "start_param": str(data.get("start_param") or "")[:100],
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OverflowError) as exc:
        raise HTTPException(401, str(exc)) from exc


def connect():
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise HTTPException(503, "Database is not configured")
    try:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(dsn, row_factory=dict_row, autocommit=True, connect_timeout=8)
    except Exception as exc:
        print("Database connection failed:", type(exc).__name__)
        raise HTTPException(503, "Rewards database unavailable") from exc


def schema(conn):
    global _schema_ready
    if _schema_ready:
        return
    # Idempotent bootstrap for a small MVP. Move to migration scripts before scale.
    with conn.cursor() as cursor:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS zen_users (
            id BIGINT PRIMARY KEY,
            first_name TEXT NOT NULL,
            balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
            farm_start BIGINT,
            farm_count INTEGER NOT NULL DEFAULT 0,
            last_daily BIGINT,
            referred_by BIGINT REFERENCES zen_users(id),
            referral_rewarded BOOLEAN NOT NULL DEFAULT FALSE,
            referral_points BIGINT NOT NULL DEFAULT 0,
            created_at BIGINT NOT NULL
        )""")
        # Nullable: old accounts migrate in place, without touching rewards.
        cursor.execute("""
        ALTER TABLE zen_users ADD COLUMN IF NOT EXISTS photo_url TEXT
        """)
        # Existing active farms keep their original 80-point reward. The
        # reward for new cycles is frozen at the start of each cycle.
        cursor.execute("""
        ALTER TABLE zen_users
          ADD COLUMN IF NOT EXISTS farm_reward INTEGER NOT NULL
          DEFAULT 80 CHECK (farm_reward BETWEEN 80 AND 96)
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS zen_tasks (
            user_id BIGINT NOT NULL REFERENCES zen_users(id),
            task_id TEXT NOT NULL,
            PRIMARY KEY (user_id, task_id)
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS zen_activity (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES zen_users(id),
            activity_type TEXT NOT NULL,
            points INTEGER NOT NULL,
            created_at BIGINT NOT NULL
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS zen_referral_intents (
            invitee_id BIGINT PRIMARY KEY,
            sponsor_id BIGINT NOT NULL REFERENCES zen_users(id),
            created_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS zen_missions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            kind TEXT NOT NULL
              CHECK (kind IN ('farm_start','farm_cycles','active_referrals','telegram_channel')),
            target INTEGER NOT NULL DEFAULT 1 CHECK (target BETWEEN 1 AND 10000),
            points INTEGER NOT NULL CHECK (points BETWEEN 1 AND 500),
            channel TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS zen_admin_audit (
            id BIGSERIAL PRIMARY KEY,
            actor_id BIGINT NOT NULL,
            action TEXT NOT NULL,
            mission_id TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at BIGINT NOT NULL
        )""")
        for mission_id, name, description, kind, target, points in DEFAULT_MISSIONS:
            cursor.execute("""
              INSERT INTO zen_missions
              (id,name,description,kind,target,points,channel,url,enabled,created_at,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,'','',TRUE,%s,%s)
              ON CONFLICT (id) DO NOTHING
            """, (mission_id, name, description, kind, target, points, utc_ms(), utc_ms()))
        cursor.execute("CREATE INDEX IF NOT EXISTS zen_referral_intents_expiry_idx ON zen_referral_intents(expires_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS zen_users_referrals_idx ON zen_users(referred_by)")
        cursor.execute("CREATE INDEX IF NOT EXISTS zen_activity_recent_idx ON zen_activity(user_id,id DESC)")
    _schema_ready = True


@contextmanager
def session():
    conn = connect()
    try:
        schema(conn)
        with conn.transaction():
            yield conn
    finally:
        conn.close()


def referral_sponsor(raw: str, invitee_id: int) -> int | None:
    """Only accept a bounded, valid Telegram deep-link referral identifier."""
    match = re.fullmatch(r"ref_([1-9][0-9]{0,18})", raw or "")
    if not match:
        return None
    sponsor_id = int(match.group(1))
    if sponsor_id > MAX_TELEGRAM_ID or sponsor_id == invitee_id:
        return None
    return sponsor_id


def remember_bot_invite(invitee_id: int, start_parameter: str) -> bool:
    """Store a 7-day invite intent from an authenticated Telegram webhook.

    The first invite wins, only existing sponsors qualify, and existing
    accounts cannot be retroactively reassigned to new inviters.
    """
    sponsor_id = referral_sponsor(start_parameter, invitee_id)
    if sponsor_id is None:
        return False
    current = utc_ms()
    with session() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
              INSERT INTO zen_referral_intents(invitee_id,sponsor_id,created_at,expires_at)
              SELECT %s, id, %s, %s FROM zen_users
              WHERE id=%s AND NOT EXISTS (SELECT 1 FROM zen_users WHERE id=%s)
              ON CONFLICT (invitee_id) DO NOTHING
            """, (invitee_id, current, current + REFERRAL_PENDING_MS,
                  sponsor_id, invitee_id))
            return cursor.rowcount == 1


def ensure_user(conn, person: dict) -> int:
    uid = person["id"]
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM zen_users WHERE id=%s", (uid,))
        if cursor.fetchone() is None:
            # A previously verified Bot /start invitation takes precedence.
            # This prevents an invite from being overwritten before signup.
            cursor.execute("""
              SELECT sponsor_id FROM zen_referral_intents
              WHERE invitee_id=%s AND expires_at >= %s
            """, (uid, utc_ms()))
            pending = cursor.fetchone()
            sponsor = pending["sponsor_id"] if pending else None
            if sponsor is None:
                # Otherwise use Telegram's signed Main Mini App start_param.
                sponsor = referral_sponsor(person.get("start_param") or "", uid)
                if sponsor is not None:
                    cursor.execute("SELECT id FROM zen_users WHERE id=%s", (sponsor,))
                    if not cursor.fetchone():
                        sponsor = None
            cursor.execute("""
              INSERT INTO zen_users(id,first_name,photo_url,referred_by,created_at)
              VALUES(%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING
            """, (uid, person["first_name"], person.get("photo_url"), sponsor, utc_ms()))
        # Mark the invite consumed without letting future links change this user.
        cursor.execute("DELETE FROM zen_referral_intents WHERE invitee_id=%s", (uid,))
        cursor.execute("UPDATE zen_users SET first_name=%s,photo_url=%s WHERE id=%s",
                       (person["first_name"], person.get("photo_url"), uid))
    return uid

def activity(conn, user_id: int, title: str, amount: int):
    with conn.cursor() as cursor:
        cursor.execute("""
          INSERT INTO zen_activity(user_id,activity_type,points,created_at)
          VALUES(%s,%s,%s,%s)
        """, (user_id, title, amount, utc_ms()))


def get_snapshot(conn, user_id: int) -> dict:
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM zen_users WHERE id=%s", (user_id,))
        u = cursor.fetchone()
        cursor.execute("SELECT task_id FROM zen_tasks WHERE user_id=%s", (user_id,))
        tasks = [x["task_id"] for x in cursor.fetchall()]
        cursor.execute("""
          SELECT id,name,description,kind,target,points,channel,url
          FROM zen_missions WHERE enabled=TRUE ORDER BY created_at,id LIMIT 100
        """)
        mission_rows = cursor.fetchall()
        cursor.execute("""
          SELECT COUNT(*) AS n,
                 COUNT(*) FILTER (WHERE farm_count > 0) AS active_n
          FROM zen_users WHERE referred_by=%s
        """, (user_id,))
        referral_stats = cursor.fetchone()
        referrals = referral_stats["n"]
        active_referrals = referral_stats["active_n"]
        # Members are visible only to their verified inviter; no public list.
        cursor.execute("""
          SELECT first_name,photo_url,farm_count
          FROM zen_users WHERE referred_by=%s
          ORDER BY created_at DESC,id DESC LIMIT 12
        """, (user_id,))
        referral_members = [{
            "firstName": row["first_name"],
            "photoUrl": row["photo_url"],
            "active": row["farm_count"] > 0,
        } for row in cursor.fetchall()]
        cursor.execute("""
          SELECT activity_type,points,created_at FROM zen_activity
          WHERE user_id=%s ORDER BY id DESC LIMIT 15
        """, (user_id,))
        history = [{"type": x["activity_type"], "amount": x["points"],
                    "at": x["created_at"]} for x in cursor.fetchall()]
    active_referrals = int(active_referrals)
    missions = [{
        "id": row["id"],
        "name": row["name"],
        "desc": row["description"],
        "kind": row["kind"],
        "target": row["target"],
        "reward": row["points"],
        "link": row["url"],
        "progress": min(int(row["target"]), mission_progress(
            row["kind"], u["farm_start"], int(u["farm_count"]), active_referrals)),
        "eligible": mission_progress(row["kind"], u["farm_start"], int(u["farm_count"]),
                                      active_referrals) >= int(row["target"])
            if row["kind"] != "telegram_channel" else False,
        "verificationRequired": row["kind"] == "telegram_channel",
    } for row in mission_rows]
    current_reward = int(u["farm_reward"]) if u["farm_start"] is not None else boosted_farm_reward(active_referrals)
    username = get_bot_username()
    return {
        "id": str(u["id"]),
        "firstName": u["first_name"],
        "photoUrl": u["photo_url"],
        "referralMembers": referral_members,
        "balance": u["balance"],
        "farmStart": u["farm_start"],
        "farmCount": u["farm_count"],
        "farmReward": current_reward,
        "nextFarmReward": boosted_farm_reward(active_referrals),
        "miningBoostPercent": min(active_referrals * BOOST_PER_ACTIVE_REFERRAL, MAX_BOOST_PERCENT),
        "maxMiningBoostPercent": MAX_BOOST_PERCENT,
        "taskEligibility": task_eligibility(u["farm_start"], int(u["farm_count"]), active_referrals),
        "lastDaily": u["last_daily"],
        "tasks": tasks,
        "missions": missions,
        "isAdmin": is_admin_id(user_id),
        "refCount": referrals,
        "activeRefCount": active_referrals,
        "refPoints": u["referral_points"],
        "history": history,
        "referralLink": f"https://t.me/{username}?startapp=ref_{user_id}" if username else "",
        "referralBotLink": f"https://t.me/{username}?start=ref_{user_id}" if username else "",
    }



@lru_cache(maxsize=1)
def _verified_bot_username() -> str:
    """Resolve this deployment's actual Telegram bot username from its token."""
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        return ""
    try:
        # Bot API verifies the supplied token and returns the bot's actual identity.
        result = _bot_api("getMe", {}, token).get("result") or {}
        name = result.get("username", "")
        return name if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_]{5,32}", name) else ""
    except Exception:
        return ""


def get_bot_username() -> str:
    """Prefer an explicitly configured username, otherwise query Telegram once."""
    configured = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", configured):
        return configured
    return _verified_bot_username()


@app.get("/api/health")
def health():
    return {"status": "ok", "name": "ZENQORY", "mode": "off-chain-points"}


@app.get("/api/db/status", include_in_schema=False)
def database_health(x_telegram_init_data: str = Header(default="")):
    """Authenticated database probe. Never allow anonymous traffic to spend DB connections."""
    telegram_identity(x_telegram_init_data)
    if not os.environ.get("DATABASE_URL"):
        return {"database": "not_configured", "connected": False}
    try:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                status = cursor.fetchone()
        return {"database": "neon_postgres", "connected": bool(status and status.get("ok") == 1)}
    except Exception:
        return {"database": "unavailable", "connected": False}


@app.get("/api/me")
def me(x_telegram_init_data: str = Header(default="")):
    person = telegram_identity(x_telegram_init_data)
    with session() as conn:
        return get_snapshot(conn, ensure_user(conn, person))


@app.post("/api/farm/start")
def start(x_telegram_init_data: str = Header(default="")):
    person = telegram_identity(x_telegram_init_data)
    with session() as conn:
        uid = ensure_user(conn, person)
        with conn.cursor() as cursor:
            cursor.execute("SELECT farm_start FROM zen_users WHERE id=%s FOR UPDATE", (uid,))
            existing = cursor.fetchone()["farm_start"]
            if existing is not None:
                raise HTTPException(409, "An active cycle already exists")
            # Freeze the boost for this farming cycle. New active friends
            # improve *future* cycles; the running cycle cannot be repriced.
            cursor.execute("""
              SELECT COUNT(*) AS n FROM zen_users WHERE referred_by=%s AND farm_count>0
            """, (uid,))
            active_referrals = cursor.fetchone()["n"]
            reward = boosted_farm_reward(active_referrals)
            cursor.execute("""
              UPDATE zen_users SET farm_start=%s, farm_reward=%s WHERE id=%s
            """, (utc_ms(), reward, uid))
        return get_snapshot(conn, uid)


@app.post("/api/farm/claim")
def claim(x_telegram_init_data: str = Header(default="")):
    person = telegram_identity(x_telegram_init_data)
    with session() as conn:
        uid = ensure_user(conn, person)
        with conn.cursor() as cursor:
            cursor.execute("""
              SELECT farm_start,farm_reward,farm_count,referred_by,referral_rewarded
              FROM zen_users WHERE id=%s FOR UPDATE
            """, (uid,))
            u = cursor.fetchone()
            if u["farm_start"] is None or utc_ms()-u["farm_start"] < FARM_MS:
                raise HTTPException(409, "This 8-hour cycle is not yet claimable")
            # Row lock + transaction permit a single payout for each cycle.
            # Only use the server-locked reward stored when farming began.
            reward = int(u["farm_reward"])
            cursor.execute("""
              UPDATE zen_users SET balance=balance+%s,farm_start=NULL,
                farm_reward=%s,farm_count=farm_count+1 WHERE id=%s
            """, (reward, FARM_REWARD, uid))
            activity(conn, uid, "Farming reward", reward)
            if u["farm_count"] == 0 and u["referred_by"] and not u["referral_rewarded"]:
                cursor.execute("""
                  UPDATE zen_users
                  SET balance=balance+%s,referral_points=referral_points+%s
                  WHERE id=%s
                """, (REFERRAL_REWARD, REFERRAL_REWARD, u["referred_by"]))
                activity(conn, u["referred_by"], "Friend activated", REFERRAL_REWARD)
                cursor.execute("UPDATE zen_users SET referral_rewarded=TRUE WHERE id=%s", (uid,))
        return get_snapshot(conn, uid)


@app.post("/api/daily")
def daily(x_telegram_init_data: str = Header(default="")):
    person = telegram_identity(x_telegram_init_data)
    with session() as conn:
        uid = ensure_user(conn, person)
        with conn.cursor() as cursor:
            cursor.execute("SELECT last_daily FROM zen_users WHERE id=%s FOR UPDATE", (uid,))
            last = cursor.fetchone()["last_daily"]
            current = utc_ms()
            if last is not None and current-last < DAILY_MS:
                raise HTTPException(409, "Come back after 24 hours")
            cursor.execute("UPDATE zen_users SET last_daily=%s,balance=balance+%s WHERE id=%s",
                           (current, DAILY_REWARD, uid))
            activity(conn, uid, "Daily reward", DAILY_REWARD)
        return get_snapshot(conn, uid)


def verify_channel_member(channel: str, user_id: int) -> bool:
    """Never award channel tasks for a click; ask Telegram for actual membership."""
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "Telegram channel verification is not configured")
    try:
        result = _bot_api("getChatMember",
                          {"chat_id": channel, "user_id": user_id}, token).get("result") or {}
    except HTTPException:
        raise HTTPException(503, "Channel membership cannot be verified right now") from None
    status = result.get("status")
    return status in ("member", "administrator", "creator") or (
        status == "restricted" and result.get("is_member") is True
    )


def check_channel_bot_permissions(channel: str) -> None:
    """Channel tasks may only be published when the bot can verify membership."""
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "Configure the Telegram bot before channel missions")
    try:
        bot = _bot_api("getMe", {}, token).get("result") or {}
        bot_id = int(bot["id"])
        role = _bot_api("getChatMember", {"chat_id": channel, "user_id": bot_id}, token)
        status = (role.get("result") or {}).get("status")
    except (HTTPException, KeyError, ValueError, TypeError):
        raise HTTPException(422,
                            "Add the ZENQORY bot as a channel administrator, then retry") from None
    if status not in ("administrator", "creator"):
        raise HTTPException(422, "The ZENQORY bot must be a channel administrator")


@app.post("/api/tasks/{task_id}")
def task_claim(task_id: str, x_telegram_init_data: str = Header(default="")):
    person = telegram_identity(x_telegram_init_data)
    if len(task_id) > 64:
        raise HTTPException(404, "Unknown mission")
    with session() as conn:
        uid = ensure_user(conn, person)
        with conn.cursor() as cursor:
            cursor.execute("""
              SELECT id,name,kind,target,points,channel
              FROM zen_missions WHERE id=%s AND enabled=TRUE FOR SHARE
            """, (task_id,))
            mission = cursor.fetchone()
            if not mission:
                raise HTTPException(404, "Mission not available")
            # Ensure a single payout even under concurrent claims.
            cursor.execute("""
              SELECT farm_start,farm_count FROM zen_users WHERE id=%s FOR UPDATE
            """, (uid,))
            farm = cursor.fetchone()
            cursor.execute("""
              SELECT 1 FROM zen_tasks WHERE user_id=%s AND task_id=%s
            """, (uid, task_id))
            if cursor.fetchone():
                raise HTTPException(409, "Mission already completed")
            cursor.execute("""
              SELECT COUNT(*) AS n FROM zen_users
              WHERE referred_by=%s AND farm_count>0
            """, (uid,))
            active_referrals = int(cursor.fetchone()["n"])
            if mission["kind"] == "telegram_channel":
                if not verify_channel_member(mission["channel"], uid):
                    raise HTTPException(409,
                                        "Join the Telegram channel first, then tap Verify & Claim")
            else:
                progress = mission_progress(mission["kind"], farm["farm_start"],
                                            int(farm["farm_count"]), active_referrals)
                if progress < mission["target"]:
                    raise HTTPException(409, "Complete the mission requirement before claiming points")
            cursor.execute("""
              INSERT INTO zen_tasks(user_id,task_id) VALUES(%s,%s)
              ON CONFLICT DO NOTHING RETURNING task_id
            """, (uid, task_id))
            if not cursor.fetchone():
                raise HTTPException(409, "Mission already completed")
            amount = int(mission["points"])
            cursor.execute("UPDATE zen_users SET balance=balance+%s WHERE id=%s", (amount, uid))
            activity(conn, uid, "Mission: " + task_id, amount)
        return get_snapshot(conn, uid)


def admin_audit(conn, actor_id: int, action: str, mission_id: str, details: str):
    with conn.cursor() as cursor:
        cursor.execute("""
          INSERT INTO zen_admin_audit(actor_id,action,mission_id,details,created_at)
          VALUES(%s,%s,%s,%s,%s)
        """, (actor_id, action, mission_id, details[:300], utc_ms()))


@app.get("/api/admin/overview", include_in_schema=False)
def admin_overview(x_telegram_init_data: str = Header(default="")):
    person = require_admin(x_telegram_init_data)
    with session() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
              SELECT COUNT(*) AS users,
                     COALESCE(SUM(balance),0) AS outstanding_points,
                     COALESCE(SUM(farm_count),0) AS farm_claims,
                     COUNT(*) FILTER(WHERE referred_by IS NOT NULL) AS invited,
                     COUNT(*) FILTER(WHERE farm_count>0) AS active_farmers
              FROM zen_users
            """)
            totals = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS n FROM zen_tasks")
            claims = int(cursor.fetchone()["n"])
            cursor.execute("""
              SELECT m.id,m.name,m.description,m.kind,m.target,m.points,
                     m.channel,m.url,m.enabled,
                     COUNT(t.user_id) AS claims
              FROM zen_missions m
              LEFT JOIN zen_tasks t ON t.task_id=m.id
              GROUP BY m.id
              ORDER BY m.created_at,m.id LIMIT 150
            """)
            missions = [{
                "id": x["id"], "name": x["name"], "desc": x["description"],
                "kind": x["kind"], "target": x["target"], "reward": x["points"],
                "channel": x["channel"], "link": x["url"], "enabled": x["enabled"],
                "claims": int(x["claims"]),
            } for x in cursor.fetchall()]
            cursor.execute("""
              SELECT id,first_name,balance,farm_count,created_at FROM zen_users
              ORDER BY created_at DESC,id DESC LIMIT 10
            """)
            recent_users = [{
                "id": str(x["id"]), "name": x["first_name"],
                "balance": x["balance"], "farmCount": x["farm_count"],
                "joinedAt": x["created_at"],
            } for x in cursor.fetchall()]
            cursor.execute("""
              SELECT action,mission_id,details,created_at
              FROM zen_admin_audit ORDER BY id DESC LIMIT 15
            """)
            audit = [{
                "action": x["action"], "missionId": x["mission_id"],
                "details": x["details"], "at": x["created_at"],
            } for x in cursor.fetchall()]
    return {
        "admin": True,
        "stats": {
            "users": int(totals["users"]),
            "activeFarmers": int(totals["active_farmers"]),
            "invited": int(totals["invited"]),
            "outstandingPoints": int(totals["outstanding_points"]),
            "farmClaims": int(totals["farm_claims"]),
            "missionClaims": claims,
        },
        "missions": missions,
        "recentUsers": recent_users,
        "audit": audit,
    }


@app.post("/api/admin/missions", include_in_schema=False)
def admin_create_mission(body: MissionCreate,
                         x_telegram_init_data: str = Header(default="")):
    person = require_admin(x_telegram_init_data)
    name = body.name.strip()
    description = body.description.strip()
    if len(name) < 5 or len(description) < 10:
        raise HTTPException(422, "Provide a clear mission name and description")
    if body.kind == "telegram_channel":
        if body.target != 1:
            raise HTTPException(422, "Channel membership requires a target of 1")
        channel, link = valid_public_channel(body.channel)
        check_channel_bot_permissions(channel)
    else:
        if body.channel.strip():
            raise HTTPException(422, "Channel address is only for Telegram channel missions")
        channel, link = "", ""
    mission_id = "mission_" + secrets.token_hex(8)
    with session() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM zen_missions WHERE enabled=TRUE")
            if int(cursor.fetchone()["n"]) >= 100:
                raise HTTPException(409, "Maximum 100 active missions reached. Pause an old mission first")
            cursor.execute("""
              INSERT INTO zen_missions
                (id,name,description,kind,target,points,channel,url,enabled,created_at,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s)
            """, (mission_id, name, description, body.kind, body.target,
                  body.points, channel, link, utc_ms(), utc_ms()))
        admin_audit(conn, person["id"], "create", mission_id,
                    "Created " + body.kind + " mission with " + str(body.points) + " points")
    return {"ok": True, "id": mission_id}


@app.patch("/api/admin/missions/{mission_id}", include_in_schema=False)
def admin_update_mission(mission_id: str, body: MissionUpdate,
                         x_telegram_init_data: str = Header(default="")):
    person = require_admin(x_telegram_init_data)
    if len(mission_id) > 64:
        raise HTTPException(404, "Mission not found")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "No changes provided")
    if any(v is None for v in changes.values()):
        raise HTTPException(422, "Mission settings cannot be null")
    for key in ("name", "description"):
        if key in changes:
            changes[key] = changes[key].strip()
            if len(changes[key]) < (5 if key == "name" else 10):
                raise HTTPException(422, "Provide meaningful mission text")
    allowed = {"name", "description", "points", "enabled"}
    if not set(changes).issubset(allowed):
        raise HTTPException(422, "Unsupported mission field")
    with session() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM zen_missions WHERE id=%s FOR UPDATE", (mission_id,))
            if not cursor.fetchone():
                raise HTTPException(404, "Mission not found")
            # Stable mission identity, threshold, verifier, and prior claims:
            # admin can pause and adjust points, never manufacture a payout.
            from psycopg import sql
            query = sql.SQL("UPDATE zen_missions SET {},updated_at=%s WHERE id=%s").format(
                sql.SQL(",").join(
                    sql.SQL("{}=%s").format(sql.Identifier(key)) for key in changes
                )
            )
            cursor.execute(query, [*changes.values(), utc_ms(), mission_id])
        admin_audit(conn, person["id"], "update", mission_id,
                    "Changed: " + ", ".join(sorted(changes.keys())))
    return {"ok": True, "id": mission_id}


@app.get("/")
def index():
    return FileResponse(HERE / "public" / "index.html")



# ---------------------------------------------------------------------------
# Telegram Bot Gateway — profile launch button and /start response
# No database is needed for welcome, help, or Mini App launch.
# ---------------------------------------------------------------------------

from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from fastapi import Request

ZENQORY_APP_URL = "https://crypto-jade-nine.vercel.app"
ZENQORY_BOT_DESCRIPTION = (
    "Explore a new era of digital rewards. 🚀\n\n"
    "Farm points every 8 hours, complete missions and grow with your friends. 💚\n\n"
    "ZNQY is a pre-launch points system, not a tradeable cryptocurrency."
)


def channel_link() -> str:
    """Allow only a real, explicitly configured Telegram channel/invite URL.

    Never guess a public channel or send users to a bot in its place.
    """
    url = os.environ.get("CHANNEL_URL", "").strip()
    if re.fullmatch(r"https://t\.me/(?:[A-Za-z0-9_]{5,32}|\+[A-Za-z0-9_-]{10,}|joinchat/[A-Za-z0-9_-]{10,})/?", url):
        return url
    return ""

_bot_setup_completed = False


def _bot_webhook_secret(token: str) -> str:
    # Telegram sends this value in its X-Telegram-Bot-Api-Secret-Token header.
    # Derived from BOT_TOKEN so the owner doesn't need a second environment secret.
    return hashlib.sha256(("zenqory:webhook:v1:" + token).encode("utf-8")).hexdigest()


def _bot_api(method: str, payload: dict, token: str) -> dict:
    # Never print requests or exceptions; Telegram bot tokens occur in request URLs.
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = UrlRequest(
        "https://api.telegram.org/bot" + token + "/" + method,
        data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=8) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        print("Telegram API operation failed:", method, type(exc).__name__)
        raise HTTPException(502, "Telegram bot setup failed. Check BOT_TOKEN in Vercel.") from None
    if not result.get("ok"):
        raise HTTPException(502, "Telegram rejected bot setup. Check BOT_TOKEN.")
    return result


def _setup_telegram_bot() -> dict:
    global _bot_setup_completed
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "Set BOT_TOKEN in Vercel Environment Variables first")
    if _bot_setup_completed:
        return {"ok": True, "webhook": "configured", "menu": "configured"}
    webhook = ZENQORY_APP_URL + "/api/telegram/webhook"
    _bot_api("setWebhook", {
        "url": webhook,
        "secret_token": _bot_webhook_secret(token),
        "allowed_updates": ["message"],
        "drop_pending_updates": False,
    }, token)
    _bot_api("setChatMenuButton", {
        "menu_button": {
            "type": "web_app",
            "text": "Open ZENQORY",
            "web_app": {"url": ZENQORY_APP_URL},
        }
    }, token)
    _bot_api("setMyCommands", {
        "commands": [
            {"command": "start", "description": "Welcome and launch ZENQORY"},
            {"command": "app", "description": "Open the rewards mini app"},
            {"command": "help", "description": "How ZENQORY rewards work"},
            {"command": "status", "description": "Check the app status"},
            {"command": "channel", "description": "Join the official ZENQORY community"},
        ]
    }, token)
    _bot_api("setMyShortDescription", {
        "short_description": "ZENQORY | Farm points, complete missions and invite friends. Genesis network."
    }, token)
    _bot_api("setMyDescription", {
        "description": ZENQORY_BOT_DESCRIPTION
    }, token)
    _bot_setup_completed = True
    return {"ok": True, "webhook": "configured", "menu": "configured"}


@app.post("/api/telegram/verify", include_in_schema=False)
def telegram_verify(x_telegram_init_data: str = Header(default="")):
    """Verify Telegram launch credentials independently of rewards/database.

    A verified Mini App session is not a claim that the points database is live.
    Do not disclose raw initData, bot tokens or third-party secrets.
    """
    person = telegram_identity(x_telegram_init_data)
    return {
        "verified": True,
        "first_name": person["first_name"],
        "rewards_mode": "live" if os.environ.get("DATABASE_URL") else "local_preview",
    }


@app.post("/api/telegram/activate", include_in_schema=False)
def activate_telegram(x_telegram_init_data: str = Header(default="")):
    """Administrative bot configuration, protected against user-triggered changes."""
    person = telegram_identity(x_telegram_init_data)
    if not is_admin_id(person["id"]):
        raise HTTPException(403, "Bot administration is restricted")
    return _setup_telegram_bot()


@app.post("/api/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request,
                           x_telegram_bot_api_secret_token: str = Header(default="")):
    """Telegram delivers /start here after our bot has a registered webhook."""
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token or not hmac.compare_digest(
        _bot_webhook_secret(token), x_telegram_bot_api_secret_token
    ):
        raise HTTPException(403, "Invalid Telegram webhook authentication")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Expected JSON")
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid update payload") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid update payload")
    message = payload.get("message")
    if not isinstance(message, dict):
        return {"ok": True}
    chat = message.get("chat") or {}
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return {"ok": True}
    chat_id = chat.get("id")
    if not isinstance(chat_id, int) or chat_id <= 0:
        return {"ok": True}
    raw_text = message.get("text", "")
    if not isinstance(raw_text, str):
        return {"ok": True}
    words = raw_text.strip().split(maxsplit=1)
    command = (words[0].split("@")[0].lower() if words else "")
    invite_status = ""
    if command == "/start" and len(words) == 2:
        # This is a server-authenticated message from Telegram (webhook secret).
        # Store referral attribution before the user opens the Mini App.
        try:
            accepted = await run_in_threadpool(remember_bot_invite, chat_id, words[1].strip())
            if accepted:
                invite_status = "\n\n🎁 Your friend's invitation has been registered."
        except Exception:
            # Bot welcome must remain usable even if the rewards DB is down.
            invite_status = ""
    if command in ("/start", "/app", "start", "open zenqory"):
        first_name = str((message.get("from") or {}).get("first_name") or "Explorer")[:40]
        greeting = (
            "Hey " + first_name + "! 💚 Welcome to ZENQORY.\n\n"
            "Your space to farm points, unlock missions and grow with friends. ✨\n\n"
            "🪙 Start an 8-hour farming cycle, then claim your points.\n"
            "🎯 Complete missions and discover new rewards.\n"
            "👥 Bring friends into the ZENQORY community.\n\n"
            "Ready to explore? Tap Launch ZENQORY below. 🚀\n\n"
            "ZNQY points are pre-launch rewards, not tradeable tokens." + invite_status
        )
    elif command in ("/channel", "/join"):
        greeting = (
            "📣 ZENQORY COMMUNITY\n\n"
            + ("Join our official channel below for launch news and updates."
               if channel_link() else
               "The official ZENQORY channel link has not been connected yet. "
               "Please check back soon.")
        )
    elif command in ("/myid", "/id"):
        greeting = (
            "🔐 YOUR TELEGRAM ID\n\n" + str(chat_id)
            + "\n\nOnly share this ID with the ZENQORY administrator you trust."
        )
    elif command == "/help":
        greeting = (
            "💚 ZENQORY HELP\n\n"
            "Use /start or /app to open the Mini App.\n"
            "Farming: start an 8-hour cycle, then claim points.\n"
            "Missions and daily rewards can earn additional points.\n\n"
            "ZNQY points are pre-launch, off-chain community rewards. "
            "Open the official Mini App from Telegram to use your verified account."
        )
    elif command == "/status":
        greeting = (
            "🟢 ZENQORY Mini App is available.\n"
            "🔐 Open the app through Telegram to access your secure reward points.\n"
            "ZNQY rewards are currently off-chain pre-launch points."
        )
    else:
        greeting = "💚 Welcome to ZENQORY! Tap the button below, or use /help."
    # Bot API allows answering a webhook with the method + parameters as JSON,
    # avoiding a separate outbound request and reducing latency.
    buttons = [[{
        "text": "🚀 Launch ZENQORY",
        "web_app": {"url": ZENQORY_APP_URL}
    }]]
    official_channel = channel_link()
    if official_channel:
        buttons.append([{
            "text": "📣 Join Channel",
            "url": official_channel
        }])
    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": greeting,
        "reply_markup": {"inline_keyboard": buttons},
    }


@app.get("/api/telegram/status", include_in_schema=False)
def telegram_status(x_telegram_init_data: str = Header(default="")):
    """Read-only bot diagnostics visible only to authenticated Telegram members."""
    telegram_identity(x_telegram_init_data)
    token = os.environ.get("BOT_TOKEN", "").strip()
    response = {
        "app": "ZENQORY",
        "bot_token_configured": bool(token),
        "bot_token_format_valid": bool(token and __import__("re").fullmatch(r"[0-9]{5,}:[A-Za-z0-9_-]{30,}", token)),
        "app_url": ZENQORY_APP_URL,
        "bot_api_reachable": False,
        "bot_username": None,
        "webhook_connected": False,
        "channel_button_configured": bool(channel_link()),
        "webhook_pending_updates": 0,
        "setup": "awaiting_bot_token",
    }
    if not token:
        return response
    try:
        bot = _bot_api("getMe", {}, token).get("result") or {}
        response["bot_api_reachable"] = True
        response["bot_username"] = bot.get("username")
        # Read-only status endpoint: never reconfigure the bot on a GET request.
        # Only a signed POST to /api/telegram/activate may register the webhook.
        webhook_info = _bot_api("getWebhookInfo", {}, token).get("result") or {}
        expected = ZENQORY_APP_URL + "/api/telegram/webhook"
        # A missing webhook is reported to the owner, not silently mutated.
        response["webhook_connected"] = webhook_info.get("url") == expected
        response["webhook_pending_updates"] = int(webhook_info.get("pending_update_count") or 0)
        response["setup"] = "ready" if response["webhook_connected"] else "webhook_not_ready"
        if webhook_info.get("last_error_date"):
            response["webhook_delivery_problem"] = True
    except HTTPException as exc:
        # Deliberately omit URL, token, Telegram response content and exceptions.
        response["setup"] = "telegram_connection_failed"
        response["http_error"] = exc.status_code
    return response



@app.middleware("http")
async def security_response_headers(request: Request, call_next):
    """Basic defense-in-depth headers for JSON and HTML responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return response


# Local uvicorn convenience. On Vercel, the public/ folder is served by its CDN.
if not os.environ.get("VERCEL"):
    for asset, mime in [("styles.css", "text/css"), ("app.js", "text/javascript"),
                        ("favicon.svg", "image/svg+xml")]:
        from fastapi.responses import Response
        @app.get("/" + asset, include_in_schema=False)
        def local_asset(asset_name=asset, media_type=mime):
            path = HERE / "public" / asset_name
            if not path.is_file():
                raise HTTPException(404)
            return FileResponse(path, media_type=media_type)

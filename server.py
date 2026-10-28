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
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl
import re

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

HERE = Path(__file__).parent
FARM_MS = 8 * 60 * 60 * 1000
DAILY_MS = 24 * 60 * 60 * 1000
FARM_REWARD = 80
DAILY_REWARD = 20
REFERRAL_REWARD = 10
TASK_REWARDS = {"welcome": 30, "safety": 20, "profile": 15}

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
        if user_id <= 0 or telegram_user.get("is_bot"):
            raise ValueError("A real Telegram user is required")
        return {
            "id": user_id,
            "first_name": str(telegram_user.get("first_name") or "Explorer")[:60],
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


def ensure_user(conn, person: dict) -> int:
    uid = person["id"]
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM zen_users WHERE id=%s", (uid,))
        if cursor.fetchone() is None:
            sponsor = None
            param = person["start_param"]
            if param.startswith("ref_") and param[4:].isdigit():
                possible = int(param[4:])
                if possible > 0 and possible != uid:
                    cursor.execute("SELECT id FROM zen_users WHERE id=%s", (possible,))
                    if cursor.fetchone():
                        sponsor = possible
            cursor.execute("""
              INSERT INTO zen_users(id,first_name,referred_by,created_at)
              VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING
            """, (uid, person["first_name"], sponsor, utc_ms()))
        cursor.execute("UPDATE zen_users SET first_name=%s WHERE id=%s", (person["first_name"], uid))
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
        cursor.execute("SELECT COUNT(*) AS n FROM zen_users WHERE referred_by=%s", (user_id,))
        referrals = cursor.fetchone()["n"]
        cursor.execute("""
          SELECT activity_type,points,created_at FROM zen_activity
          WHERE user_id=%s ORDER BY id DESC LIMIT 15
        """, (user_id,))
        history = [{"type": x["activity_type"], "amount": x["points"],
                    "at": x["created_at"]} for x in cursor.fetchall()]
    username = get_bot_username()
    return {
        "id": str(u["id"]),
        "firstName": u["first_name"],
        "balance": u["balance"],
        "farmStart": u["farm_start"],
        "farmCount": u["farm_count"],
        "lastDaily": u["last_daily"],
        "tasks": tasks,
        "refCount": referrals,
        "refPoints": u["referral_points"],
        "history": history,
        "referralLink": f"https://t.me/{username}?startapp=ref_{user_id}" if username else "",
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
def database_health():
    """Minimal PostgreSQL connectivity probe without exposing secrets.

    This endpoint does not create user accounts or award any reward points.
    """
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
            cursor.execute("UPDATE zen_users SET farm_start=%s WHERE id=%s", (utc_ms(), uid))
        return get_snapshot(conn, uid)


@app.post("/api/farm/claim")
def claim(x_telegram_init_data: str = Header(default="")):
    person = telegram_identity(x_telegram_init_data)
    with session() as conn:
        uid = ensure_user(conn, person)
        with conn.cursor() as cursor:
            cursor.execute("""
              SELECT farm_start,farm_count,referred_by,referral_rewarded
              FROM zen_users WHERE id=%s FOR UPDATE
            """, (uid,))
            u = cursor.fetchone()
            if u["farm_start"] is None or utc_ms()-u["farm_start"] < FARM_MS:
                raise HTTPException(409, "This 8-hour cycle is not yet claimable")
            cursor.execute("""
              UPDATE zen_users SET balance=balance+%s,farm_start=NULL,farm_count=farm_count+1
              WHERE id=%s
            """, (FARM_REWARD, uid))
            activity(conn, uid, "Farming reward", FARM_REWARD)
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


@app.post("/api/tasks/{task_id}")
def task_claim(task_id: str, x_telegram_init_data: str = Header(default="")):
    if task_id not in TASK_REWARDS:
        raise HTTPException(404, "Unknown mission")
    person = telegram_identity(x_telegram_init_data)
    with session() as conn:
        uid = ensure_user(conn, person)
        with conn.cursor() as cursor:
            cursor.execute("""
              INSERT INTO zen_tasks(user_id,task_id) VALUES(%s,%s)
              ON CONFLICT DO NOTHING RETURNING task_id
            """, (uid, task_id))
            if not cursor.fetchone():
                raise HTTPException(409, "Mission already completed")
            amount = TASK_REWARDS[task_id]
            cursor.execute("UPDATE zen_users SET balance=balance+%s WHERE id=%s", (amount, uid))
            activity(conn, uid, "Mission: " + task_id, amount)
        return get_snapshot(conn, uid)


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
        "short_description": "ZENQORY | Farm reward points, complete missions, invite friends. Genesis preview."
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
    """Secure one-time setup after launch from the actual Telegram Mini App."""
    telegram_identity(x_telegram_init_data)
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
    command = raw_text.strip().split(maxsplit=1)[0].split("@")[0].lower()
    if command in ("/start", "/app", "start", "open zenqory"):
        first_name = str((message.get("from") or {}).get("first_name") or "Explorer")[:40]
        greeting = (
            "Hey " + first_name + "! 💚 Welcome to ZENQORY.\n\n"
            "Your space to farm points, unlock missions and grow with friends. ✨\n\n"
            "🪙 Start an 8-hour farming cycle, then claim your points.\n"
            "🎯 Complete missions and discover new rewards.\n"
            "👥 Bring friends into the ZENQORY community.\n\n"
            "Ready to explore? Tap Launch ZENQORY below. 🚀\n\n"
            "ZNQY points are pre-launch rewards, not tradeable tokens."
        )
    elif command in ("/channel", "/join"):
        greeting = (
            "📣 ZENQORY COMMUNITY\n\n"
            + ("Join our official channel below for launch news and updates."
               if channel_link() else
               "The official ZENQORY channel link has not been connected yet. "
               "Please check back soon.")
        )
    elif command == "/help":
        greeting = (
            "💚 ZENQORY HELP\n\n"
            "Use /start or /app to open the Mini App.\n"
            "Farming: start an 8-hour cycle, then claim points.\n"
            "Missions and daily rewards can earn additional points.\n\n"
            "Current phase: preview. Demo points stay on your device until "
            "secure live storage is configured."
        )
    elif command == "/status":
        greeting = (
            "🟢 ZENQORY Mini App is available.\n"
            "🧪 Rewards: preview mode until database is connected.\n"
            "Tap below to launch."
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
def telegram_status():
    """Safe one-click bot diagnostics + one-time automatic webhook configuration.

    The webhook URL, commands and menu button are hardcoded for this project.
    This endpoint never returns a token or arbitrary Telegram chat/user data.
    """
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
        # Synchronize our brief, original welcome copy without touching media.
        # BotFather exclusively controls the GIF/video description picture.
        current_description = _bot_api("getMyDescription", {}, token).get("result") or {}
        if current_description.get("description", "") != ZENQORY_BOT_DESCRIPTION:
            _bot_api("setMyDescription", {"description": ZENQORY_BOT_DESCRIPTION}, token)
        webhook_info = _bot_api("getWebhookInfo", {}, token).get("result") or {}
        expected = ZENQORY_APP_URL + "/api/telegram/webhook"
        if webhook_info.get("url") != expected:
            _setup_telegram_bot()
            webhook_info = _bot_api("getWebhookInfo", {}, token).get("result") or {}
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

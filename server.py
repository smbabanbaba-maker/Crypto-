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
from pathlib import Path
from urllib.parse import parse_qsl

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
    token = os.environ.get("BOT_TOKEN", "")
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
        # hash and third-party signature must not enter the HMAC data-check-string.
        check_str = "\n".join(f"{k}={v}" for k, v in sorted(pairs) if k not in ("hash", "signature"))
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
    username = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
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


@app.get("/api/health")
def health():
    return {"status": "ok", "name": "ZENQORY", "mode": "off-chain-points"}


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
        ]
    }, token)
    _bot_api("setMyShortDescription", {
        "short_description": "ZENQORY | Farm reward points, complete missions, invite friends. Genesis preview."
    }, token)
    _bot_api("setMyDescription", {
        "description": (
            "💚 Welcome to ZENQORY — a futuristic pre-launch rewards community.\n\n"
            "🚀 Open our Telegram Mini App to start 8-hour farming cycles, "
            "complete missions and invite friends.\n\n"
            "🪙 ZNQY points are off-chain preview rewards, not a tradeable token. "
            "Live rewards storage and further features will be announced after testing."
        )
    }, token)
    _bot_setup_completed = True
    return {"ok": True, "webhook": "configured", "menu": "configured"}


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
            "💚 Barka da zuwa ZENQORY, " + first_name + "!\n\n"
            "🚀 Your digital rewards journey starts here.\n\n"
            "🪙 Start an 8-hour farming cycle\n"
            "🎯 Complete reward missions\n"
            "👥 Invite your friends\n"
            "💎 Track your ZNQY pre-launch points\n\n"
            "👇 Tap the button below to launch ZENQORY.\n\n"
            "ℹ️ Rewards are currently pre-launch points, not tradeable cryptocurrency."
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
    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": greeting,
        "reply_markup": {
            "inline_keyboard": [[{
                "text": "🚀 Launch ZENQORY",
                "web_app": {"url": ZENQORY_APP_URL}
            }]]
        },
    }


@app.get("/api/telegram/status", include_in_schema=False)
def telegram_status():
    """Safe public config check; never exposes token or Telegram user data."""
    return {
        "app": "ZENQORY",
        "bot_token_configured": bool(os.environ.get("BOT_TOKEN", "").strip()),
        "app_url": ZENQORY_APP_URL,
        "activation": "Launch the Mini App from Telegram to register the webhook",
    }


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

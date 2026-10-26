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

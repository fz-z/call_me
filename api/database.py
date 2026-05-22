import os
import sqlite3
import uuid
from datetime import datetime, timezone

import aiosqlite
from passlib.context import CryptContext

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/call_me.db")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _ensure_dir():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)


def _sync_conn() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def get_db() -> aiosqlite.Connection:
    _ensure_dir()
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    """Called at startup. Creates tables and seeds admin account."""
    conn = _sync_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                alias TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                system_prompt TEXT NOT NULL DEFAULT '',
                owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS permissions (
                agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                granted_by TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                PRIMARY KEY (agent_id, user_id)
            );
        """)

        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin")
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (admin_username,)
        ).fetchone()
        admin_id = None
        if not existing:
            admin_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (admin_id, admin_username, pwd_context.hash(admin_password), "admin", now),
            )
        else:
            admin_id = existing["id"]

        # Seed default agent from env vars
        seed_alias = os.environ.get("SEED_AGENT_ALIAS", "").strip()
        if seed_alias:
            seed_voice = os.environ.get("SEED_AGENT_VOICE", "Cherry").strip()
            seed_prompt = os.environ.get("SEED_AGENT_SYSTEM_PROMPT", "").strip()
            seed_owner = os.environ.get("SEED_AGENT_OWNER", admin_username).strip()

            owner_row = conn.execute(
                "SELECT id FROM users WHERE username = ?", (seed_owner,)
            ).fetchone()
            owner_id = owner_row["id"] if owner_row else admin_id

            existing_agent = conn.execute(
                "SELECT id FROM agents WHERE alias = ? AND owner_id = ?",
                (seed_alias, owner_id),
            ).fetchone()

            if not existing_agent:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), seed_alias, seed_voice, seed_prompt, owner_id, now),
                )

        conn.commit()
    finally:
        conn.close()

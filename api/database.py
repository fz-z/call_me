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
        if not existing:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), admin_username, pwd_context.hash(admin_password), "admin", now),
            )
        conn.commit()
    finally:
        conn.close()

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

        # Migration: add source_agent_id to distinguish root agents from copies
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN source_agent_id TEXT REFERENCES agents(id)")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: model_configs table for LLM config pool
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                api_key TEXT NOT NULL,
                temperature REAL NOT NULL DEFAULT 0.7,
                max_tokens INTEGER NOT NULL DEFAULT 2048,
                created_at TEXT NOT NULL
            )
        """)

        # Migration: add model_config_id to agents
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN model_config_id TEXT REFERENCES model_configs(id) ON DELETE SET NULL")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: voices table for voice pool
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                voice_id TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'cloned',
                created_at TEXT NOT NULL
            )
        """)

        # Migration: add voice_pool_id to agents
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN voice_pool_id TEXT REFERENCES voices(id)")
        except sqlite3.OperationalError:
            pass

        # Seed built-in voices
        builtins = [
            ("Cherry", "Cherry"),
            ("Stella", "Stella"),
            ("Luna", "Luna"),
            ("Scott", "Scott"),
            ("Kevin", "Kevin"),
        ]
        for name, vid in builtins:
            existing = conn.execute(
                "SELECT id FROM voices WHERE name = ?", (name,)
            ).fetchone()
            if not existing:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), name, vid, "builtin", now),
                )

        # Migration: tts_configs table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tts_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                api_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Migration: voice_tts_links many-to-many table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_tts_links (
                voice_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
                tts_config_id TEXT NOT NULL REFERENCES tts_configs(id) ON DELETE CASCADE,
                PRIMARY KEY (voice_id, tts_config_id)
            )
        """)

        # Migration: add tts_config_id to agents
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN tts_config_id TEXT REFERENCES tts_configs(id)")
        except sqlite3.OperationalError:
            pass

        # Seed TTS configs
        dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
        tts_seeds = [
            ("通义通用TTS", "qwen", "qwen3-tts-flash-realtime"),
            ("通义VC", "qwen", "qwen3-tts-vc-realtime-2026-01-15"),
        ]
        tts_ids = {}
        for name, provider, model in tts_seeds:
            existing = conn.execute("SELECT id FROM tts_configs WHERE name = ?", (name,)).fetchone()
            if not existing:
                tid = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO tts_configs (id, name, provider, model, api_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (tid, name, provider, model, dashscope_key, now),
                )
                tts_ids[name] = tid
            else:
                tts_ids[name] = existing["id"]

        # Seed voice_tts_links: built-in voices → 通义通用TTS, cloned voices → 通义VC
        if tts_ids:
            builtin_tts_id = tts_ids.get("通义通用TTS")
            vc_tts_id = tts_ids.get("通义VC")
            builtins = conn.execute("SELECT id FROM voices WHERE type = 'builtin'").fetchall()
            cloned = conn.execute("SELECT id FROM voices WHERE type = 'cloned'").fetchall()
            for v in builtins:
                if builtin_tts_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
                        (v["id"], builtin_tts_id),
                    )
            for v in cloned:
                if vc_tts_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
                        (v["id"], vc_tts_id),
                    )

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

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

        # Seed built-in voices — only when table is empty AND user explicitly set SEED_BUILTIN_VOICES
        voice_count = conn.execute("SELECT COUNT(*) FROM voices").fetchone()[0]
        raw_voices = os.environ.get("SEED_BUILTIN_VOICES")
        if voice_count == 0 and raw_voices:
            builtins = [(v.strip(), v.strip()) for v in raw_voices.split(",") if v.strip()]
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

        # Migration: audition_text on voices
        try:
            conn.execute("ALTER TABLE voices ADD COLUMN audition_text TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add tts_config_id to agents
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN tts_config_id TEXT REFERENCES tts_configs(id)")
        except sqlite3.OperationalError:
            pass

        # Migration: add supports_voice_clone to tts_configs (before seed)
        try:
            conn.execute("ALTER TABLE tts_configs ADD COLUMN supports_voice_clone INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            pass

        # Seed TTS configs — each seeds independently when .env has its model
        dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
        tts_ids = {}
        tts_count = conn.execute("SELECT COUNT(*) FROM tts_configs").fetchone()[0]
        flash_model = os.environ.get("SEED_TTS_FLASH_MODEL")
        vc_model = os.environ.get("SEED_TTS_VC_MODEL")
        tts_seeds = []
        if tts_count == 0:
            if flash_model:
                tts_seeds.append(("通义通用TTS", "qwen", flash_model))
            if vc_model:
                tts_seeds.append(("通义VC", "qwen", vc_model))
        if tts_seeds:
            for name, provider, model in tts_seeds:
                existing = conn.execute("SELECT id FROM tts_configs WHERE name = ?", (name,)).fetchone()
                if not existing:
                    tid = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()
                    supports_clone = 1 if "VC" in name or "vc" in model else 0
                    conn.execute(
                        "INSERT INTO tts_configs (id, name, provider, model, api_key, supports_voice_clone, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (tid, name, provider, model, dashscope_key, supports_clone, now),
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

        # Seed default model_config — only when table is empty AND user explicitly set DEFAULT_LLM_MODEL
        mc_count = conn.execute("SELECT COUNT(*) FROM model_configs").fetchone()[0]
        default_llm = os.environ.get("DEFAULT_LLM_MODEL")
        if mc_count == 0 and default_llm:
            mc_id = str(uuid.uuid4())
            mc_now = datetime.now(timezone.utc).isoformat()
            default_temp = float(os.environ.get("DEFAULT_LLM_TEMPERATURE", "0.7"))
            default_max_tokens = int(os.environ.get("DEFAULT_MAX_TOKENS", "2048"))
            conn.execute(
                "INSERT INTO model_configs (id, name, provider, model, api_key, temperature, max_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (mc_id, "Qwen Plus", "qwen", default_llm, dashscope_key, default_temp, default_max_tokens, mc_now),
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

        # Migration: api_keys table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL,
                api_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Seed API keys from .env — only when table is completely empty (first run)
        dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        api_key_ids = {}
        key_count = conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        if key_count == 0:
            key_seeds = []
            if dashscope_key:
                key_seeds.append(("DashScope", "qwen", dashscope_key))
            if deepseek_key:
                key_seeds.append(("DeepSeek", "deepseek", deepseek_key))
            for name, provider, api_key in key_seeds:
                existing = conn.execute("SELECT id FROM api_keys WHERE name = ?", (name,)).fetchone()
                if not existing:
                    kid = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "INSERT INTO api_keys (id, name, provider, api_key, created_at) VALUES (?, ?, ?, ?, ?)",
                        (kid, name, provider, api_key, now),
                    )
                    api_key_ids[name] = kid
                else:
                    api_key_ids[name] = existing["id"]

        # Migration: add api_key_id to model_configs (replace api_key column)
        try:
            conn.execute("ALTER TABLE model_configs ADD COLUMN api_key_id TEXT REFERENCES api_keys(id)")
        except sqlite3.OperationalError:
            pass

        # Migration: add api_key_id to tts_configs
        try:
            conn.execute("ALTER TABLE tts_configs ADD COLUMN api_key_id TEXT REFERENCES api_keys(id)")
        except sqlite3.OperationalError:
            pass

        # Migration: add supports_voice_clone to tts_configs
        try:
            conn.execute("ALTER TABLE tts_configs ADD COLUMN supports_voice_clone INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        if api_key_ids:
            for mc in conn.execute("SELECT id, provider FROM model_configs WHERE api_key_id IS NULL").fetchall():
                key_name = "DashScope" if mc["provider"] == "qwen" else "DeepSeek"
                if key_name in api_key_ids:
                    conn.execute("UPDATE model_configs SET api_key_id = ? WHERE id = ?",
                                 (api_key_ids[key_name], mc["id"]))

            for tc in conn.execute("SELECT id, provider FROM tts_configs WHERE api_key_id IS NULL").fetchall():
                key_name = "DashScope" if tc["provider"] == "qwen" else "DeepSeek"
                if key_name in api_key_ids:
                    conn.execute("UPDATE tts_configs SET api_key_id = ? WHERE id = ?",
                                 (api_key_ids[key_name], tc["id"]))

        # Migration: call_logs table for call history and statistics
        conn.execute("""
            CREATE TABLE IF NOT EXISTS call_logs (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL REFERENCES agents(id),
                caller_user_id TEXT NOT NULL REFERENCES users(id),
                room_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_seconds INTEGER,
                status TEXT NOT NULL DEFAULT 'running'
            )
        """)

        conn.commit()
    finally:
        conn.close()

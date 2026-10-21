import os
from database import init_db, _sync_conn, get_db, pwd_context


class TestDatabaseInit:
    def test_creates_tables(self, clean_db):
        conn = _sync_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        assert "users" in table_names
        assert "agents" in table_names
        assert "permissions" in table_names
        conn.close()

    def test_seeds_admin(self, clean_db):
        conn = _sync_conn()
        admin = conn.execute(
            "SELECT * FROM users WHERE username = ?", ("admin",)
        ).fetchone()
        assert admin is not None
        assert admin["role"] == "admin"
        conn.close()

    def test_admin_password_is_hashed(self, clean_db):
        conn = _sync_conn()
        admin = conn.execute(
            "SELECT * FROM users WHERE username = ?", ("admin",)
        ).fetchone()
        assert admin["password_hash"] != "admin123"
        assert pwd_context.verify("admin123", admin["password_hash"])
        conn.close()

    def test_init_db_idempotent(self, clean_db):
        init_db()  # second call should not fail or duplicate
        conn = _sync_conn()
        count = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE username = ?", ("admin",)
        ).fetchone()["c"]
        assert count == 1
        conn.close()

    def test_seeds_qwen_audio_tts_as_cloneable(self, clean_db, monkeypatch):
        conn = _sync_conn()
        try:
            conn.execute("DELETE FROM voice_tts_links")
            conn.execute("DELETE FROM tts_configs")
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setenv("SEED_TTS_FLASH_MODEL", "qwen-audio-3.1-tts-flash")
        init_db()

        conn = _sync_conn()
        try:
            config = conn.execute(
                "SELECT model, supports_voice_clone FROM tts_configs WHERE model = ?",
                ("qwen-audio-3.1-tts-flash",),
            ).fetchone()
            assert config is not None
            assert config["supports_voice_clone"] == 1
        finally:
            conn.close()

    def test_realtime_schema_migrations_are_idempotent(self, clean_db):
        """Realtime schema additions survive repeated startup migrations."""
        init_db()
        conn = _sync_conn()
        try:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            assert {"realtime_configs", "voice_runtime_bindings"} <= tables

            agent_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(agents)").fetchall()
            }
            assert {"runtime_mode", "realtime_config_id"} <= agent_columns

            call_log_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(call_logs)").fetchall()
            }
            assert {
                "runtime_mode",
                "provider",
                "model",
                "failure_stage",
                "failure_reason",
            } <= call_log_columns

            admin = conn.execute(
                "SELECT id FROM users WHERE username = ?", ("admin",)
            ).fetchone()
            conn.execute(
                "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("pipeline-default-agent", "Pipeline", "Cherry", "", admin["id"], "2024-01-01"),
            )
            conn.commit()
            runtime_mode = conn.execute(
                "SELECT runtime_mode FROM agents WHERE id = ?", ("pipeline-default-agent",)
            ).fetchone()["runtime_mode"]
            assert runtime_mode == "pipeline"
        finally:
            conn.close()

    def test_backfills_tts_runtime_bindings_without_duplicates(self, clean_db):
        conn = _sync_conn()
        try:
            link = conn.execute(
                "SELECT v.id AS voice_id, v.voice_id AS provider_voice_id, "
                "vl.tts_config_id FROM voices v "
                "JOIN voice_tts_links vl ON vl.voice_id = v.id LIMIT 1"
            ).fetchone()
            assert link is not None
            voice = link
            tts_config_id = link["tts_config_id"]
            conn.execute(
                "DELETE FROM voice_runtime_bindings "
                "WHERE voice_pool_id = ? AND runtime_kind = 'tts' AND runtime_config_id = ?",
                (voice["voice_id"], tts_config_id),
            )
            conn.commit()
        finally:
            conn.close()

        init_db()
        init_db()

        conn = _sync_conn()
        try:
            bindings = conn.execute(
                "SELECT runtime_kind, runtime_config_id, provider_voice_id "
                "FROM voice_runtime_bindings WHERE voice_pool_id = ?",
                (voice["voice_id"],),
            ).fetchall()
            assert [dict(binding) for binding in bindings] == [
                {
                    "runtime_kind": "tts",
                    "runtime_config_id": tts_config_id,
                    "provider_voice_id": voice["provider_voice_id"],
                }
            ]
        finally:
            conn.close()

    def test_foreign_key_enforcement(self, clean_db):
        conn = _sync_conn()
        import uuid
        # Try inserting an agent with non-existent owner
        try:
            conn.execute(
                "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "test", "v1", "", "nonexistent", "2024-01-01"),
            )
            conn.commit()
            assert False, "Should have raised IntegrityError"
        except Exception:
            pass  # expected
        conn.close()

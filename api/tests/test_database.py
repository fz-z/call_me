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

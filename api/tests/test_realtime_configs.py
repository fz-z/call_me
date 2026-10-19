import uuid

from fastapi.testclient import TestClient

from main import app
from tests.test_auth import _admin_header


client = TestClient(app)


def _create_api_key(name="Qwen realtime key", provider="qwen"):
    response = client.post(
        "/api/admin/api-keys",
        headers=_admin_header(),
        json={"name": name, "provider": provider, "api_key": "secret-key-value"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_realtime_config(api_key_id, **overrides):
    payload = {
        "name": "Qwen realtime",
        "provider": "qwen",
        "model": "qwen-audio-3.1-realtime-plus",
        "api_key_id": api_key_id,
        "endpoint": "wss://dashscope.example/realtime",
        "region": "cn-beijing",
        "capabilities_json": '{"audio": true}',
    }
    payload.update(overrides)
    response = client.post(
        "/api/admin/realtime-configs", headers=_admin_header(), json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestRealtimeConfigCrud:
    def test_create_list_and_update_hide_api_key_value(self, clean_db):
        api_key_id = _create_api_key()

        created = _create_realtime_config(api_key_id)
        assert created["api_key_id"] == api_key_id
        assert created["provider"] == "qwen"
        assert "api_key" not in created

        listed = client.get("/api/admin/realtime-configs", headers=_admin_header())
        assert listed.status_code == 200
        assert listed.json() == [created]
        assert "secret-key-value" not in listed.text

        updated = client.patch(
            f"/api/admin/realtime-configs/{created['id']}",
            headers=_admin_header(),
            json={"name": "Updated realtime", "region": "cn-shanghai"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Updated realtime"
        assert updated.json()["region"] == "cn-shanghai"
        assert "api_key" not in updated.json()

    def test_rejects_unsupported_provider_and_model(self, clean_db):
        api_key_id = _create_api_key()

        unsupported_provider = client.post(
            "/api/admin/realtime-configs",
            headers=_admin_header(),
            json={
                "name": "Other provider",
                "provider": "other",
                "model": "qwen-audio-3.1-realtime-plus",
                "api_key_id": api_key_id,
            },
        )
        assert unsupported_provider.status_code == 400
        assert "provider" in unsupported_provider.json()["detail"].lower()

        unsupported_model = client.post(
            "/api/admin/realtime-configs",
            headers=_admin_header(),
            json={
                "name": "Other model",
                "provider": "qwen",
                "model": "qwen-audio-other",
                "api_key_id": api_key_id,
            },
        )
        assert unsupported_model.status_code == 400
        assert "model" in unsupported_model.json()["detail"].lower()

    def test_api_key_reference_must_exist_and_match_provider(self, clean_db):
        missing_key = client.post(
            "/api/admin/realtime-configs",
            headers=_admin_header(),
            json={
                "name": "Missing key",
                "provider": "qwen",
                "model": "qwen-audio-3.1-realtime-plus",
                "api_key_id": "does-not-exist",
            },
        )
        assert missing_key.status_code == 400
        assert "api key" in missing_key.json()["detail"].lower()

        other_provider_key_id = _create_api_key("DeepSeek key", "deepseek")
        mismatched_key = client.post(
            "/api/admin/realtime-configs",
            headers=_admin_header(),
            json={
                "name": "Mismatched key",
                "provider": "qwen",
                "model": "qwen-audio-3.1-realtime-plus",
                "api_key_id": other_provider_key_id,
            },
        )
        assert mismatched_key.status_code == 400
        assert "provider" in mismatched_key.json()["detail"].lower()

    def test_delete_rejects_agent_and_voice_binding_references(self, clean_db):
        config = _create_realtime_config(_create_api_key())
        from database import _sync_conn

        db = _sync_conn()
        try:
            admin = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
            voice = db.execute("SELECT id FROM voices LIMIT 1").fetchone()
            db.execute(
                "INSERT INTO agents "
                "(id, alias, voice_id, system_prompt, owner_id, realtime_config_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    "Realtime agent",
                    "Cherry",
                    "",
                    admin["id"],
                    config["id"],
                    "2026-10-19T00:00:00+00:00",
                ),
            )
            db.execute(
                "INSERT INTO voice_runtime_bindings "
                "(id, voice_pool_id, runtime_kind, runtime_config_id, provider_voice_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    voice["id"],
                    "realtime",
                    config["id"],
                    "provider-voice-id",
                    "2026-10-19T00:00:00+00:00",
                ),
            )
            db.commit()
        finally:
            db.close()

        response = client.delete(
            f"/api/admin/realtime-configs/{config['id']}", headers=_admin_header()
        )
        assert response.status_code == 409
        assert response.json()["detail"]["reference_count"] == 2

    def test_delete_unreferenced_config(self, clean_db):
        config = _create_realtime_config(_create_api_key())

        response = client.delete(
            f"/api/admin/realtime-configs/{config['id']}", headers=_admin_header()
        )
        assert response.status_code == 204

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# Reuse auth helpers from test_auth
from tests.test_auth import _auth_header, _admin_header


def _get_voice_pool_id(db=None):
    """Get a voice_pool_id from the seeded built-in voices."""
    from database import _sync_conn
    conn = _sync_conn()
    try:
        row = conn.execute("SELECT id FROM voices WHERE name = 'Cherry'").fetchone()
        return row["id"]
    finally:
        conn.close()


def _create_realtime_config(voice_pool_id, *, with_binding=True):
    key = client.post(
        "/api/admin/api-keys",
        headers=_admin_header(),
        json={
            "name": f"Agent runtime key {uuid.uuid4()}",
            "provider": "qwen",
            "api_key": "agent-runtime-secret",
        },
    )
    assert key.status_code == 200, key.text
    config = client.post(
        "/api/admin/realtime-configs",
        headers=_admin_header(),
        json={
            "name": f"Agent runtime config {uuid.uuid4()}",
            "provider": "qwen",
            "model": "qwen-audio-3.1-realtime-plus",
            "api_key_id": key.json()["id"],
            "endpoint": "wss://realtime.example.test",
            "capabilities_json": json.dumps({"voice_clone": True}),
        },
    )
    assert config.status_code == 200, config.text
    if with_binding:
        from database import _sync_conn

        db = _sync_conn()
        try:
            db.execute(
                "INSERT INTO voice_runtime_bindings "
                "(id, voice_pool_id, runtime_kind, runtime_config_id, provider_voice_id, created_at) "
                "VALUES (?, ?, 'realtime', ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    voice_pool_id,
                    config.json()["id"],
                    "private-realtime-voice",
                    "2026-10-19T00:00:00+00:00",
                ),
            )
            db.commit()
        finally:
            db.close()
    return config.json()


class TestAgentCRUD:
    def test_list_empty(self, clean_db):
        resp = client.get("/api/agents", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_agent(self, clean_db):
        voice_pool_id = _get_voice_pool_id()

        resp = client.post(
            "/api/agents",
            headers=_auth_header(),
            json={"alias": "Test Agent", "system_prompt": "Be helpful", "voice_pool_id": voice_pool_id},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["alias"] == "Test Agent"
        # Provider-specific voice ids are worker-only secrets.  Clients select
        # a pool entry by its opaque id instead.
        assert "voice_id" not in data
        assert data["voice_pool_id"] == voice_pool_id
        assert data["system_prompt"] == "Be helpful"

    def test_agent_speech_rate_round_trip_and_validation(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        response = client.post(
            "/api/agents",
            headers=_auth_header(),
            json={
                "alias": "Rate Agent",
                "voice_pool_id": voice_pool_id,
                "speech_rate": 1.3,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["speech_rate"] == 1.3
        agent_id = data["id"]

        from database import _sync_conn
        from config_utils import resolve_agent_runtime_config

        db = _sync_conn()
        try:
            row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            runtime = resolve_agent_runtime_config(db, row)
        finally:
            db.close()
        assert runtime["speech_rate"] == 1.3

        updated = client.patch(
            f"/api/agents/{agent_id}",
            headers=_auth_header(),
            json={"speech_rate": 0.8},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["speech_rate"] == 0.8

        invalid = client.post(
            "/api/agents",
            headers=_auth_header(),
            json={
                "alias": "Invalid rate",
                "voice_pool_id": voice_pool_id,
                "speech_rate": 2.5,
            },
        )
        assert invalid.status_code == 400

    def test_pipeline_agent_defaults_to_pipeline_runtime(self, clean_db):
        response = client.post(
            "/api/agents",
            headers=_auth_header(),
            json={"alias": "Pipeline", "voice_pool_id": _get_voice_pool_id()},
        )

        assert response.status_code == 200, response.text
        assert response.json()["runtime_mode"] == "pipeline"
        assert response.json()["realtime_config_id"] is None

    def test_realtime_agent_requires_a_config_and_exact_voice_binding(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        missing_config = client.post(
            "/api/agents",
            headers=_auth_header(),
            json={
                "alias": "Missing config",
                "voice_pool_id": voice_pool_id,
                "runtime_mode": "realtime",
            },
        )
        config_without_binding = _create_realtime_config(voice_pool_id, with_binding=False)
        missing_binding = client.post(
            "/api/agents",
            headers=_auth_header(),
            json={
                "alias": "Missing binding",
                "voice_pool_id": voice_pool_id,
                "runtime_mode": "realtime",
                "realtime_config_id": config_without_binding["id"],
            },
        )

        assert missing_config.status_code == 400
        assert missing_binding.status_code == 400

    def test_realtime_agent_persists_selected_runtime_without_pipeline_defaults(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        config = _create_realtime_config(voice_pool_id)

        response = client.post(
            "/api/agents",
            headers=_auth_header(),
            json={
                "alias": "Realtime",
                "voice_pool_id": voice_pool_id,
                "runtime_mode": "realtime",
                "realtime_config_id": config["id"],
                "model_config_id": "",
                "tts_config_id": "",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["runtime_mode"] == "realtime"
        assert response.json()["realtime_config_id"] == config["id"]
        assert response.json()["model_config_id"] is None
        assert response.json()["tts_config_id"] is None

    def test_updating_to_realtime_requires_a_config_and_exact_voice_binding(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        headers = _auth_header("mode-updater", "pw")
        pipeline_agent = client.post(
            "/api/agents",
            headers=headers,
            json={"alias": "Mode updater", "voice_pool_id": voice_pool_id},
        )
        assert pipeline_agent.status_code == 200, pipeline_agent.text
        config = _create_realtime_config(voice_pool_id, with_binding=False)

        no_config = client.patch(
            f"/api/agents/{pipeline_agent.json()['id']}",
            headers=headers,
            json={"runtime_mode": "realtime"},
        )
        no_binding = client.patch(
            f"/api/agents/{pipeline_agent.json()['id']}",
            headers=headers,
            json={"runtime_mode": "realtime", "realtime_config_id": config["id"]},
        )

        assert no_config.status_code == 400
        assert no_binding.status_code == 400

    def test_list_after_create(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        headers = _auth_header()

        client.post(
            "/api/agents", headers=headers,
            json={"alias": "Agent 1", "system_prompt": "Prompt 1", "voice_pool_id": voice_pool_id},
        )
        client.post(
            "/api/agents", headers=headers,
            json={"alias": "Agent 2", "system_prompt": "Prompt 2", "voice_pool_id": voice_pool_id},
        )

        resp = client.get("/api/agents", headers=headers)
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) == 2

    def test_get_agent(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        headers = _auth_header("owner", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            json={"alias": "Get Me", "system_prompt": "Hi", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        resp = client.get(f"/api/agents/{agent_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["alias"] == "Get Me"

    def test_update_agent(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        headers = _auth_header("updater", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            json={"alias": "Old Name", "system_prompt": "Old Prompt", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        resp = client.patch(
            f"/api/agents/{agent_id}", headers=headers,
            json={"alias": "New Name", "system_prompt": "New Prompt"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["alias"] == "New Name"
        assert data["system_prompt"] == "New Prompt"

    def test_delete_agent(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        headers = _auth_header("deleter", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            json={"alias": "Delete Me", "system_prompt": "Bye", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        resp = client.delete(f"/api/agents/{agent_id}", headers=headers)
        assert resp.status_code == 204

        # Verify deleted
        resp = client.get(f"/api/agents/{agent_id}", headers=headers)
        assert resp.status_code == 404

    def test_cannot_access_others_agent(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("owner", "pw")

        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "Private Agent", "system_prompt": "Secret", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        other_headers = _auth_header("intruder", "pw")
        resp = client.get(f"/api/agents/{agent_id}", headers=other_headers)
        assert resp.status_code == 404

    def test_admin_can_access_all(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        headers = _auth_header("someone", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            json={"alias": "Someone Agent", "system_prompt": "Prompt", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        admin_resp = client.get(f"/api/agents/{agent_id}", headers=_admin_header())
        assert admin_resp.status_code == 200

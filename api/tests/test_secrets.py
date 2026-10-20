import base64
import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app
from tests.test_auth import _auth_header, _admin_header

client = TestClient(app)

WORKER_HEADERS = {"X-Worker-Secret": os.environ.get("WORKER_INTERNAL_SECRET", "test-worker-secret")}


def _decode_agent_config_from_token(token: str) -> dict:
    payload_b64 = token.split(".")[1]
    padding = "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    attrs = payload.get("attributes") or {}
    if isinstance(attrs, str):
        attrs = json.loads(attrs)
    raw = attrs.get("agent_config", "{}")
    return json.loads(raw) if isinstance(raw, str) else raw


def _get_voice_pool_id():
    from database import _sync_conn

    conn = _sync_conn()
    try:
        row = conn.execute("SELECT id FROM voices WHERE name = 'Cherry'").fetchone()
        return row["id"]
    finally:
        conn.close()


class TestApiKeyResponses:
    def test_list_api_keys_never_returns_plaintext(self, clean_db):
        create = client.post(
            "/api/admin/api-keys",
            headers=_admin_header(),
            json={"name": "DashScope-SecretsTest", "provider": "qwen", "api_key": "sk-super-secret-key-12345"},
        )
        assert create.status_code == 200
        assert create.json()["api_key_preview"] == "sk-s...2345"
        assert "api_key" not in create.json()

        listed = client.get("/api/admin/api-keys", headers=_admin_header())
        assert listed.status_code == 200
        item = listed.json()[0]
        assert "api_key" not in item
        assert item["api_key_preview"] == "sk-s...2345"
        assert "sk-super-secret-key-12345" not in json.dumps(listed.json())


class TestCallTokenSecrets:
    def test_token_agent_config_has_no_api_keys(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller_secrets", "pw")
        agent_id = client.post(
            "/api/agents",
            headers=owner_headers,
            json={"alias": "SecretBot", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        ).json()["id"]

        resp = client.post(
            "/api/call/token",
            headers=owner_headers,
            json={"agent_id": agent_id},
        )
        assert resp.status_code == 200
        cfg = _decode_agent_config_from_token(resp.json()["token"])
        assert set(cfg) == {"agent_id", "runtime_mode", "call_log_id"}
        assert cfg["agent_id"] == agent_id
        assert cfg["runtime_mode"] == "pipeline"
        assert "sk-" not in json.dumps(cfg)

    def test_worker_returns_realtime_secrets_for_the_exact_selected_binding(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        key = client.post(
            "/api/admin/api-keys",
            headers=_admin_header(),
            json={"name": f"Worker realtime key {uuid.uuid4()}", "provider": "qwen", "api_key": "worker-realtime-secret"},
        )
        assert key.status_code == 200, key.text
        config = client.post(
            "/api/admin/realtime-configs",
            headers=_admin_header(),
            json={
                "name": f"Worker realtime config {uuid.uuid4()}",
                "provider": "qwen",
                "model": "qwen-audio-3.1-realtime-plus",
                "api_key_id": key.json()["id"],
                "endpoint": "wss://worker-realtime.example.test",
            },
        )
        assert config.status_code == 200, config.text
        from database import _sync_conn

        db = _sync_conn()
        try:
            db.execute(
                "INSERT INTO voice_runtime_bindings "
                "(id, voice_pool_id, runtime_kind, runtime_config_id, provider_voice_id, created_at) "
                "VALUES (?, ?, 'realtime', ?, ?, ?)",
                (str(uuid.uuid4()), voice_pool_id, config.json()["id"], "worker-private-voice", "2026-10-19T00:00:00+00:00"),
            )
            db.commit()
        finally:
            db.close()

        owner_headers = _auth_header("realtime_worker", "pw")
        agent = client.post(
            "/api/agents",
            headers=owner_headers,
            json={
                "alias": "Realtime worker",
                "voice_pool_id": voice_pool_id,
                "runtime_mode": "realtime",
                "realtime_config_id": config.json()["id"],
            },
        )
        assert agent.status_code == 200, agent.text

        response = client.get(
            f"/api/internal/worker/agent-runtime/{agent.json()['id']}",
            headers=WORKER_HEADERS,
        )

        assert response.status_code == 200, response.text
        runtime = response.json()
        assert runtime["runtime_mode"] == "realtime"
        assert runtime["realtime_config"] == {
            "provider": "qwen",
            "model": "qwen-audio-3.1-realtime-plus",
            "endpoint": "wss://worker-realtime.example.test",
            "api_key": "worker-realtime-secret",
            "voice_id": "worker-private-voice",
        }
        assert "model_config" not in runtime
        assert "tts_config" not in runtime

    def test_worker_runtime_endpoint_returns_secrets(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller_worker", "pw")
        agent_id = client.post(
            "/api/agents",
            headers=owner_headers,
            json={"alias": "WorkerBot", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        ).json()["id"]

        resp = client.get(
            f"/api/internal/worker/agent-runtime/{agent_id}",
            headers=WORKER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == agent_id
        # Seeded DB has default model/tts with keys from env
        assert data.get("model_config") is None or "api_key" in data.get("model_config", {})

    def test_worker_runtime_rejects_missing_secret(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        agent_id = client.post(
            "/api/agents",
            headers=_auth_header("caller_bad", "pw"),
            json={"alias": "Bad", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        ).json()["id"]
        resp = client.get(f"/api/internal/worker/agent-runtime/{agent_id}")
        assert resp.status_code == 403

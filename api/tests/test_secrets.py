import base64
import json
import os

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
        assert cfg["agent_id"] == agent_id
        assert "model_config" not in cfg
        assert "tts_config" not in cfg
        assert "sk-" not in json.dumps(cfg)

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

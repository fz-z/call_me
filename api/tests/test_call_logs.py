import os
import uuid

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

from tests.test_auth import _auth_header, _admin_header

WORKER_HEADERS = {"X-Worker-Secret": os.environ.get("WORKER_INTERNAL_SECRET", "test-worker-secret")}


def _get_voice_pool_id():
    from database import _sync_conn
    conn = _sync_conn()
    try:
        row = conn.execute("SELECT id FROM voices WHERE name = 'Cherry'").fetchone()
        return row["id"]
    finally:
        conn.close()


class TestCallLog:
    def test_token_creates_call_log(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller1", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        resp = client.post(
            "/api/call/token", headers=owner_headers,
            json={"agent_id": agent_id},
        )
        assert resp.status_code == 200
        token_data = resp.json()
        assert "token" in token_data
        assert "room_url" in token_data

    def test_end_call_log(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller2", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot2", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        resp = client.post(
            "/api/call/token", headers=owner_headers,
            json={"agent_id": agent_id},
        )
        assert resp.status_code == 200

        # Query DB directly for the latest call_log
        from database import _sync_conn
        conn = _sync_conn()
        try:
            log = conn.execute("SELECT id FROM call_logs ORDER BY started_at DESC LIMIT 1").fetchone()
            call_log_id = log["id"]
        finally:
            conn.close()

        resp = client.patch(
            f"/api/call/admin/call-logs/{call_log_id}/end",
            json={"status": "completed", "duration_seconds": 45},
            headers=WORKER_HEADERS,
        )
        assert resp.status_code == 204

        # Verify the log was updated
        conn = _sync_conn()
        try:
            log = conn.execute("SELECT * FROM call_logs WHERE id = ?", (call_log_id,)).fetchone()
            assert log["status"] == "completed"
            assert log["duration_seconds"] == 45
            assert log["ended_at"] is not None
        finally:
            conn.close()

    def test_call_log_records_runtime_and_sanitized_failure_diagnostics(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("runtime-log-caller", "pw")
        agent_id = client.post(
            "/api/agents",
            headers=owner_headers,
            json={"alias": "Runtime log", "voice_pool_id": voice_pool_id},
        ).json()["id"]
        assert client.post("/api/call/token", headers=owner_headers, json={"agent_id": agent_id}).status_code == 200

        from database import _sync_conn
        conn = _sync_conn()
        try:
            log = conn.execute("SELECT * FROM call_logs ORDER BY started_at DESC LIMIT 1").fetchone()
            call_log_id = log["id"]
            assert log["runtime_mode"] == "pipeline"
            assert log["provider"] == "qwen"
            assert log["model"] == "qwen-plus"
        finally:
            conn.close()

        finished = client.patch(
            f"/api/call/admin/call-logs/{call_log_id}/end",
            headers=WORKER_HEADERS,
            json={
                "status": "failed",
                "duration_seconds": 0,
                "failure_stage": "provider_connect",
                "failure_reason": "connection_failed",
            },
        )
        assert finished.status_code == 204, finished.text

        conn = _sync_conn()
        try:
            log = conn.execute("SELECT * FROM call_logs WHERE id = ?", (call_log_id,)).fetchone()
            assert log["failure_stage"] == "provider_connect"
            assert log["failure_reason"] == "connection_failed"
        finally:
            conn.close()

    def test_incomplete_realtime_configuration_creates_no_call_log(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        from database import _sync_conn

        config_id = str(uuid.uuid4())
        db = _sync_conn()
        try:
            db.execute(
                "INSERT INTO realtime_configs "
                "(id, name, provider, model, endpoint, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (config_id, "Incomplete runtime", "qwen", "qwen-audio-3.1-realtime-plus", "", "2026-10-19T00:00:00+00:00"),
            )
            db.execute(
                "INSERT INTO voice_runtime_bindings "
                "(id, voice_pool_id, runtime_kind, runtime_config_id, provider_voice_id, created_at) "
                "VALUES (?, ?, 'realtime', ?, ?, ?)",
                (str(uuid.uuid4()), voice_pool_id, config_id, "private-voice", "2026-10-19T00:00:00+00:00"),
            )
            db.commit()
        finally:
            db.close()

        owner_headers = _auth_header("incomplete-realtime", "pw")
        agent = client.post(
            "/api/agents",
            headers=owner_headers,
            json={
                "alias": "Incomplete realtime",
                "voice_pool_id": voice_pool_id,
                "runtime_mode": "realtime",
                "realtime_config_id": config_id,
            },
        )
        assert agent.status_code == 200, agent.text
        response = client.post("/api/call/token", headers=owner_headers, json={"agent_id": agent.json()["id"]})

        assert response.status_code == 400
        db = _sync_conn()
        try:
            assert db.execute("SELECT COUNT(*) FROM call_logs").fetchone()[0] == 0
        finally:
            db.close()


class TestCallLogList:
    def test_list_empty(self, clean_db):
        resp = client.get("/api/admin/call-logs", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_with_records(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller3", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot3", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        for _ in range(2):
            client.post("/api/call/token", headers=owner_headers, json={"agent_id": agent_id})

        resp = client.get("/api/admin/call-logs", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        item = data["items"][0]
        assert item["agent_alias"] == "TestBot3"
        assert item["status"] == "running"

    def test_list_requires_admin(self, clean_db):
        resp = client.get("/api/admin/call-logs")
        assert resp.status_code == 401

    def test_list_filter_by_agent(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller4", "pw")
        create_resp1 = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "BotA", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        create_resp2 = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "BotB", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp1.json()["id"]})
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp2.json()["id"]})

        resp = client.get(
            f"/api/admin/call-logs?agent_id={create_resp1.json()['id']}",
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["agent_alias"] == "BotA"


class TestStats:
    def test_overview_empty(self, clean_db):
        resp = client.get("/api/admin/stats/overview", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 0
        assert data["today_calls"] == 0
        assert data["active_users"] == 0

    def test_overview_with_records(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller5", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot5", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": agent_id})

        resp = client.get("/api/admin/stats/overview", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 1
        assert data["today_calls"] == 1
        assert data["active_users"] == 1

    def test_trend(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller6", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot6", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp.json()["id"]})

        resp = client.get("/api/admin/stats/trend?days=30", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 0

    def test_top_agents(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller7", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TopBot", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp.json()["id"]})

        resp = client.get("/api/admin/stats/top-agents?limit=10", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["name"] == "TopBot"

    def test_top_users(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller8", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot8", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp.json()["id"]})

        resp = client.get("/api/admin/stats/top-users?limit=10", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["name"] == "caller8"

    def test_stats_require_admin(self, clean_db):
        endpoints = [
            "/api/admin/stats/overview",
            "/api/admin/stats/trend",
            "/api/admin/stats/top-agents",
            "/api/admin/stats/top-users",
        ]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 401, f"{ep} should require admin"

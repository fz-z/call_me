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
        assert data["voice_id"] == "Cherry"
        assert data["voice_pool_id"] == voice_pool_id
        assert data["system_prompt"] == "Be helpful"

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

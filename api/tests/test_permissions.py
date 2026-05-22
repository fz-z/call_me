import io
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

from tests.test_auth import _auth_header, _admin_header


class TestPermissions:
    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_grant_and_access(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_grant"
        owner_headers = _auth_header("owner", "pw")

        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            data={"alias": "Sharable", "system_prompt": "Share"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )
        agent_id = create_resp.json()["id"]

        # Register another user
        client.post("/api/auth/register", json={"username": "receiver", "password": "pw"})

        # Admin grants permission
        resp = client.post(
            f"/api/agents/{agent_id}/grant",
            headers=_admin_header(),
            json={"username": "receiver"},
        )
        assert resp.status_code == 200
        assert resp.json()["agent_id"] == agent_id

        # Receiver can now access
        receiver_resp = client.post("/api/auth/login", json={"username": "receiver", "password": "pw"})
        receiver_token = receiver_resp.json()["token"]
        receiver_headers = {"Authorization": f"Bearer {receiver_token}"}

        resp = client.get(f"/api/agents/{agent_id}", headers=receiver_headers)
        assert resp.status_code == 200

    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_revoke_access(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_revoke"
        owner_headers = _auth_header("owner2", "pw")

        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            data={"alias": "Revocable", "system_prompt": "Revoke"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )
        agent_id = create_resp.json()["id"]

        client.post("/api/auth/register", json={"username": "target", "password": "pw"})
        client.post(
            f"/api/agents/{agent_id}/grant",
            headers=_admin_header(),
            json={"username": "target"},
        )

        # Revoke
        resp = client.delete(
            f"/api/agents/{agent_id}/grant/target",
            headers=_admin_header(),
        )
        assert resp.status_code == 204

        # Target can no longer access
        target_resp = client.post("/api/auth/login", json={"username": "target", "password": "pw"})
        target_token = target_resp.json()["token"]
        target_headers = {"Authorization": f"Bearer {target_token}"}

        resp = client.get(f"/api/agents/{agent_id}", headers=target_headers)
        assert resp.status_code == 404

    def test_non_admin_cannot_grant(self, clean_db):
        headers = _auth_header("normal", "pw")
        # agent_id doesn't need to exist for this test
        resp = client.post(
            "/api/agents/nonexistent/grant",
            headers=headers,
            json={"username": "someone"},
        )
        assert resp.status_code == 403

    def test_grant_nonexistent_user(self, clean_db):
        resp = client.post(
            "/api/agents/some-id/grant",
            headers=_admin_header(),
            json={"username": "ghost"},
        )
        assert resp.status_code == 404

    def test_grant_nonexistent_agent(self, clean_db):
        client.post("/api/auth/register", json={"username": "realuser", "password": "pw"})
        resp = client.post(
            "/api/agents/fake-agent-id/grant",
            headers=_admin_header(),
            json={"username": "realuser"},
        )
        assert resp.status_code == 404


class TestCallToken:
    @patch("call.lk_api.AccessToken")
    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_get_token(self, mock_enroll, mock_access_token, clean_db):
        mock_enroll.return_value = "voice_token"
        # Setup the mock for AccessToken
        mock_token_instance = MagicMock()
        mock_token_instance.to_jwt.return_value = "fake_jwt_token"
        mock_access_token.return_value.with_identity.return_value = mock_token_instance
        mock_token_instance.with_name.return_value = mock_token_instance
        mock_token_instance.with_attributes.return_value = mock_token_instance
        mock_token_instance.with_grants.return_value = mock_token_instance

        headers = _auth_header("caller", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            data={"alias": "Call Agent", "system_prompt": "Answer calls"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )
        agent_id = create_resp.json()["id"]

        resp = client.post(
            "/api/call/token", headers=headers,
            json={"agent_id": agent_id},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "token" in data
        assert data["room_url"].startswith("wss")

    def test_get_token_no_permission(self, clean_db):
        headers = _auth_header("noaccess", "pw")
        resp = client.post(
            "/api/call/token", headers=headers,
            json={"agent_id": "some-nonexistent-id"},
        )
        assert resp.status_code == 404


class TestAdmin:
    def test_list_users(self, clean_db):
        client.post("/api/auth/register", json={"username": "u1", "password": "pw"})
        resp = client.get("/api/admin/users", headers=_admin_header())
        assert resp.status_code == 200
        users = resp.json()
        usernames = [u["username"] for u in users]
        assert "admin" in usernames
        assert "u1" in usernames

    def test_list_all_agents_admin(self, clean_db):
        resp = client.get("/api/admin/agents", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_non_admin_cannot_access_admin_endpoints(self, clean_db):
        headers = _auth_header("normie", "pw")
        resp = client.get("/api/admin/users", headers=headers)
        assert resp.status_code == 403

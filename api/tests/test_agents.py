import io
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# Reuse auth helpers from test_auth
from tests.test_auth import _auth_header, _admin_header


class TestAgentCRUD:
    def test_list_empty(self, clean_db):
        resp = client.get("/api/agents", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_create_agent(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_abc123"

        resp = client.post(
            "/api/agents",
            headers=_auth_header(),
            data={"alias": "Test Agent", "system_prompt": "Be helpful"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake audio"), "audio/wav")},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["alias"] == "Test Agent"
        assert data["voice_id"] == "voice_abc123"
        assert data["system_prompt"] == "Be helpful"

    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_list_after_create(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_xyz"
        headers = _auth_header()

        client.post(
            "/api/agents", headers=headers,
            data={"alias": "Agent 1", "system_prompt": "Prompt 1"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )
        mock_enroll.return_value = "voice_abc"
        client.post(
            "/api/agents", headers=headers,
            data={"alias": "Agent 2", "system_prompt": "Prompt 2"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )

        resp = client.get("/api/agents", headers=headers)
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) == 2

    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_get_agent(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_get"
        headers = _auth_header("owner", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            data={"alias": "Get Me", "system_prompt": "Hi"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )
        agent_id = create_resp.json()["id"]

        resp = client.get(f"/api/agents/{agent_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["alias"] == "Get Me"

    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_update_agent(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_upd"
        headers = _auth_header("updater", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            data={"alias": "Old Name", "system_prompt": "Old Prompt"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
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

    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_delete_agent(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_del"
        headers = _auth_header("deleter", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            data={"alias": "Delete Me", "system_prompt": "Bye"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )
        agent_id = create_resp.json()["id"]

        resp = client.delete(f"/api/agents/{agent_id}", headers=headers)
        assert resp.status_code == 204

        # Verify deleted
        resp = client.get(f"/api/agents/{agent_id}", headers=headers)
        assert resp.status_code == 404

    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_cannot_access_others_agent(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_priv"
        owner_headers = _auth_header("owner", "pw")

        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            data={"alias": "Private Agent", "system_prompt": "Secret"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )
        agent_id = create_resp.json()["id"]

        other_headers = _auth_header("intruder", "pw")
        resp = client.get(f"/api/agents/{agent_id}", headers=other_headers)
        assert resp.status_code == 404

    @patch("agents.enroll_voice", new_callable=AsyncMock)
    def test_admin_can_access_all(self, mock_enroll, clean_db):
        mock_enroll.return_value = "voice_admin"
        headers = _auth_header("someone", "pw")

        create_resp = client.post(
            "/api/agents", headers=headers,
            data={"alias": "Someone Agent", "system_prompt": "Prompt"},
            files={"audio_file": ("test.wav", io.BytesIO(b"fake"), "audio/wav")},
        )
        agent_id = create_resp.json()["id"]

        admin_resp = client.get(f"/api/agents/{agent_id}", headers=_admin_header())
        assert admin_resp.status_code == 200

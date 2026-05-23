import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

from tests.test_auth import _admin_header, _auth_header


def _get_first_voice_and_tts():
    from database import _sync_conn
    conn = _sync_conn()
    try:
        voice = conn.execute("SELECT * FROM voices LIMIT 1").fetchone()
        if not voice:
            return None, None, None
        link = conn.execute(
            "SELECT tc.id FROM tts_configs tc "
            "JOIN voice_tts_links vl ON tc.id = vl.tts_config_id "
            "WHERE vl.voice_id = ? LIMIT 1",
            (voice["id"],),
        ).fetchone()
        return voice, link["id"] if link else None, voice["id"]
    finally:
        conn.close()


class TestVoiceAuditionText:
    def test_update_audition_text(self, clean_db):
        voice, _, _ = _get_first_voice_and_tts()
        if not voice:
            pytest.skip("No voices in test db")

        resp = client.patch(
            f"/api/admin/voices/{voice['id']}",
            headers=_admin_header(),
            json={"audition_text": "这是一段试听文本"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == voice["name"]

        from database import _sync_conn
        conn = _sync_conn()
        try:
            row = conn.execute("SELECT audition_text FROM voices WHERE id = ?", (voice["id"],)).fetchone()
            assert row["audition_text"] == "这是一段试听文本"
        finally:
            conn.close()

    def test_clear_audition_text(self, clean_db):
        voice, _, _ = _get_first_voice_and_tts()
        if not voice:
            pytest.skip("No voices in test db")

        client.patch(
            f"/api/admin/voices/{voice['id']}",
            headers=_admin_header(),
            json={"audition_text": "something"},
        )
        resp = client.patch(
            f"/api/admin/voices/{voice['id']}",
            headers=_admin_header(),
            json={"audition_text": ""},
        )
        assert resp.status_code == 200

        from database import _sync_conn
        conn = _sync_conn()
        try:
            row = conn.execute("SELECT audition_text FROM voices WHERE id = ?", (voice["id"],)).fetchone()
            assert row["audition_text"] == ""
        finally:
            conn.close()

    def test_update_name_and_audition_text_together(self, clean_db):
        voice, _, _ = _get_first_voice_and_tts()
        if not voice:
            pytest.skip("No voices in test db")

        old_name = voice["name"]
        resp = client.patch(
            f"/api/admin/voices/{voice['id']}",
            headers=_admin_header(),
            json={"name": old_name + "-改", "audition_text": "新试听文案"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == old_name + "-改"


class TestVoiceAudition:
    def test_audition_missing_text(self, clean_db):
        voice, tts_id, _ = _get_first_voice_and_tts()
        if not voice or not tts_id:
            pytest.skip("No voice with TTS config in test db")

        resp = client.post(
            f"/api/admin/voices/{voice['id']}/audition",
            headers=_admin_header(),
            json={},
        )
        assert resp.status_code == 422

    def test_audition_voice_not_found(self, clean_db):
        resp = client.post(
            "/api/admin/voices/nonexistent-id/audition",
            headers=_admin_header(),
            json={"text": "你好"},
        )
        assert resp.status_code == 404

    def test_audition_no_tts_config(self, clean_db):
        from database import _sync_conn
        conn = _sync_conn()
        try:
            voice = conn.execute(
                "SELECT v.id FROM voices v LEFT JOIN voice_tts_links vl ON v.id = vl.voice_id WHERE vl.voice_id IS NULL LIMIT 1"
            ).fetchone()
        finally:
            conn.close()

        if not voice:
            pytest.skip("No voice without TTS config")

        resp = client.post(
            f"/api/admin/voices/{voice['id']}/audition",
            headers=_admin_header(),
            json={"text": "你好"},
        )
        assert resp.status_code == 400
        assert "no linked TTS" in resp.json()["detail"].lower()

    def test_audition_requires_admin(self, clean_db):
        voice, tts_id, _ = _get_first_voice_and_tts()
        if not voice or not tts_id:
            pytest.skip("No voice with TTS config in test db")

        resp = client.post(
            f"/api/admin/voices/{voice['id']}/audition",
            headers=_auth_header(),
            json={"text": "你好"},
        )
        assert resp.status_code == 403

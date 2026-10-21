import uuid

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

from tests.test_auth import _admin_header, _auth_header


class TestRealtimeAudition:
    def _binding(self):
        from database import _sync_conn
        voice_id, config_id = str(uuid.uuid4()), str(uuid.uuid4())
        now = "2026-10-21T00:00:00+00:00"
        db = _sync_conn()
        try:
            db.execute("INSERT INTO voices (id,name,voice_id,type,created_at) VALUES (?,?,?,?,?)",
                       (voice_id, "试听音色", "", "cloned", now))
            db.execute("INSERT INTO realtime_configs "
                       "(id,name,provider,model,api_key,endpoint,capabilities_json,created_at) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (config_id, "试听模型", "qwen", "qwen-audio-3.1-realtime-plus",
                        "test-key", "wss://example.test/api-ws/v1/realtime", '{"voice_clone":true}', now))
            db.execute("INSERT INTO voice_runtime_bindings "
                       "(id,voice_pool_id,runtime_kind,runtime_config_id,provider_voice_id,created_at) "
                       "VALUES (?,?,'realtime',?,?,?)",
                       (str(uuid.uuid4()), voice_id, config_id, "provider-preview-voice", now))
            db.commit()
        finally:
            db.close()
        return voice_id, config_id

    def test_exact_binding_and_one_off_text(self, clean_db, monkeypatch):
        import base64
        import voices
        voice_id, config_id = self._binding()
        captured = {}

        async def fake_preview(**kwargs):
            captured.update(kwargs)
            return b"RIFF-preview"

        monkeypatch.setattr(voices, "synthesize_realtime_preview", fake_preview, raising=False)
        response = client.post(
            f"/api/admin/voices/{voice_id}/realtime-bindings/{config_id}/audition",
            headers=_admin_header(), json={"text": " 你好 "},
        )
        assert response.status_code == 200, response.text
        assert base64.b64decode(response.json()["audio_base64"]) == b"RIFF-preview"
        assert response.json()["mime_type"] == "audio/wav"
        assert captured["voice_id"] == "provider-preview-voice"
        assert captured["text"] == "你好"
        assert "provider-preview-voice" not in response.text
        assert "test-key" not in response.text
        from database import _sync_conn
        db = _sync_conn()
        try:
            assert db.execute("SELECT COUNT(*) FROM voice_runtime_bindings WHERE voice_pool_id=?", (voice_id,)).fetchone()[0] == 1
            assert db.execute("SELECT audition_text FROM voices WHERE id=?", (voice_id,)).fetchone()[0] is None
        finally:
            db.close()

    @pytest.mark.parametrize("text", [" ", "a" * 121])
    def test_rejects_invalid_text(self, clean_db, text):
        voice_id, config_id = self._binding()
        response = client.post(
            f"/api/admin/voices/{voice_id}/realtime-bindings/{config_id}/audition",
            headers=_admin_header(), json={"text": text},
        )
        assert response.status_code == 422

    def test_requires_admin_and_exact_binding(self, clean_db):
        voice_id, config_id = self._binding()
        url = f"/api/admin/voices/{voice_id}/realtime-bindings/{config_id}/audition"
        assert client.post(url, json={"text": "你好"}).status_code != 200
        assert client.post(
            f"/api/admin/voices/{voice_id}/realtime-bindings/{uuid.uuid4()}/audition",
            headers=_admin_header(), json={"text": "你好"},
        ).status_code == 404
        from database import _sync_conn
        db = _sync_conn()
        try:
            db.execute("UPDATE voice_runtime_bindings SET runtime_kind='tts' WHERE voice_pool_id=?", (voice_id,))
            db.commit()
        finally:
            db.close()
        assert client.post(url, headers=_admin_header(), json={"text": "你好"}).status_code == 404

    @pytest.mark.parametrize("error_type,status,detail", [
        ("timeout", 504, "超时"), ("too_large", 413, "过长"),
        ("provider", 502, "拒绝"), ("no_audio", 502, "未生成音频"),
    ])
    def test_safe_errors(self, clean_db, monkeypatch, error_type, status, detail):
        import asyncio
        import voices
        from realtime_audition import RealtimeAuditionTooLarge, RealtimeAuditionRejected, RealtimeAuditionNoAudio
        voice_id, config_id = self._binding()
        async def fail(**_):
            if error_type == "timeout":
                raise asyncio.TimeoutError("test-key provider-preview-voice")
            if error_type == "too_large":
                raise RealtimeAuditionTooLarge("test-key provider-preview-voice")
            if error_type == "provider":
                raise RealtimeAuditionRejected("test-key provider-preview-voice")
            if error_type == "no_audio":
                raise RealtimeAuditionNoAudio("test-key provider-preview-voice")
            raise RuntimeError("test-key provider-preview-voice")
        monkeypatch.setattr(voices, "synthesize_realtime_preview", fail)
        response = client.post(
            f"/api/admin/voices/{voice_id}/realtime-bindings/{config_id}/audition",
            headers=_admin_header(), json={"text": "你好"},
        )
        assert response.status_code == status
        assert detail in response.text
        assert "test-key" not in response.text
        assert "provider-preview-voice" not in response.text


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
    def test_voice_list_hides_provider_voice_id(self, clean_db):
        resp = client.get("/api/admin/voices", headers=_admin_header())

        assert resp.status_code == 200
        assert resp.json()
        assert "voice_id" not in resp.json()[0]
        assert resp.json()[0]["has_classic_voice"] is True

    def test_realtime_only_voice_cannot_gain_tts_by_linking_config(self, clean_db):
        from database import _sync_conn

        voice_id = str(uuid.uuid4())
        conn = _sync_conn()
        try:
            conn.execute(
                "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, '', 'cloned', ?)",
                (voice_id, "仅实时音色", "2026-10-21T00:00:00+00:00"),
            )
            tts_id = conn.execute("SELECT id FROM tts_configs LIMIT 1").fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        listed = client.get("/api/admin/voices", headers=_admin_header())
        assert next(item for item in listed.json() if item["id"] == voice_id)["has_classic_voice"] is False
        linked = client.post(
            f"/api/admin/voices/{voice_id}/tts-configs",
            headers=_admin_header(),
            json={"tts_config_id": tts_id},
        )
        assert linked.status_code == 400
        assert "classic" in linked.json()["detail"].lower()

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
        assert resp.json()["audition_text"] == "这是一段试听文本"

        listed = client.get("/api/admin/voices", headers=_admin_header())
        assert listed.status_code == 200
        assert next(item for item in listed.json() if item["id"] == voice["id"])["audition_text"] == "这是一段试听文本"

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


class TestVoiceCreationApiKey:
    def test_create_voice_uses_tts_config_linked_key(self, clean_db, monkeypatch):
        key = client.post(
            "/api/admin/api-keys",
            headers=_admin_header(),
            json={
                "name": "Linked Qwen key",
                "provider": "qwen",
                "api_key": "linked-secret",
            },
        )
        assert key.status_code == 200, key.text

        config = client.post(
            "/api/admin/tts-configs",
            headers=_admin_header(),
            json={
                "name": "Qwen Audio candidate",
                "provider": "qwen",
                "model": "qwen-audio-3.1-tts-flash",
                "api_key_id": key.json()["id"],
                "supports_voice_clone": True,
            },
        )
        assert config.status_code == 200, config.text

        captured = {}

        async def fake_enroll(
            audio_bytes, mime_type, api_key, tts_model=None, voice_name="",
            *, target_model=None, endpoint=None, audio_url=None,
        ):
            captured.update(
                api_key=api_key,
                target_model=target_model,
                endpoint=endpoint,
                voice_name=voice_name,
                audio_url=audio_url,
            )
            return "provider-candidate-voice"

        monkeypatch.setattr("voices.enroll_voice", fake_enroll)
        monkeypatch.setenv("DASHSCOPE_API_KEY", "stale-env-key")
        monkeypatch.setenv("DASHSCOPE_WORKSPACE", "llm-test")
        monkeypatch.delenv("QWEN_VOICE_ENROLLMENT_API_URL", raising=False)

        response = client.post(
            "/api/admin/voices",
            headers=_admin_header(),
            data={"name": "候选测试音色", "tts_config_id": config.json()["id"]},
            files={"audio_file": ("reference.wav", b"audio", "audio/wav")},
        )

        assert response.status_code == 200, response.text
        assert captured["api_key"] == "linked-secret"
        assert captured["target_model"] == "qwen-audio-3.1-tts-flash"
        assert captured["voice_name"] == "候选测试音色"
        assert captured["endpoint"] == (
            "https://llm-test.cn-beijing.maas.aliyuncs.com/"
            "api/v1/services/audio/tts/customization"
        )
        assert captured["audio_url"].startswith("http")


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

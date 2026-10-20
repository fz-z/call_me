import json
import uuid

from fastapi.testclient import TestClient

from main import app
from tests.test_auth import _admin_header


client = TestClient(app)


def _first_voice_id():
    from database import _sync_conn

    db = _sync_conn()
    try:
        return db.execute("SELECT id FROM voices ORDER BY name LIMIT 1").fetchone()["id"]
    finally:
        db.close()


def _create_realtime_config(*, capabilities={"voice_clone": True}):
    key = client.post(
        "/api/admin/api-keys",
        headers=_admin_header(),
        json={"name": f"Realtime key {uuid.uuid4()}", "provider": "qwen", "api_key": "realtime-secret"},
    )
    assert key.status_code == 200, key.text
    config = client.post(
        "/api/admin/realtime-configs",
        headers=_admin_header(),
        json={
            "name": f"Realtime config {uuid.uuid4()}",
            "provider": "qwen",
            "model": "qwen-audio-3.1-realtime-plus",
            "api_key_id": key.json()["id"],
            "endpoint": "https://enrollment.example.test",
            "capabilities_json": json.dumps(capabilities),
        },
    )
    assert config.status_code == 200, config.text
    return config.json()


def test_runtime_binding_list_is_sanitized_and_names_its_configuration(clean_db):
    from database import _sync_conn

    voice_id = _first_voice_id()
    config = _create_realtime_config()
    db = _sync_conn()
    try:
        db.execute(
            "INSERT INTO voice_runtime_bindings "
            "(id, voice_pool_id, runtime_kind, runtime_config_id, provider_voice_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), voice_id, "realtime", config["id"], "private-provider-voice", "2026-10-19T00:00:00+00:00"),
        )
        db.commit()
    finally:
        db.close()

    response = client.get(f"/api/admin/voices/{voice_id}/runtime-bindings", headers=_admin_header())

    assert response.status_code == 200, response.text
    realtime_binding = next(
        binding for binding in response.json()
        if binding["runtime_kind"] == "realtime" and binding["runtime_config_id"] == config["id"]
    )
    assert realtime_binding["voice_pool_id"] == voice_id
    assert realtime_binding["runtime_config_name"] == config["name"]
    assert realtime_binding["runtime_config_model"] == config["model"]
    assert realtime_binding["created_at"] == "2026-10-19T00:00:00+00:00"
    assert "provider_voice_id" not in response.text
    assert "private-provider-voice" not in response.text


def test_creating_realtime_binding_requires_clone_capability(clean_db):
    voice_id = _first_voice_id()
    config = _create_realtime_config(capabilities={"voice_clone": False})

    response = client.post(
        f"/api/admin/voices/{voice_id}/realtime-bindings",
        headers=_admin_header(),
        data={"realtime_config_id": config["id"], "authorization_confirmed": "true"},
        files={"audio_file": ("reference.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 400
    assert "voice_clone" in response.json()["detail"]


def test_creating_realtime_binding_uses_exact_config_and_sanitizes_response(clean_db, monkeypatch):
    voice_id = _first_voice_id()
    config = _create_realtime_config()
    captured = {}

    async def fake_enroll(audio_bytes, mime_type, api_key, tts_model=None, voice_name="", *, target_model=None, endpoint=None, audio_url=None):
        captured.update(
            api_key=api_key,
            target_model=target_model,
            endpoint=endpoint,
            voice_name=voice_name,
        )
        return "private-realtime-provider-voice"

    monkeypatch.setattr("voices.enroll_voice", fake_enroll)
    response = client.post(
        f"/api/admin/voices/{voice_id}/realtime-bindings",
        headers=_admin_header(),
        data={"realtime_config_id": config["id"], "authorization_confirmed": "true"},
        files={"audio_file": ("reference.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["runtime_config_id"] == config["id"]
    assert response.json()["runtime_config_name"] == config["name"]
    assert "provider_voice_id" not in response.json()
    assert "private-realtime-provider-voice" not in response.text
    assert captured["api_key"] == "realtime-secret"
    assert captured["target_model"] == "qwen-audio-3.1-realtime-plus"
    # A realtime configuration stores its WebSocket endpoint. Voice enrollment
    # is an HTTP API in the same Model Studio workspace, never the WebSocket.
    assert captured["endpoint"] == "https://enrollment.example.test"
    assert captured["voice_name"]


def test_creating_realtime_binding_converts_workspace_websocket_to_enrollment_http_url(clean_db, monkeypatch):
    voice_id = _first_voice_id()
    config = _create_realtime_config()
    workspace_ws = "wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
    from database import _sync_conn

    db = _sync_conn()
    try:
        db.execute("UPDATE realtime_configs SET endpoint = ? WHERE id = ?", (workspace_ws, config["id"]))
        db.commit()
    finally:
        db.close()

    captured = {}

    async def fake_enroll(audio_bytes, mime_type, api_key, tts_model=None, voice_name="", *, target_model=None, endpoint=None, audio_url=None):
        captured["endpoint"] = endpoint
        return "private-realtime-provider-voice"

    monkeypatch.setattr("voices.enroll_voice", fake_enroll)
    response = client.post(
        f"/api/admin/voices/{voice_id}/realtime-bindings",
        headers=_admin_header(),
        data={"realtime_config_id": config["id"], "authorization_confirmed": "true"},
        files={"audio_file": ("reference.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert captured["endpoint"] == (
        "https://workspace.cn-beijing.maas.aliyuncs.com/"
        "api/v1/services/audio/tts/customization"
    )


def test_binding_resolver_keeps_legacy_tts_links_and_never_falls_back_to_other_config(clean_db):
    from database import _sync_conn
    from runtime_bindings import resolve_voice_binding

    voice_id = _first_voice_id()
    db = _sync_conn()
    try:
        tts_binding = db.execute(
            "SELECT runtime_config_id, provider_voice_id FROM voice_runtime_bindings "
            "WHERE voice_pool_id = ? AND runtime_kind = 'tts' LIMIT 1",
            (voice_id,),
        ).fetchone()
        assert tts_binding is not None

        resolved = resolve_voice_binding(db, voice_id, "tts", tts_binding["runtime_config_id"])
        missing = resolve_voice_binding(db, voice_id, "realtime", "different-realtime-config")
    finally:
        db.close()

    assert resolved["provider_voice_id"] == tts_binding["provider_voice_id"]
    assert missing is None

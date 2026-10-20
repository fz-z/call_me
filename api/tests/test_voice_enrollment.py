import asyncio

import pytest

from voice_enrollment import enroll_voice


@pytest.mark.parametrize(
    ("model", "expected_model", "expected_action"),
    [
        ("qwen3-tts-vc-realtime-2026-01-15", "qwen-voice-enrollment", "create"),
        ("qwen-audio-3.1-realtime-plus", "voice-enrollment", "create_voice"),
    ],
)
def test_enrollment_uses_the_protocol_for_its_target_model(
    monkeypatch, model, expected_model, expected_action
):
    captured = {}

    async def capture(_api_key, payload, *, endpoint=None):
        captured["payload"] = payload
        return "provider-voice-id"

    monkeypatch.setattr("voice_enrollment._call_dashscope_enrollment", capture)

    voice_id = asyncio.run(
        enroll_voice(
            b"audio",
            "audio/wav",
            "secret",
            target_model=model,
            voice_name="测试 Voice 01",
            audio_url="https://audio.example/voice.wav",
        )
    )

    assert voice_id == "provider-voice-id"
    payload = captured["payload"]
    assert payload["model"] == expected_model
    assert payload["input"]["action"] == expected_action
    assert payload["input"]["target_model"] == model
    if expected_action == "create":
        assert payload["input"]["audio"]["data"] == "https://audio.example/voice.wav"
        assert payload["input"]["preferred_name"] == "Voice01"
        assert "prefix" not in payload["input"]
    else:
        assert payload["input"]["url"] == "https://audio.example/voice.wav"

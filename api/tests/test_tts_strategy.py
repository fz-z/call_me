import asyncio
import base64
import json
import sys
import types

import pytest

from tts_strategy import QwenRealtimeStrategy, get_tts_strategy


class FakeResponse:
    def __init__(self, body, content_type, status=200, content_length=None):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.content_length = (
            len(body) if content_length is None else content_length
        )

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def install_fake_session(
    monkeypatch,
    *,
    post_payload,
    post_status=200,
    download_body=b"",
    download_type="audio/wav",
    download_status=200,
    download_length=None,
):
    seen = {}

    class FakeSession:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            seen["url"] = url
            seen["authorization"] = kwargs["headers"]["Authorization"]
            seen["body"] = kwargs["json"]
            return FakeResponse(
                json.dumps(post_payload).encode("utf-8"),
                "application/json",
                post_status,
            )

        def get(self, url):
            seen["audio_url"] = url
            return FakeResponse(
                download_body,
                download_type,
                download_status,
                download_length,
            )

    monkeypatch.setattr("tts_strategy.aiohttp.ClientSession", FakeSession)
    return seen


@pytest.mark.parametrize(
    "model",
    ["qwen-audio-3.0-tts-flash", "qwen-audio-3.1-tts-flash"],
)
def test_qwen_audio_model_selects_dedicated_http_strategy(model):
    assert type(get_tts_strategy(model)).__name__ == "QwenAudioHttpStrategy"


def test_qwen_audio_endpoint_requires_workspace(monkeypatch):
    monkeypatch.delenv("QWEN_AUDIO_TTS_API_URL", raising=False)
    monkeypatch.delenv("DASHSCOPE_WORKSPACE", raising=False)
    strategy = get_tts_strategy("qwen-audio-3.1-tts-flash")

    with pytest.raises(RuntimeError, match="DASHSCOPE_WORKSPACE"):
        strategy._api_url()


def test_qwen_audio_endpoint_uses_workspace(monkeypatch):
    monkeypatch.delenv("QWEN_AUDIO_TTS_API_URL", raising=False)
    monkeypatch.setenv("DASHSCOPE_WORKSPACE", "llm-example")
    strategy = get_tts_strategy("qwen-audio-3.1-tts-flash")

    assert strategy._api_url() == (
        "https://llm-example.cn-beijing.maas.aliyuncs.com/"
        "api/v1/services/audio/tts/SpeechSynthesizer"
    )


def test_qwen_audio_endpoint_prefers_explicit_override(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_WORKSPACE", "llm-example")
    monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", "https://override.test/synthesize/")
    strategy = get_tts_strategy("qwen-audio-3.1-tts-flash")

    assert strategy._api_url() == "https://override.test/synthesize"


@pytest.mark.asyncio
async def test_qwen_audio_synthesizes_from_provider_audio_url(monkeypatch):
    seen = install_fake_session(
        monkeypatch,
        post_payload={
            "request_id": "req-1",
            "output": {"audio": {"url": "https://audio.test/file.wav"}},
        },
        download_body=b"RIFFtest",
    )
    monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", "https://workspace.test/synthesize")
    strategy = get_tts_strategy("qwen-audio-3.1-tts-flash")
    encoded, mime = await strategy.synthesize(
        {
            "model": "qwen-audio-3.1-tts-flash",
            "resolved_key": "secret",
            "api_key": "",
        },
        "qwen-audio-3.1-tts-flash-ls-1234",
        "你好",
    )

    assert base64.b64decode(encoded) == b"RIFFtest"
    assert mime == "audio/wav"
    assert seen["authorization"] == "Bearer secret"
    assert seen["url"] == "https://workspace.test/synthesize"
    assert seen["audio_url"] == "https://audio.test/file.wav"
    assert seen["body"] == {
        "model": "qwen-audio-3.1-tts-flash",
        "input": {
            "text": "你好",
            "voice": "qwen-audio-3.1-tts-flash-ls-1234",
            "format": "wav",
            "sample_rate": 24000,
        },
    }


@pytest.mark.asyncio
async def test_qwen_audio_accepts_inline_audio_data(monkeypatch):
    install_fake_session(
        monkeypatch,
        post_payload={
            "request_id": "req-inline",
            "output": {"audio": {"data": "UklGRmlubGluZQ=="}},
        },
    )
    monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", "https://workspace.test/synthesize")

    encoded, mime = await get_tts_strategy("qwen-audio-3.1-tts-flash").synthesize(
        {"model": "qwen-audio-3.1-tts-flash", "resolved_key": "secret", "api_key": ""},
        "voice",
        "你好",
    )

    assert encoded == "UklGRmlubGluZQ=="
    assert mime == "audio/wav"


@pytest.mark.asyncio
async def test_qwen_audio_surfaces_provider_error_without_secret(monkeypatch):
    install_fake_session(
        monkeypatch,
        post_status=400,
        post_payload={
            "request_id": "req-bad",
            "code": "InvalidParameter",
            "message": "bad voice for secret-key",
        },
    )
    monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", "https://workspace.test/synthesize")

    with pytest.raises(RuntimeError) as raised:
        await get_tts_strategy("qwen-audio-3.1-tts-flash").synthesize(
            {
                "model": "qwen-audio-3.1-tts-flash",
                "resolved_key": "secret-key",
                "api_key": "",
            },
            "voice",
            "你好",
        )

    message = str(raised.value)
    assert "InvalidParameter" in message
    assert "bad voice" in message
    assert "req-bad" in message
    assert "secret-key" not in message


@pytest.mark.asyncio
async def test_qwen_audio_rejects_missing_audio_url(monkeypatch):
    install_fake_session(
        monkeypatch,
        post_payload={"request_id": "req-empty", "output": {"audio": {}}},
    )
    monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", "https://workspace.test/synthesize")

    with pytest.raises(RuntimeError, match="missing audio URL.*req-empty"):
        await get_tts_strategy("qwen-audio-3.1-tts-flash").synthesize(
            {"model": "qwen-audio-3.1-tts-flash", "resolved_key": "secret", "api_key": ""},
            "voice",
            "你好",
        )


@pytest.mark.asyncio
async def test_qwen_audio_rejects_non_audio_download(monkeypatch):
    install_fake_session(
        monkeypatch,
        post_payload={"output": {"audio": {"url": "https://audio.test/file"}}},
        download_body=b"provider error",
        download_type="text/plain",
    )
    monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", "https://workspace.test/synthesize")

    with pytest.raises(RuntimeError, match="non-audio"):
        await get_tts_strategy("qwen-audio-3.1-tts-flash").synthesize(
            {"model": "qwen-audio-3.1-tts-flash", "resolved_key": "secret", "api_key": ""},
            "voice",
            "你好",
        )


@pytest.mark.asyncio
async def test_qwen_audio_rejects_oversized_download(monkeypatch):
    install_fake_session(
        monkeypatch,
        post_payload={"output": {"audio": {"url": "https://audio.test/file"}}},
        download_body=b"RIFF",
        download_length=20 * 1024 * 1024 + 1,
    )
    monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", "https://workspace.test/synthesize")

    with pytest.raises(RuntimeError, match="too large"):
        await get_tts_strategy("qwen-audio-3.1-tts-flash").synthesize(
            {"model": "qwen-audio-3.1-tts-flash", "resolved_key": "secret", "api_key": ""},
            "voice",
            "你好",
        )


def test_qwen_realtime_audition_surfaces_provider_error(monkeypatch):
    class FakeCallback:
        pass

    class FakeAudioFormat:
        PCM_24000HZ_MONO_16BIT = "pcm"

    class FakeClient:
        def __init__(self, *, callback, **_kwargs):
            self.callback = callback

        def connect(self):
            pass

        def update_session(self, **_kwargs):
            pass

        def append_text(self, _text):
            pass

        def finish(self):
            self.callback.on_event(
                {
                    "type": "error",
                    "error": {"code": "InvalidVoice", "message": "voice is not valid for this model"},
                }
            )

        def close(self):
            pass

    dashscope = types.ModuleType("dashscope")
    realtime = types.ModuleType("dashscope.audio.qwen_tts_realtime")
    realtime.QwenTtsRealtime = FakeClient
    realtime.QwenTtsRealtimeCallback = FakeCallback
    realtime.AudioFormat = FakeAudioFormat
    audio = types.ModuleType("dashscope.audio")
    audio.__path__ = []
    dashscope.audio = audio
    audio.qwen_tts_realtime = realtime
    monkeypatch.setitem(sys.modules, "dashscope", dashscope)
    monkeypatch.setitem(sys.modules, "dashscope.audio", audio)
    monkeypatch.setitem(sys.modules, "dashscope.audio.qwen_tts_realtime", realtime)

    with pytest.raises(RuntimeError, match="InvalidVoice.*voice is not valid for this model"):
        asyncio.run(
            QwenRealtimeStrategy().synthesize(
                {"model": "qwen3-tts-vc-realtime-2026-01-15", "resolved_key": "key", "api_key": ""},
                "invalid-voice-id",
                "你好",
            )
        )


def test_qwen_realtime_audition_surfaces_websocket_close_reason(monkeypatch):
    class FakeCallback:
        pass

    class FakeAudioFormat:
        PCM_24000HZ_MONO_16BIT = "pcm"

    class FakeClient:
        def __init__(self, *, callback, **_kwargs):
            self.callback = callback

        def connect(self):
            pass

        def update_session(self, **_kwargs):
            pass

        def append_text(self, _text):
            pass

        def finish(self):
            self.callback.on_close(1007, "Model not exist.")

        def close(self):
            pass

    dashscope = types.ModuleType("dashscope")
    realtime = types.ModuleType("dashscope.audio.qwen_tts_realtime")
    realtime.QwenTtsRealtime = FakeClient
    realtime.QwenTtsRealtimeCallback = FakeCallback
    realtime.AudioFormat = FakeAudioFormat
    audio = types.ModuleType("dashscope.audio")
    audio.__path__ = []
    dashscope.audio = audio
    audio.qwen_tts_realtime = realtime
    monkeypatch.setitem(sys.modules, "dashscope", dashscope)
    monkeypatch.setitem(sys.modules, "dashscope.audio", audio)
    monkeypatch.setitem(sys.modules, "dashscope.audio.qwen_tts_realtime", realtime)

    with pytest.raises(RuntimeError, match=r"WebSocket closed \(code=1007\): Model not exist\."):
        asyncio.run(
            QwenRealtimeStrategy().synthesize(
                {"model": "qwen3-tts-vc-realtime-2026-01-15", "resolved_key": "key", "api_key": ""},
                "voice-id",
                "你好",
            )
        )

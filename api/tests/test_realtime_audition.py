import base64
import asyncio
import io
import json
import wave
from types import SimpleNamespace

import aiohttp
import pytest

from realtime_audition import (
    MAX_PCM_BYTES, RealtimeAuditionError, RealtimeAuditionTooLarge,
    synthesize_realtime_preview,
)


class FakeSocket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send_json(self, event):
        self.sent.append(event)

    async def receive(self):
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(next(self.events)))


class FakeSession:
    def __init__(self, socket):
        self.socket = socket
        self.closed = False
        self.url = None
        self.headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    def ws_connect(self, url, *, headers, max_msg_size=None):
        self.url, self.headers = url, headers
        self.max_msg_size = max_msg_size
        return self.socket


@pytest.mark.asyncio
async def test_preview_uses_bound_voice_and_returns_wav():
    pcm = b"\x01\x00\x02\x00"
    socket = FakeSocket([
        {"type": "response.audio.delta", "delta": base64.b64encode(pcm).decode()},
        {"type": "response.done", "response": {"status": "completed"}},
    ])
    session = FakeSession(socket)
    result = await synthesize_realtime_preview(
        api_key="test-key", endpoint="wss://example.test/api-ws/v1/realtime?model=old",
        model="qwen-audio-3.1-realtime-plus", voice_id="cloned-voice", text="你好",
        session_factory=lambda: session,
    )
    assert session.url.count("model=") == 1
    assert "model=qwen-audio-3.1-realtime-plus" in session.url
    assert session.headers == {"Authorization": "Bearer test-key"}
    assert session.max_msg_size is not None and session.max_msg_size <= 3 * 1024 * 1024
    assert socket.sent[0]["session"]["voice"] == "cloned-voice"
    assert socket.sent[1]["item"]["content"][0]["type"] == "input_text"
    assert "你好" in socket.sent[1]["item"]["content"][0]["text"]
    assert socket.sent[2]["type"] == "response.create"
    with wave.open(io.BytesIO(result), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert wav.readframes(2) == pcm
    assert socket.closed and session.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("events,error_type", [
    ([{"type": "response.done", "response": {"status": "failed"}}], RealtimeAuditionError),
    ([{"type": "response.done", "response": None}], RealtimeAuditionError),
    ([{"type": "response.done", "response": {"status": "completed"}}], RealtimeAuditionError),
    ([{"type": "error", "message": "secret provider detail"}], RealtimeAuditionError),
    ([{"type": "response.audio.delta", "delta": "!"}], RealtimeAuditionError),
    ([{"type": "response.audio.delta", "delta": "AQ=="}], RealtimeAuditionError),
    ([{"type": "response.audio.delta", "delta": base64.b64encode(b"\x00" * (MAX_PCM_BYTES + 2)).decode()}], RealtimeAuditionTooLarge),
])
async def test_preview_rejects_bad_responses_and_closes(events, error_type):
    socket = FakeSocket(events)
    session = FakeSession(socket)
    with pytest.raises(error_type) as caught:
        await synthesize_realtime_preview(
            api_key="test-key", endpoint="wss://example.test/realtime", model="model",
            voice_id="secret-voice", text="test", session_factory=lambda: session,
        )
    assert "secret" not in str(caught.value)
    assert socket.closed and session.closed


@pytest.mark.asyncio
async def test_timeout_closes_resources(monkeypatch):
    import realtime_audition
    monkeypatch.setattr(realtime_audition, "TOTAL_TIMEOUT_SECONDS", 0.01)
    socket = FakeSocket([])
    async def wait_forever():
        await asyncio.Event().wait()
    socket.receive = wait_forever
    session = FakeSession(socket)
    with pytest.raises(asyncio.TimeoutError):
        await synthesize_realtime_preview(
            api_key="test-key", endpoint="wss://example.test/realtime", model="model",
            voice_id="voice", text="test", session_factory=lambda: session,
        )
    assert socket.closed and session.closed


@pytest.mark.asyncio
async def test_plaintext_endpoint_is_rejected_before_connecting():
    socket = FakeSocket([])
    session = FakeSession(socket)
    with pytest.raises(RealtimeAuditionError):
        await synthesize_realtime_preview(
            api_key="secret-key", endpoint="ws://example.test/realtime", model="model",
            voice_id="voice", text="test", session_factory=lambda: session,
        )
    assert session.url is None
    assert session.headers is None


@pytest.mark.asyncio
async def test_oversized_encoded_delta_is_rejected_before_decode(monkeypatch):
    import realtime_audition
    called = False
    def decode(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not decode oversized delta")
    monkeypatch.setattr(realtime_audition.base64, "b64decode", decode)
    socket = FakeSocket([{"type": "response.audio.delta", "delta": "A" * (3 * 1024 * 1024)}])
    session = FakeSession(socket)
    with pytest.raises(RealtimeAuditionTooLarge):
        await synthesize_realtime_preview(
            api_key="test-key", endpoint="wss://example.test/realtime", model="model",
            voice_id="voice", text="test", session_factory=lambda: session,
        )
    assert not called
    assert socket.closed and session.closed

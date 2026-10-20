import asyncio
import sys
import types

import pytest

from tts_strategy import QwenRealtimeStrategy


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

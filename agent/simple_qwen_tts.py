from __future__ import annotations

import base64
import json
import os

import aiohttp
from livekit import rtc
from livekit.agents.tts import (
    TTS,
    ChunkedStream,
    SynthesizeStream,
    TTSCapabilities,
)
from livekit.agents.types import APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.utils import shortuuid


class SimpleQwenTTS(TTS):
    """Minimal Qwen TTS adapter: one HTTP request per text, returns full audio."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen-tts",
        voice: str = "Cherry",
        sample_rate: int = 24000,
        num_channels: int = 1,
    ) -> None:
        super().__init__(
            capabilities=TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=num_channels,
        )
        self._api_key = api_key
        self._model = model
        self._voice = voice

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "qwen-tts-simple"

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> ChunkedStream:
        return self._synthesize_with_stream(text=text, conn_options=conn_options)

    def stream(self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> SynthesizeStream:
        return _SimpleQwenSynthesizeStream(tts=self, conn_options=conn_options)


class _SimpleQwenSynthesizeStream(SynthesizeStream):
    async def _run(self, emitter) -> None:
        tts = self._tts
        request_id = shortuuid()

        buf = ""
        async for item in self._input_ch:
            if isinstance(item, self._FlushSentinel):
                continue
            if item:
                self._mark_started()
                buf += item

        text = buf.strip()
        if not text:
            return

        audio = await _call_qwen_tts_http(tts=tts, text=text)
        if not audio:
            return

        # Push as one segment with frame size chunks
        emitter.initialize(
            request_id=request_id,
            sample_rate=tts.sample_rate,
            num_channels=tts.num_channels,
            mime_type="audio/wav",
            stream=False,
        )
        emitter.start_segment(segment_id=shortuuid())

        chunk_size = 16 * 1024
        for i in range(0, len(audio), chunk_size):
            chunk = audio[i : i + chunk_size]
            emitter.push(chunk)

        emitter.flush()


async def _call_qwen_tts_http(*, tts: SimpleQwenTTS, text: str) -> bytes:
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    body = {
        "model": tts._model,
        "input": {"text": text, "voice": tts._voice},
        "parameters": {
            "response_format": {"type": "audio", "format": "wav"},
        },
    }
    headers = {
        "Authorization": f"Bearer {tts._api_key}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=body) as resp:
            raw = await resp.read()
            if resp.status >= 400:
                raise RuntimeError(f"Qwen TTS HTTP {resp.status}: {raw[:500].decode('utf-8', errors='replace')}")

            ctype = resp.headers.get("Content-Type", "").lower()
            if ctype.startswith("audio/"):
                return raw

            obj = json.loads(raw.decode("utf-8"))
            audio_url = _extract_audio_url(obj)
            if audio_url:
                async with session.get(audio_url) as audio_resp:
                    return await audio_resp.read()

            raise RuntimeError(f"Could not extract audio from response: {json.dumps(obj)[:500]}")


def _extract_audio_url(obj) -> str | None:
    if isinstance(obj, dict):
        for k in ("url", "audio_url", "audioUrl"):
            v = obj.get(k)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                return v
        for k in ("output", "audio"):
            if k in obj:
                found = _extract_audio_url(obj[k])
                if found:
                    return found
    return None

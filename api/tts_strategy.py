"""TTS synthesis strategies for different model families.

Each strategy knows how to call its model's API for audition/synthesis.
Selected by model name prefix.
"""
import base64
import json
import os
import aiohttp


class TtsStrategy:
    """Base strategy. Subclasses override synthesize()."""

    async def synthesize(self, tts_row, voice_id: str, text: str) -> tuple[str, str]:
        """Return (audio_base64, mime_type)."""
        raise NotImplementedError


class QwenHttpStrategy(TtsStrategy):
    """qwen TTS models without realtime (HTTP REST API)."""

    async def synthesize(self, tts_row, voice_id: str, text: str) -> tuple[str, str]:
        model = tts_row["model"]
        api_key = tts_row["resolved_key"] or tts_row["api_key"]
        api_url = os.environ.get(
            "QWEN_TTS_API_URL",
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        )
        req_body = {
            "model": model,
            "input": {"text": text, "voice": voice_id},
            "parameters": {"response_format": {"type": "audio", "format": "wav"}},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(api_url, json=req_body, headers=headers) as r:
                raw = await r.read()
                if r.status >= 400:
                    snippet = raw[:500].decode("utf-8", errors="replace")
                    raise RuntimeError(f"TTS synthesis failed: {snippet}")
                ctype = (r.headers.get("Content-Type") or "").lower()
                if ctype.startswith("audio/"):
                    return base64.b64encode(raw).decode("utf-8"), ctype
                obj = json.loads(raw.decode("utf-8"))
                audio_b64 = _extract_audio_b64(obj)
                if audio_b64:
                    return audio_b64, "audio/wav"
                raise RuntimeError("No audio data in TTS response")


class QwenAudioHttpStrategy(TtsStrategy):
    """Qwen Audio TTS via the workspace-scoped SpeechSynthesizer API."""

    MAX_AUDIO_BYTES = 20 * 1024 * 1024

    def _api_url(self) -> str:
        override = os.environ.get("QWEN_AUDIO_TTS_API_URL", "").strip()
        if override:
            return override.rstrip("/")
        workspace = os.environ.get("DASHSCOPE_WORKSPACE", "").strip()
        if not workspace:
            raise RuntimeError(
                "DASHSCOPE_WORKSPACE is required for Qwen Audio TTS"
            )
        return (
            f"https://{workspace}.cn-beijing.maas.aliyuncs.com/"
            "api/v1/services/audio/tts/SpeechSynthesizer"
        )

    async def synthesize(self, tts_row, voice_id: str, text: str) -> tuple[str, str]:
        api_key = tts_row["resolved_key"] or tts_row["api_key"]
        try:
            return await self._synthesize(tts_row, voice_id, text, api_key)
        except RuntimeError as error:
            raise RuntimeError(_redact_secret(str(error), api_key)) from error

    async def _synthesize(
        self, tts_row, voice_id: str, text: str, api_key: str
    ) -> tuple[str, str]:
        body = {
            "model": tts_row["model"],
            "input": {
                "text": text,
                "voice": voice_id,
                "format": "wav",
                "sample_rate": 24000,
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._api_url(), json=body, headers=headers) as response:
                payload = await _read_qwen_json(response)

            output = payload.get("output") if isinstance(payload, dict) else None
            audio = output.get("audio") if isinstance(output, dict) else None
            if not isinstance(audio, dict):
                raise RuntimeError(_qwen_error_detail(payload, "missing audio response"))

            inline_data = audio.get("data")
            if isinstance(inline_data, str) and inline_data:
                return inline_data, "audio/wav"

            audio_url = audio.get("url")
            if not isinstance(audio_url, str) or not audio_url.startswith(("http://", "https://")):
                raise RuntimeError(_qwen_error_detail(payload, "missing audio URL"))

            async with session.get(audio_url) as download:
                raw, mime_type = await _read_bounded_audio(
                    download, self.MAX_AUDIO_BYTES
                )

        return base64.b64encode(raw).decode("utf-8"), mime_type


class QwenRealtimeStrategy(TtsStrategy):
    """qwen TTS models with realtime (WebSocket via dashscope SDK)."""

    async def synthesize(self, tts_row, voice_id: str, text: str) -> tuple[str, str]:
        import asyncio
        from dashscope.audio.qwen_tts_realtime import (
            QwenTtsRealtime,
            QwenTtsRealtimeCallback,
        )

        model = tts_row["model"]
        api_key = tts_row["resolved_key"] or tts_row["api_key"]

        ws_url = os.environ.get("QWEN_TTS_REALTIME_WS_URL", "").strip() or (
            "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
        )
        ws_url = ws_url.split("?", 1)[0]
        workspace_id = os.environ.get("DASHSCOPE_WORKSPACE", "").strip() or None
        import dashscope
        dashscope.api_key = api_key

        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        audio_chunks: list[bytes] = []
        provider_errors: list[str] = []

        class _CB(QwenTtsRealtimeCallback):
            def on_event(self, message):
                if isinstance(message, dict):
                    response = message
                elif isinstance(message, str):
                    try:
                        response = json.loads(message)
                    except Exception:
                        return
                else:
                    return

                ev_type = response.get("type", "")
                if ev_type == "response.audio.delta":
                    delta = response.get("delta")
                    if isinstance(delta, str) and delta:
                        try:
                            audio_chunks.append(base64.b64decode(delta))
                        except Exception:
                            return
                elif ev_type in ("response.audio.done", "response.done", "session.finished"):
                    loop.call_soon_threadsafe(q.put_nowait, None)
                elif ev_type in ("error", "session.error", "response.error"):
                    error = response.get("error") or response
                    if isinstance(error, dict):
                        code = error.get("code") or error.get("type")
                        message = error.get("message") or error.get("msg")
                        detail = ": ".join(str(part) for part in (code, message) if part)
                    else:
                        detail = str(error)
                    provider_errors.append(detail or f"provider event {ev_type}")
                    loop.call_soon_threadsafe(q.put_nowait, None)

            def on_close(self, close_status_code, close_msg):
                if (close_status_code not in (None, 1000) or close_msg) and not provider_errors:
                    detail = "WebSocket closed"
                    if close_status_code is not None:
                        detail += f" (code={close_status_code})"
                    if close_msg:
                        detail += f": {close_msg}"
                    provider_errors.append(detail)
                loop.call_soon_threadsafe(q.put_nowait, None)

        cb = _CB()
        client = QwenTtsRealtime(model=model, callback=cb, url=ws_url, workspace=workspace_id)

        from dashscope.audio.qwen_tts_realtime import AudioFormat

        await asyncio.to_thread(client.connect)
        await asyncio.to_thread(
            client.update_session,
            voice=voice_id,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="server_commit",
        )
        await asyncio.to_thread(client.append_text, text)
        await asyncio.to_thread(client.finish)

        while True:
            item = await q.get()
            if item is None:
                break

        try:
            await asyncio.to_thread(client.close)
        except Exception:
            pass

        if provider_errors:
            raise RuntimeError(f"DashScope realtime error: {provider_errors[0]}")
        if not audio_chunks:
            raise RuntimeError(
                "No audio generated by TTS realtime (provider closed the session without audio)"
            )

        pcm_data = b"".join(audio_chunks)
        wav_data = _pcm_to_wav(pcm_data, sample_rate=24000)
        return base64.b64encode(wav_data).decode("utf-8"), "audio/wav"


class VolcengineTtsStrategy(TtsStrategy):
    """Volcengine TTS synthesis via HTTP SSE unidirectional endpoint."""

    TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"

    async def synthesize(self, tts_row, voice_id: str, text: str) -> tuple[str, str]:
        import uuid as _uuid

        api_key = tts_row["resolved_key"] or tts_row["api_key"]
        resource_id = os.environ.get("VOLCENGINE_RESOURCE_ID", "seed-icl-2.0")

        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "X-Api-Request-Id": str(_uuid.uuid4()),
            "X-Api-Resource-Id": resource_id,
        }

        body = {
            "speaker_id": voice_id,
            "text": text,
        }

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.TTS_URL, json=body, headers=headers) as resp:
                raw = await resp.read()
                if resp.status != 200:
                    snippet = raw[:500].decode("utf-8", errors="replace")
                    raise RuntimeError(f"Volcengine TTS failed HTTP {resp.status}: {snippet}")

                # SSE response: extract audio data from event stream
                # The response is text/event-stream with base64 audio chunks
                audio_b64 = _parse_volcengine_sse(raw.decode("utf-8", errors="replace"))
                if not audio_b64:
                    raise RuntimeError("No audio data in Volcengine TTS response")

                return audio_b64, _detect_volc_audio_mime(audio_b64)


class CosyVoiceStrategy(TtsStrategy):
    """cosyvoice models (WebSocket via dashscope tts_v2 SDK)."""

    async def synthesize(self, tts_row, voice_id: str, text: str) -> tuple[str, str]:
        import asyncio
        import dashscope
        from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

        model = tts_row["model"]
        api_key = tts_row["resolved_key"] or tts_row["api_key"]
        dashscope.api_key = api_key
        dashscope.base_websocket_api_url = os.environ.get(
            "COSYVOICE_WS_URL",
            "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
        )

        synthesizer = SpeechSynthesizer(
            model=model,
            voice=voice_id,
            format=AudioFormat.PCM_24000HZ_MONO_16BIT,
        )

        audio = await asyncio.to_thread(synthesizer.call, text)
        if not audio:
            raise RuntimeError("No audio generated by CosyVoice TTS")

        wav_data = _pcm_to_wav(_fade_in(audio, sample_rate=24000, duration_ms=10), 24000)
        return base64.b64encode(wav_data).decode("utf-8"), "audio/wav"


def get_tts_strategy(model: str) -> TtsStrategy:
    """Select strategy by model name."""
    m = (model or "").lower()
    if m.startswith("qwen-audio-") and "-tts-" in m:
        return QwenAudioHttpStrategy()
    if m.startswith("cosyvoice"):
        return CosyVoiceStrategy()
    if m.startswith("volcengine") or m.startswith("seed-icl") or m.startswith("bytedance"):
        return VolcengineTtsStrategy()
    if "realtime" in m:
        return QwenRealtimeStrategy()
    return QwenHttpStrategy()


def _redact_secret(text: str, secret: str) -> str:
    if secret and text:
        return text.replace(secret, "[redacted]")
    return text


def _looks_like_audio(raw: bytes) -> bool:
    if raw.startswith((b"RIFF", b"ID3", b"OggS", b"fLaC")):
        return True
    # MPEG audio frame sync (MP3/AAC ADTS share the 0xFFE mask family).
    return len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0


def _qwen_error_detail(payload: object, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    code = payload.get("code")
    message = payload.get("message")
    request_id = payload.get("request_id")
    parts = [str(part) for part in (code, message) if part]
    detail = ": ".join(parts) or fallback
    if request_id:
        detail += f" (request_id={request_id})"
    return detail


async def _read_qwen_json(response) -> dict:
    raw = await response.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Qwen Audio TTS returned invalid JSON (HTTP {response.status})"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("Qwen Audio TTS returned an invalid response object")
    if response.status >= 400 or payload.get("code"):
        raise RuntimeError(
            _qwen_error_detail(payload, f"Qwen Audio TTS HTTP {response.status}")
        )
    return payload


async def _read_bounded_audio(response, max_bytes: int) -> tuple[bytes, str]:
    if response.status >= 400:
        raw = await response.read()
        snippet = raw[:500].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Qwen Audio TTS audio download failed HTTP {response.status}: {snippet}"
        )

    content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
    is_audio_type = content_type.startswith("audio/")
    is_generic_type = content_type in ("", "application/octet-stream")
    if not (is_audio_type or is_generic_type):
        raise RuntimeError(
            f"Qwen Audio TTS audio download returned non-audio content: {content_type or 'unknown'}"
        )

    content_length = getattr(response, "content_length", None)
    if content_length is not None and content_length > max_bytes:
        raise RuntimeError("Qwen Audio TTS audio download is too large")

    content = getattr(response, "content", None)
    if content is not None:
        raw = await content.read(max_bytes + 1)
    else:
        raw = await response.read()
    if len(raw) > max_bytes:
        raise RuntimeError("Qwen Audio TTS audio download is too large")
    if not raw:
        raise RuntimeError("Qwen Audio TTS audio download is empty")
    if not is_audio_type and not _looks_like_audio(raw):
        raise RuntimeError(
            f"Qwen Audio TTS audio download returned non-audio content: {content_type or 'unknown'}"
        )
    return raw, content_type if is_audio_type else "audio/wav"


def _parse_volcengine_sse(text: str) -> str | None:
    """Parse Volcengine SSE response to extract base64 audio data."""
    audio_parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    obj = json.loads(data)
                    audio_chunk = obj.get("audio") or obj.get("data") or ""
                    if audio_chunk:
                        audio_parts.append(audio_chunk)
                except json.JSONDecodeError:
                    pass
    return "".join(audio_parts) if audio_parts else None


def _detect_volc_audio_mime(audio_b64: str) -> str:
    """Detect audio format from base64 header bytes."""
    try:
        header = base64.b64decode(audio_b64[:20])
        if header[:4] == b"RIFF":
            return "audio/wav"
        if header[:3] == b"ID3" or header[:2] == b"\xff\xfb":
            return "audio/mpeg"
        if header[:4] == b"OggS":
            return "audio/ogg"
    except Exception:
        pass
    return "audio/wav"


def _extract_audio_b64(obj: dict) -> str | None:
    output = obj.get("output")
    if isinstance(output, dict):
        audio = output.get("audio")
        if isinstance(audio, dict):
            for k in ("data", "audio", "audio_base64"):
                v = audio.get(k)
                if isinstance(v, str) and v:
                    return v
        if isinstance(audio, str) and audio:
            return audio
    return None


def _fade_in(pcm_data: bytes, sample_rate: int, duration_ms: int = 10) -> bytes:
    """Apply a short fade-in to eliminate pops/clicks at the start."""
    import struct
    num_samples = int(sample_rate * duration_ms / 1000)
    if num_samples <= 0 or len(pcm_data) < num_samples * 2:
        return pcm_data

    result = bytearray(pcm_data)
    for i in range(num_samples):
        offset = i * 2
        sample = struct.unpack_from("<h", result, offset)[0]
        factor = i / num_samples  # linear ramp from 0 to 1
        sample = int(sample * factor)
        struct.pack_into("<h", result, offset, max(-32768, min(32767, sample)))
    return bytes(result)


def _pcm_to_wav(pcm_data: bytes, sample_rate: int, num_channels: int = 1, bits_per_sample: int = 16) -> bytes:
    import struct
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE", b"fmt ", 16, 1,
        num_channels, sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )
    return header + pcm_data

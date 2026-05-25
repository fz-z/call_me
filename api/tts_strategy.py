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
                    loop.call_soon_threadsafe(q.put_nowait, None)

            def on_close(self, close_status_code, close_msg):
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

        if not audio_chunks:
            raise RuntimeError("No audio generated by TTS realtime")

        pcm_data = b"".join(audio_chunks)
        wav_data = _pcm_to_wav(pcm_data, sample_rate=24000)
        return base64.b64encode(wav_data).decode("utf-8"), "audio/wav"


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
    if m.startswith("cosyvoice"):
        return CosyVoiceStrategy()
    if "realtime" in m:
        return QwenRealtimeStrategy()
    return QwenHttpStrategy()


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

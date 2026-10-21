"""Bounded, short-lived audio preview for an existing realtime voice."""

import asyncio
import base64
import io
import json
import wave
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp

MAX_PCM_BYTES = 2 * 1024 * 1024
TOTAL_TIMEOUT_SECONDS = 35


class RealtimeAuditionError(Exception):
    pass


class RealtimeAuditionTooLarge(RealtimeAuditionError):
    pass


class RealtimeAuditionNoAudio(RealtimeAuditionError):
    pass


class RealtimeAuditionRejected(RealtimeAuditionError):
    pass


def _model_endpoint(endpoint: str, model: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "wss" or not parsed.netloc:
        raise RealtimeAuditionError("Invalid realtime endpoint")
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "model"]
    query.append(("model", model))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _wav(pcm: bytes) -> bytes:
    result = io.BytesIO()
    with wave.open(result, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(pcm)
    return result.getvalue()


async def synthesize_realtime_preview(
    *, api_key: str, endpoint: str, model: str, voice_id: str, text: str,
    session_factory=None,
) -> bytes:
    async def generate():
        pcm = bytearray()
        async with (session_factory or aiohttp.ClientSession)() as session:
            async with session.ws_connect(
                _model_endpoint(endpoint, model),
                headers={"Authorization": f"Bearer {api_key}"},
                max_msg_size=3 * 1024 * 1024,
            ) as socket:
                await socket.send_json({"type": "session.update", "session": {
                    "voice": voice_id, "modalities": ["audio", "text"],
                    "input_audio_format": "pcm", "output_audio_format": "pcm",
                }})
                await socket.send_json({"type": "conversation.item.create", "item": {
                    "type": "message", "role": "user", "content": [{"type": "input_text",
                        "text": f"请只逐字朗读以下文案，不要回答或添加内容：{text}"}],
                }})
                await socket.send_json({"type": "response.create"})
                while True:
                    message = await socket.receive()
                    if message.type != aiohttp.WSMsgType.TEXT:
                        raise RealtimeAuditionError("Realtime connection closed before completion")
                    try:
                        event = json.loads(message.data)
                    except (TypeError, json.JSONDecodeError) as error:
                        raise RealtimeAuditionError("Invalid realtime response") from error
                    if not isinstance(event, dict):
                        raise RealtimeAuditionError("Invalid realtime response")
                    if event.get("type") == "response.audio.delta":
                        encoded = event.get("delta")
                        if not isinstance(encoded, str):
                            raise RealtimeAuditionError("Invalid realtime audio")
                        if len(encoded) > 4 * ((MAX_PCM_BYTES - len(pcm) + 2) // 3):
                            raise RealtimeAuditionTooLarge("Realtime preview exceeds audio limit")
                        try:
                            chunk = base64.b64decode(encoded, validate=True)
                        except (KeyError, ValueError, TypeError) as error:
                            raise RealtimeAuditionError("Invalid realtime audio") from error
                        if len(chunk) % 2:
                            raise RealtimeAuditionError("Invalid realtime audio")
                        if len(pcm) + len(chunk) > MAX_PCM_BYTES:
                            raise RealtimeAuditionTooLarge("Realtime preview exceeds audio limit")
                        pcm.extend(chunk)
                    elif event.get("type") == "response.done":
                        response = event.get("response")
                        if not isinstance(response, dict) or response.get("status") != "completed":
                            raise RealtimeAuditionError("Realtime preview did not complete")
                        if not pcm:
                            raise RealtimeAuditionNoAudio("Realtime preview returned no audio")
                        return _wav(bytes(pcm))
                    elif event.get("type") == "error":
                        raise RealtimeAuditionRejected("Realtime provider rejected preview")

    return await asyncio.wait_for(generate(), TOTAL_TIMEOUT_SECONDS)

"""Voice enrollment strategies for different TTS model families.

Each strategy knows how to enroll a voice (upload audio → get voice_id)
for its specific TTS model family.
"""
import base64
import json
import os
import aiohttp


class EnrollmentStrategy:
    """Base strategy for voice enrollment."""

    async def enroll(self, audio_bytes: bytes, mime_type: str, api_key: str, tts_model: str) -> str:
        raise NotImplementedError


class QwenEnrollmentStrategy(EnrollmentStrategy):
    """Qwen-TTS voice enrollment: base64 data URI, action=create."""

    async def enroll(self, audio_bytes: bytes, mime_type: str, api_key: str, tts_model: str) -> str:
        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64}"

        payload = {
            "model": "qwen-voice-enrollment",
            "input": {
                "action": "create",
                "target_model": tts_model,
                "preferred_name": "voice",
                "audio": {"data": data_uri},
            },
        }
        return await _call_enrollment_api(api_key, payload)


class CosyVoiceEnrollmentStrategy(EnrollmentStrategy):
    """CosyVoice voice enrollment: audio URL, action=create_voice."""

    async def enroll(self, audio_bytes: bytes, mime_type: str, api_key: str, tts_model: str) -> str:
        # CosyVoice enrollment requires audio as a URL.
        # Try data URI first — if the API doesn't support it, the caller
        # will need to provide a publicly accessible URL.
        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64}"

        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": tts_model,
                "prefix": "voice",
                "url": data_uri,
            },
        }
        return await _call_enrollment_api(api_key, payload)


def _get_enrollment_strategy(tts_model: str | None) -> EnrollmentStrategy:
    if tts_model and tts_model.lower().startswith("cosyvoice"):
        return CosyVoiceEnrollmentStrategy()
    return QwenEnrollmentStrategy()


async def enroll_voice(
    audio_bytes: bytes,
    mime_type: str,
    api_key: str,
    tts_model: str | None = None,
) -> str:
    """Upload audio to DashScope voice enrollment, return voice_id."""
    tts_model = tts_model or os.environ.get("SEED_TTS_VC_MODEL", "qwen3-tts-vc-realtime-2026-01-15")
    strategy = _get_enrollment_strategy(tts_model)
    return await strategy.enroll(audio_bytes, mime_type, api_key, tts_model)


async def _call_enrollment_api(api_key: str, payload: dict) -> str:
    api_url = os.environ.get(
        "QWEN_VOICE_ENROLLMENT_API_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization",
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(api_url, headers=headers, json=payload) as resp:
            raw = await resp.read()
            if resp.status >= 400:
                snippet = raw[:2000].decode("utf-8", errors="replace")
                raise RuntimeError(f"Voice enrollment failed HTTP {resp.status}: {snippet}")
            obj = json.loads(raw.decode("utf-8"))
            output = obj["output"]
            # CosyVoice returns "voice_id", Qwen-TTS returns "voice"
            return output.get("voice_id") or output["voice"]

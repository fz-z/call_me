"""Voice enrollment strategies for different TTS model families.

Each strategy knows how to enroll a voice (upload audio → get voice_id)
for its specific TTS model family.
"""
import asyncio
import base64
import json
import os
import re
import time
import uuid
import aiohttp


class EnrollmentStrategy:
    """Base strategy for voice enrollment."""

    async def enroll(
        self, audio_bytes: bytes, mime_type: str, api_key: str, tts_model: str,
        voice_name: str = "", endpoint: str | None = None, audio_url: str | None = None,
    ) -> str:
        raise NotImplementedError


class QwenEnrollmentStrategy(EnrollmentStrategy):
    """Qwen-Audio voice enrollment from a temporary, publicly reachable URL."""

    async def enroll(
        self, audio_bytes: bytes, mime_type: str, api_key: str, target_model: str,
        voice_name: str = "", endpoint: str | None = None, audio_url: str | None = None,
    ) -> str:
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": target_model,
                "prefix": "voice",
                "url": audio_url,
            },
        }
        if not audio_url:
            raise ValueError("Qwen voice enrollment requires a publicly reachable audio URL")
        # The enrollment API requires a publicly reachable URL; it does not
        # accept a data URI for this operation.
        return await _call_dashscope_enrollment(api_key, payload, endpoint=endpoint)


class QwenTtsEnrollmentStrategy(EnrollmentStrategy):
    """Qwen3-TTS voice enrollment (different API from Qwen-Audio)."""

    async def enroll(
        self, audio_bytes: bytes, mime_type: str, api_key: str, target_model: str,
        voice_name: str = "", endpoint: str | None = None, audio_url: str | None = None,
    ) -> str:
        if not audio_url:
            raise ValueError("Qwen3-TTS voice enrollment requires a publicly reachable audio URL")
        preferred_name = re.sub(r"[^a-zA-Z0-9_]", "", voice_name)[:16] or "voice"
        payload = {
            "model": "qwen-voice-enrollment",
            "input": {
                "action": "create",
                "target_model": target_model,
                "preferred_name": preferred_name,
                "audio": {"data": audio_url},
            },
        }
        return await _call_dashscope_enrollment(api_key, payload, endpoint=endpoint)


class CosyVoiceEnrollmentStrategy(EnrollmentStrategy):
    """CosyVoice voice enrollment: audio URL, action=create_voice."""

    async def enroll(self, audio_bytes: bytes, mime_type: str, api_key: str, tts_model: str, voice_name: str = "", endpoint: str | None = None, audio_url: str | None = None) -> str:
        if not audio_url:
            raise ValueError("CosyVoice enrollment requires a publicly reachable audio URL")
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": tts_model,
                "prefix": "voice",
                "url": audio_url,
            },
        }
        return await _call_dashscope_enrollment(api_key, payload, endpoint=endpoint)


class VolcengineEnrollmentStrategy(EnrollmentStrategy):
    """Volcengine (ByteDance) voice clone — async training with polling."""

    VOICE_CLONE_URL = "https://openspeech.bytedance.com/api/v3/tts/voice_clone"
    GET_VOICE_URL = "https://openspeech.bytedance.com/api/v3/tts/get_voice"
    POLL_INTERVAL = 3  # seconds
    MAX_POLL_SECONDS = 120

    async def enroll(self, audio_bytes: bytes, mime_type: str, api_key: str, tts_model: str, voice_name: str = "", endpoint: str | None = None, audio_url: str | None = None) -> str:
        return await self._voice_clone(audio_bytes, mime_type, api_key, voice_name)

    async def _voice_clone(self, audio_bytes: bytes, mime_type: str, api_key: str, voice_name: str) -> str:
        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        audio_format = self._map_mime(mime_type)

        preset_speaker = os.environ.get("VOLCENGINE_SPEAKER_ID", "").strip()

        body = {
            "audio": {"data": b64, "format": audio_format},
            "language": 0,
        }

        if preset_speaker and preset_speaker != "custom_speaker_id":
            body["speaker_id"] = preset_speaker
        else:
            body["speaker_id"] = "custom_speaker_id"
            body["custom_speaker_id"] = _sanitize_volc_speaker_name(voice_name)

        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.VOICE_CLONE_URL, json=body, headers=headers) as resp:
                raw = await resp.read()
                if resp.status != 200:
                    snippet = raw[:2000].decode("utf-8", errors="replace")
                    raise RuntimeError(f"Voice clone failed HTTP {resp.status}: {snippet}")
                result = json.loads(raw.decode("utf-8"))
                speaker_id = result.get("speaker_id", "")
                if not speaker_id:
                    raise RuntimeError(f"Voice clone returned no speaker_id: {raw[:500].decode('utf-8', errors='replace')}")

        # Poll until training completes
        return await self._poll_until_ready(api_key, speaker_id)

    async def _poll_until_ready(self, api_key: str, speaker_id: str) -> str:
        deadline = time.time() + self.MAX_POLL_SECONDS
        while time.time() < deadline:
            await asyncio.sleep(self.POLL_INTERVAL)
            status = await self._get_voice_status(api_key, speaker_id)
            if status in (2, 4):  # Success or Active
                return speaker_id
            if status == 3:  # Failed
                raise RuntimeError(f"Voice clone training failed for speaker_id={speaker_id}")
            # status 0=NotFound, 1=Training — keep polling

        raise RuntimeError(f"Voice clone training timed out after {self.MAX_POLL_SECONDS}s for speaker_id={speaker_id}")

    async def _get_voice_status(self, api_key: str, speaker_id: str) -> int:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }
        body = {"speaker_id": speaker_id}
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.GET_VOICE_URL, json=body, headers=headers) as resp:
                raw = await resp.read()
                if resp.status != 200:
                    snippet = raw[:500].decode("utf-8", errors="replace")
                    raise RuntimeError(f"Get voice status failed HTTP {resp.status}: {snippet}")
                result = json.loads(raw.decode("utf-8"))
                return result.get("status", 0)

    @staticmethod
    def _map_mime(mime_type: str) -> str:
        m = (mime_type or "audio/wav").lower()
        if "wav" in m:
            return "wav"
        if "mp3" in m or "mpeg" in m:
            return "mp3"
        if "m4a" in m:
            return "m4a"
        if "ogg" in m:
            return "ogg"
        if "aac" in m:
            return "aac"
        if "pcm" in m:
            return "pcm"
        return "wav"


def _sanitize_volc_speaker_name(name: str) -> str:
    """Sanitize a voice name to volcengine custom_speaker_id rules:
    8-256 chars, starts with letter, alphanumeric + - _ only.
    """
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", name)
    if not safe or not safe[0].isalpha():
        safe = "custom_" + (safe or "voice")
    if len(safe) < 8:
        safe = safe + "_" + uuid.uuid4().hex[:7]
    if len(safe) > 256:
        safe = safe[:256]
    return safe.rstrip("-_")


def _get_enrollment_strategy(tts_model: str | None) -> EnrollmentStrategy:
    if not tts_model:
        return QwenEnrollmentStrategy()
    m = tts_model.lower()
    if m.startswith("cosyvoice"):
        return CosyVoiceEnrollmentStrategy()
    if m.startswith("volcengine") or m.startswith("seed-icl") or m.startswith("bytedance"):
        return VolcengineEnrollmentStrategy()
    if m.startswith("qwen3-tts"):
        return QwenTtsEnrollmentStrategy()
    return QwenEnrollmentStrategy()


async def enroll_voice(
    audio_bytes: bytes,
    mime_type: str,
    api_key: str,
    tts_model: str | None = None,
    voice_name: str = "",
    *,
    target_model: str | None = None,
    endpoint: str | None = None,
    audio_url: str | None = None,
) -> str:
    """Upload audio to voice enrollment service, return voice_id."""
    selected_model = target_model or tts_model or os.environ.get(
        "SEED_TTS_VC_MODEL", "qwen3-tts-vc-realtime-2026-01-15"
    )
    strategy = _get_enrollment_strategy(selected_model)
    return await strategy.enroll(
        audio_bytes, mime_type, api_key, selected_model, voice_name, endpoint,
        audio_url=audio_url,
    )


async def _call_dashscope_enrollment(api_key: str, payload: dict, *, endpoint: str | None = None) -> str:
    api_url = endpoint or os.environ.get(
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
            return output.get("voice_id") or output["voice"]

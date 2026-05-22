import base64
import json
import os
import aiohttp


async def enroll_voice(audio_bytes: bytes, mime_type: str, api_key: str) -> str:
    """Upload audio to DashScope qwen-voice-enrollment, return voice_id."""
    b64 = base64.b64encode(audio_bytes).decode("utf-8")
    data_uri = f"data:{mime_type};base64,{b64}"

    payload = {
        "model": "qwen-voice-enrollment",
        "input": {
            "action": "create",
            "target_model": os.environ.get("QWEN_TTS_MODEL", "qwen3-tts-vc-realtime-2026-01-15"),
            "preferred_name": "voice",
            "audio": {"data": data_uri},
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    api_url = os.environ.get(
        "QWEN_VOICE_ENROLLMENT_API_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization",
    )

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(api_url, headers=headers, json=payload) as resp:
            raw = await resp.read()
            if resp.status >= 400:
                snippet = raw[:2000].decode("utf-8", errors="replace")
                raise RuntimeError(f"Voice enrollment failed HTTP {resp.status}: {snippet}")
            obj = json.loads(raw.decode("utf-8"))
            return obj["output"]["voice"]

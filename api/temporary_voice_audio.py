"""Short-lived public URLs required by the Qwen voice enrollment API."""

import os
import secrets
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response


router = APIRouter(prefix="/api/public/voice-audio", tags=["voice-audio"])
_AUDIO_DIR = Path(tempfile.gettempdir()) / "call-me-voice-audio"
_AUDIO_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
_AUDIO_TTL_SECONDS = 600
_published: dict[str, tuple[Path, str, float]] = {}


def publish_voice_audio(audio_bytes: bytes, mime_type: str) -> tuple[str, str]:
    """Write audio to a random, temporary capability URL for the provider."""
    now = time.monotonic()
    for token, (path, _, expires_at) in list(_published.items()):
        if expires_at <= now:
            path.unlink(missing_ok=True)
            _published.pop(token, None)

    token = secrets.token_urlsafe(32)
    path = _AUDIO_DIR / token
    with path.open("xb") as audio_file:
        audio_file.write(audio_bytes)

    content_type = mime_type if mime_type.startswith("audio/") else "application/octet-stream"
    _published[token] = (path, content_type, now + _AUDIO_TTL_SECONDS)
    public_base = os.environ.get(
        "VOICE_AUDIO_PUBLIC_BASE_URL", "http://47.116.9.70:8000"
    ).rstrip("/")
    return token, f"{public_base}/api/public/voice-audio/{token}"


def remove_published_voice_audio(token: str) -> None:
    item = _published.pop(token, None)
    if item:
        item[0].unlink(missing_ok=True)


@router.get("/{token}")
def get_temporary_voice_audio(token: str):
    item = _published.get(token)
    if not item:
        raise HTTPException(status_code=404, detail="Audio URL not found or expired")

    path, content_type, expires_at = item
    if expires_at <= time.monotonic() or not path.is_file():
        remove_published_voice_audio(token)
        raise HTTPException(status_code=404, detail="Audio URL not found or expired")

    return Response(
        content=path.read_bytes(),
        media_type=content_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )

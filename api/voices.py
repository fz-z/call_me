import asyncio
import base64
import json
import uuid
import os
from datetime import datetime, timezone

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database import _sync_conn
from models import VoiceOut, VoiceCreate, VoiceManualCreate, VoiceUpdate, TtsConfigOut, VoiceTtsLinkRequest, AuditionRequest, AuditionResponse
from auth import require_admin
from voice_enrollment import enroll_voice

router = APIRouter(prefix="/api/admin/voices", tags=["voices"])


@router.get("", response_model=list[VoiceOut])
def list_voices(
    tts_config_id: str | None = None,
    admin: dict = Depends(require_admin),
):
    db = _sync_conn()
    try:
        if tts_config_id:
            rows = db.execute(
                "SELECT v.* FROM voices v JOIN voice_tts_links vl ON v.id = vl.voice_id WHERE vl.tts_config_id = ? ORDER BY v.type, v.name",
                (tts_config_id,),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM voices ORDER BY type, name").fetchall()
        return [VoiceOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.post("", response_model=VoiceOut)
async def create_voice(
    name: str = Form(...),
    audio_file: UploadFile = File(...),
    tts_config_id: str | None = Form(None),
    admin: dict = Depends(require_admin),
):
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="DASHSCOPE_API_KEY not configured")

    audio_bytes = await audio_file.read()
    content_type = audio_file.content_type or "audio/wav"

    try:
        dashscope_voice_id = await enroll_voice(audio_bytes, content_type, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice enrollment failed: {e}")

    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM voices WHERE name = ?", (name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Voice name already exists")

        voice_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
            (voice_id, name, dashscope_voice_id, "cloned", now),
        )
        if tts_config_id:
            tts_exists = db.execute("SELECT id FROM tts_configs WHERE id = ?", (tts_config_id,)).fetchone()
            if tts_exists:
                db.execute(
                    "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
                    (voice_id, tts_config_id),
                )
        db.commit()
        return VoiceOut(id=voice_id, name=name, voice_id=dashscope_voice_id, type="cloned", created_at=now)
    finally:
        db.close()


@router.post("/manual", response_model=VoiceOut)
def create_voice_manual(body: VoiceManualCreate, admin: dict = Depends(require_admin)):
    if body.type not in ("builtin", "cloned"):
        raise HTTPException(status_code=400, detail="type must be 'builtin' or 'cloned'")

    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM voices WHERE name = ?", (body.name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Voice name already exists")

        voice_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
            (voice_id, body.name, body.voice_id, body.type, now),
        )
        if body.tts_config_id:
            tts_exists = db.execute("SELECT id FROM tts_configs WHERE id = ?", (body.tts_config_id,)).fetchone()
            if tts_exists:
                db.execute(
                    "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
                    (voice_id, body.tts_config_id),
                )
        db.commit()
        return VoiceOut(id=voice_id, name=body.name, voice_id=body.voice_id, type=body.type, created_at=now)
    finally:
        db.close()


@router.patch("/{voice_id}", response_model=VoiceOut)
def update_voice(voice_id: str, body: VoiceUpdate, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")

        if body.name is not None:
            existing = db.execute("SELECT id FROM voices WHERE name = ? AND id != ?", (body.name, voice_id)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Voice name already exists")
            db.execute("UPDATE voices SET name = ? WHERE id = ?", (body.name, voice_id))

        if body.audition_text is not None:
            db.execute("UPDATE voices SET audition_text = ? WHERE id = ?", (body.audition_text, voice_id))

        db.commit()
        updated = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        return VoiceOut(**dict(updated))
    finally:
        db.close()


@router.delete("/{voice_id}", status_code=204)
def delete_voice(voice_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        refs = db.execute(
            "SELECT COUNT(*) as c FROM agents WHERE voice_pool_id = ?", (voice_id,)
        ).fetchone()["c"]
        if refs > 0:
            raise HTTPException(status_code=400, detail=f"Voice is used by {refs} agent(s)")

        db.execute("DELETE FROM voices WHERE id = ?", (voice_id,))
        db.commit()
    finally:
        db.close()
    return None


@router.get("/{voice_id}/tts-configs", response_model=list[TtsConfigOut])
def get_voice_tts_configs(voice_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute(
            "SELECT tc.* FROM tts_configs tc JOIN voice_tts_links vl ON tc.id = vl.tts_config_id WHERE vl.voice_id = ?",
            (voice_id,),
        ).fetchall()
        return [TtsConfigOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.post("/{voice_id}/tts-configs", status_code=204)
def link_voice_tts(voice_id: str, body: VoiceTtsLinkRequest, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT id FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        tts = db.execute("SELECT id FROM tts_configs WHERE id = ?", (body.tts_config_id,)).fetchone()
        if not tts:
            raise HTTPException(status_code=404, detail="TTS config not found")

        db.execute(
            "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
            (voice_id, body.tts_config_id),
        )
        db.commit()
    finally:
        db.close()
    return None


@router.delete("/{voice_id}/tts-configs/{tts_id}", status_code=204)
def unlink_voice_tts(voice_id: str, tts_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        db.execute(
            "DELETE FROM voice_tts_links WHERE voice_id = ? AND tts_config_id = ?",
            (voice_id, tts_id),
        )
        db.commit()
    finally:
        db.close()
    return None


@router.post("/{voice_id}/audition", response_model=AuditionResponse)
async def audition_voice(voice_id: str, body: AuditionRequest, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")

        tts_row = db.execute(
            "SELECT tc.*, ak.api_key as resolved_key FROM tts_configs tc "
            "JOIN voice_tts_links vl ON tc.id = vl.tts_config_id "
            "LEFT JOIN api_keys ak ON tc.api_key_id = ak.id "
            "WHERE vl.voice_id = ? "
            "ORDER BY tc.created_at ASC LIMIT 1",
            (voice_id,),
        ).fetchone()
        if not tts_row:
            raise HTTPException(status_code=400, detail="Voice has no linked TTS config")
    finally:
        db.close()

    provider = (tts_row["provider"] or "").lower()
    if provider == "qwen":
        model = tts_row["model"] or ""
        if "realtime" in model.lower():
            audio_base64, mime_type = await _qwen_audition_realtime(tts_row, voice["voice_id"], body.text)
        else:
            audio_base64, mime_type = await _qwen_audition(tts_row, voice["voice_id"], body.text)
    else:
        raise HTTPException(status_code=400, detail=f"Audition not supported for provider: {provider}")

    return {"audio_base64": audio_base64, "mime_type": mime_type}


async def _qwen_audition(tts_row, voice_id: str, text: str) -> tuple[str, str]:
    model = tts_row["model"]
    api_key = tts_row["resolved_key"] or tts_row["api_key"]
    api_url = os.environ.get(
        "QWEN_TTS_API_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    )

    req_body = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice_id,
        },
        "parameters": {
            "response_format": {
                "type": "audio",
                "format": "wav",
            },
        },
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
                raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {snippet}")

            ctype = (r.headers.get("Content-Type") or "").lower()
            if ctype.startswith("audio/"):
                return base64.b64encode(raw).decode("utf-8"), ctype

            obj = json.loads(raw.decode("utf-8"))
            audio_b64 = _extract_audio_b64_from_output(obj)
            if audio_b64:
                return audio_b64, "audio/wav"

            raise HTTPException(status_code=502, detail="No audio data in TTS response")


async def _qwen_audition_realtime(tts_row, voice_id: str, text: str) -> tuple[str, str]:
    model = tts_row["model"]
    api_key = tts_row["resolved_key"] or tts_row["api_key"]

    try:
        import dashscope
        from dashscope.audio.qwen_tts_realtime import (
            AudioFormat,
            QwenTtsRealtime,
            QwenTtsRealtimeCallback,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="dashscope SDK not installed")

    ws_url = os.environ.get("QWEN_TTS_REALTIME_WS_URL", "").strip() or (
        "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    )
    ws_url = ws_url.split("?", 1)[0]
    workspace_id = os.environ.get("DASHSCOPE_WORKSPACE", "").strip() or None
    dashscope.api_key = api_key

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[bytes | None] = asyncio.Queue()
    audio_chunks: list[bytes] = []

    class _CB(QwenTtsRealtimeCallback):
        def on_event(self, message):
            nonlocal audio_chunks
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
                        audio = base64.b64decode(delta)
                    except Exception:
                        return
                    audio_chunks.append(audio)
            elif ev_type in ("response.audio.done", "response.done", "session.finished"):
                loop.call_soon_threadsafe(q.put_nowait, None)
            elif ev_type in ("error", "session.error", "response.error"):
                loop.call_soon_threadsafe(q.put_nowait, None)

        def on_close(self, close_status_code, close_msg):
            loop.call_soon_threadsafe(q.put_nowait, None)

    cb = _CB()
    client = QwenTtsRealtime(
        model=model,
        callback=cb,
        url=ws_url,
        workspace=workspace_id,
    )

    voice = voice_id
    try:
        await asyncio.to_thread(client.connect)
        await asyncio.to_thread(
            client.update_session,
            voice=voice,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="server_commit",
        )
        await asyncio.to_thread(client.append_text, text)
        await asyncio.to_thread(client.finish)
    except Exception as e:
        loop.call_soon_threadsafe(q.put_nowait, None)
        raise HTTPException(status_code=502, detail=f"TTS realtime call failed: {e}")

    while True:
        item = await q.get()
        if item is None:
            break

    try:
        await asyncio.to_thread(client.close)
    except Exception:
        pass

    if not audio_chunks:
        raise HTTPException(status_code=502, detail="No audio generated by TTS realtime")

    pcm_data = b"".join(audio_chunks)
    wav_data = _pcm_to_wav(pcm_data, sample_rate=24000, num_channels=1, bits_per_sample=16)
    return base64.b64encode(wav_data).decode("utf-8"), "audio/wav"


def _pcm_to_wav(pcm_data: bytes, sample_rate: int, num_channels: int, bits_per_sample: int) -> bytes:
    import struct
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_data


def _extract_audio_b64_from_output(obj: dict) -> str | None:
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

import uuid
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database import _sync_conn
from models import VoiceOut, VoiceCreate, TtsConfigOut, VoiceTtsLinkRequest
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


@router.delete("/{voice_id}", status_code=204)
def delete_voice(voice_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        if voice["type"] == "builtin":
            raise HTTPException(status_code=400, detail="Cannot delete built-in voice")

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

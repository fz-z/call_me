import uuid
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database import _sync_conn
from models import VoiceOut, VoiceCreate
from auth import require_admin
from voice_enrollment import enroll_voice

router = APIRouter(prefix="/api/admin/voices", tags=["voices"])


@router.get("", response_model=list[VoiceOut])
def list_voices(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT * FROM voices ORDER BY type, name").fetchall()
        return [VoiceOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.post("", response_model=VoiceOut)
async def create_voice(
    name: str = Form(...),
    audio_file: UploadFile = File(...),
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

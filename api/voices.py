import uuid
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database import _sync_conn
from models import VoiceOut, VoiceCreate, VoiceManualCreate, VoiceUpdate, TtsConfigOut, VoiceTtsLinkRequest, AuditionRequest, AuditionResponse
from auth import require_admin
from voice_enrollment import enroll_voice
from tts_strategy import get_tts_strategy

router = APIRouter(prefix="/api/admin/voices", tags=["voices"])


def _normalize_provider(provider: str) -> str:
    """Normalize provider names to canonical form (qwen / deepseek / etc)."""
    p = (provider or "").lower()
    if any(kw in p for kw in ("qwen", "dashscope", "百炼", "bailian", "阿里", "alibaba")):
        return "qwen"
    if "deepseek" in p:
        return "deepseek"
    return p


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

    # Look up TTS model for enrollment parameters
    tts_model = None
    if tts_config_id:
        db = _sync_conn()
        try:
            tc = db.execute("SELECT model FROM tts_configs WHERE id = ?", (tts_config_id,)).fetchone()
            if tc:
                tts_model = tc["model"]
        finally:
            db.close()

    try:
        dashscope_voice_id = await enroll_voice(audio_bytes, content_type, api_key, tts_model)
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

    provider = _normalize_provider(tts_row["provider"] or "")
    if provider != "qwen":
        raise HTTPException(status_code=400, detail=f"Audition not supported for provider: {tts_row['provider']}")

    model = tts_row["model"] or ""
    try:
        strategy = get_tts_strategy(model)
        audio_base64, mime_type = await strategy.synthesize(tts_row, voice["voice_id"], body.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {e}")

    return {"audio_base64": audio_base64, "mime_type": mime_type}

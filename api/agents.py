import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import AgentOut, AgentCreate, AgentUpdate
from auth import get_current_user
from config_utils import validate_agent_runtime_selection

router = APIRouter(prefix="/api/agents", tags=["agents"])

MIN_SPEECH_RATE = 0.5
MAX_SPEECH_RATE = 2.0


def _validate_speech_rate(value: float | None) -> float:
    rate = 1.0 if value is None else float(value)
    if not MIN_SPEECH_RATE <= rate <= MAX_SPEECH_RATE:
        raise HTTPException(
            status_code=400,
            detail=f"speech_rate must be between {MIN_SPEECH_RATE} and {MAX_SPEECH_RATE}",
        )
    return rate


def _user_can_access(db, agent_id: str, user_id: str, role: str) -> bool:
    if role == "admin":
        return True
    row = db.execute("SELECT owner_id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    return row is not None and row["owner_id"] == user_id


@router.post("", response_model=AgentOut)
def create_agent(
    body: AgentCreate,
    user: dict = Depends(get_current_user),
):
    """Create an agent by selecting a voice from the pool. No audio upload."""
    db = _sync_conn()
    try:
        selection = validate_agent_runtime_selection(
            db,
            runtime_mode=body.runtime_mode,
            voice_pool_id=body.voice_pool_id,
            model_config_id=body.model_config_id,
            tts_config_id=body.tts_config_id,
            realtime_config_id=body.realtime_config_id,
        )

        speech_rate = _validate_speech_rate(body.speech_rate)
        allow_interruptions = 1 if body.allow_interruptions else 0
        agent_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        try:
            db.execute(
                "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, voice_pool_id, source_agent_id, model_config_id, tts_config_id, runtime_mode, realtime_config_id, photo_url, speech_rate, allow_interruptions, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    agent_id, body.alias, selection["voice_id"], body.system_prompt,
                    user["id"], selection["voice_pool_id"], None,
                    selection["model_config_id"], selection["tts_config_id"],
                    selection["runtime_mode"], selection["realtime_config_id"], body.photo_url,
                    speech_rate, allow_interruptions, now,
                ),
            )
        except Exception:
            import logging
            logging.getLogger("api").error(
                "FK constraint failed — voice_pool_id=%s tts_config_id=%s model_config_id=%s owner_id=%s",
                selection["voice_pool_id"], selection["tts_config_id"], selection["model_config_id"], user["id"],
            )
            raise
        db.commit()
        row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return AgentOut(**dict(row))
    finally:
        db.close()


@router.get("", response_model=list[AgentOut])
def list_agents(user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        if user["role"] == "admin":
            rows = db.execute(
                "SELECT * FROM agents WHERE source_agent_id IS NULL ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM agents WHERE owner_id = ? ORDER BY created_at DESC",
                (user["id"],),
            ).fetchall()
        return [AgentOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        if not _user_can_access(db, agent_id, user["id"], user["role"]):
            raise HTTPException(status_code=404, detail="Agent not found")
        row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
        return AgentOut(**dict(row))
    finally:
        db.close()


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: str, body: AgentUpdate, user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
        if row["owner_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only owner or admin can update")

        new_alias = body.alias if body.alias is not None else row["alias"]
        new_prompt = body.system_prompt if body.system_prompt is not None else row["system_prompt"]
        new_model_config_id = row["model_config_id"] if body.model_config_id is None else body.model_config_id
        new_tts_config_id = row["tts_config_id"] if body.tts_config_id is None else body.tts_config_id
        new_realtime_config_id = row["realtime_config_id"] if body.realtime_config_id is None else body.realtime_config_id
        new_runtime_mode = row["runtime_mode"] if body.runtime_mode is None else body.runtime_mode
        new_voice_pool_id = row["voice_pool_id"]
        new_photo_url = row["photo_url"] if "photo_url" in row.keys() else None
        if body.photo_url is not None:
            new_photo_url = body.photo_url if body.photo_url.strip() else None
        new_speech_rate = (
            row["speech_rate"] if body.speech_rate is None
            else _validate_speech_rate(body.speech_rate)
        )
        new_allow_interruptions = (
            row["allow_interruptions"] if body.allow_interruptions is None
            else (1 if body.allow_interruptions else 0)
        )

        if body.voice_pool_id is not None:
            new_voice_pool_id = body.voice_pool_id

        selection = validate_agent_runtime_selection(
            db,
            runtime_mode=new_runtime_mode,
            voice_pool_id=new_voice_pool_id,
            model_config_id=new_model_config_id,
            tts_config_id=new_tts_config_id,
            realtime_config_id=new_realtime_config_id,
        )

        db.execute(
            "UPDATE agents SET alias=?, system_prompt=?, model_config_id=?, voice_pool_id=?, voice_id=?, tts_config_id=?, runtime_mode=?, realtime_config_id=?, photo_url=?, speech_rate=?, allow_interruptions=? WHERE id=?",
            (
                new_alias, new_prompt, selection["model_config_id"], selection["voice_pool_id"],
                selection["voice_id"], selection["tts_config_id"], selection["runtime_mode"],
                selection["realtime_config_id"], new_photo_url, new_speech_rate,
                new_allow_interruptions, agent_id,
            ),
        )
        db.commit()
        updated = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return AgentOut(**dict(updated))
    finally:
        db.close()


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
        if row["owner_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only owner or admin can delete")

        db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        db.commit()
    finally:
        db.close()
    return None

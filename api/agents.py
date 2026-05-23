import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import AgentOut, AgentCreate, AgentUpdate
from auth import get_current_user

router = APIRouter(prefix="/api/agents", tags=["agents"])


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
        if not body.voice_pool_id or not body.voice_pool_id.strip():
            raise HTTPException(status_code=400, detail="voice_pool_id is required")

        # Lookup voice from pool
        voice = db.execute(
            "SELECT voice_id FROM voices WHERE id = ?", (body.voice_pool_id,)
        ).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found in pool")

        # Validate optional FKs if provided
        if body.tts_config_id:
            tts_exists = db.execute("SELECT id FROM tts_configs WHERE id = ?", (body.tts_config_id,)).fetchone()
            if not tts_exists:
                raise HTTPException(status_code=400, detail="tts_config_id not found")
        if body.model_config_id:
            mc_exists = db.execute("SELECT id FROM model_configs WHERE id = ?", (body.model_config_id,)).fetchone()
            if not mc_exists:
                raise HTTPException(status_code=400, detail="model_config_id not found")

        agent_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, voice_pool_id, source_agent_id, model_config_id, tts_config_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, body.alias, voice["voice_id"], body.system_prompt, user["id"], body.voice_pool_id, None, body.model_config_id, body.tts_config_id, now),
        )
        db.commit()
        return AgentOut(
            id=agent_id, alias=body.alias, voice_id=voice["voice_id"],
            voice_pool_id=body.voice_pool_id,
            system_prompt=body.system_prompt, owner_id=user["id"],
            tts_config_id=getattr(body, 'tts_config_id', None),
            created_at=now,
        )
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
        new_model_config_id = body.model_config_id if body.model_config_id is not None else row["model_config_id"]
        new_tts_config_id = body.tts_config_id if body.tts_config_id is not None else row["tts_config_id"]
        new_voice_pool_id = row["voice_pool_id"] if "voice_pool_id" in row.keys() else None
        new_voice_id = row["voice_id"]

        if body.voice_pool_id is not None:
            voice_row = db.execute(
                "SELECT voice_id FROM voices WHERE id = ?", (body.voice_pool_id,)
            ).fetchone()
            if not voice_row:
                raise HTTPException(status_code=404, detail="Voice not found")
            new_voice_pool_id = body.voice_pool_id
            new_voice_id = voice_row["voice_id"]

        db.execute(
            "UPDATE agents SET alias=?, system_prompt=?, model_config_id=?, voice_pool_id=?, voice_id=?, tts_config_id=? WHERE id=?",
            (new_alias, new_prompt, new_model_config_id, new_voice_pool_id, new_voice_id, new_tts_config_id, agent_id),
        )
        db.commit()
        return AgentOut(
            id=agent_id, alias=new_alias, voice_id=new_voice_id,
            voice_pool_id=new_voice_pool_id,
            system_prompt=new_prompt, owner_id=row["owner_id"],
            source_agent_id=row["source_agent_id"] if "source_agent_id" in row.keys() else None, model_config_id=new_model_config_id,
            tts_config_id=new_tts_config_id,
            created_at=row["created_at"],
        )
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

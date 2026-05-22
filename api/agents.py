import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database import _sync_conn
from models import AgentOut, AgentCreate, AgentUpdate
from auth import get_current_user, require_admin
from voice_enrollment import enroll_voice

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _user_can_access(db, agent_id: str, user_id: str, role: str) -> bool:
    if role == "admin":
        return True
    row = db.execute("SELECT owner_id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not row:
        return False
    if row["owner_id"] == user_id:
        return True
    perm = db.execute(
        "SELECT 1 FROM permissions WHERE agent_id = ? AND user_id = ?", (agent_id, user_id)
    ).fetchone()
    return perm is not None


@router.post("", response_model=AgentOut)
async def create_agent(
    alias: str = Form(...),
    system_prompt: str = Form(""),
    audio_file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="DASHSCOPE_API_KEY not configured")

    audio_bytes = await audio_file.read()
    content_type = audio_file.content_type or "audio/wav"

    try:
        voice_id = await enroll_voice(audio_bytes, content_type, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice enrollment failed: {e}")

    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db = _sync_conn()
    try:
        db.execute(
            "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, alias, voice_id, system_prompt, user["id"], now),
        )
        db.commit()
        return AgentOut(
            id=agent_id, alias=alias, voice_id=voice_id,
            system_prompt=system_prompt, owner_id=user["id"], created_at=now,
        )
    finally:
        db.close()


@router.get("", response_model=list[AgentOut])
def list_agents(user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        rows = db.execute(
            """SELECT DISTINCT a.* FROM agents a
               LEFT JOIN permissions p ON a.id = p.agent_id AND p.user_id = ?
               WHERE a.owner_id = ? OR p.user_id = ?
               ORDER BY a.created_at DESC""",
            (user["id"], user["id"], user["id"]),
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
        if not _user_can_access(db, agent_id, user["id"], user["role"]):
            raise HTTPException(status_code=404, detail="Agent not found")

        row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
        if row["owner_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only owner or admin can update")

        new_alias = body.alias if body.alias is not None else row["alias"]
        new_prompt = body.system_prompt if body.system_prompt is not None else row["system_prompt"]
        db.execute(
            "UPDATE agents SET alias = ?, system_prompt = ? WHERE id = ?",
            (new_alias, new_prompt, agent_id),
        )
        db.commit()
        return AgentOut(
            id=agent_id, alias=new_alias, voice_id=row["voice_id"],
            system_prompt=new_prompt, owner_id=row["owner_id"], created_at=row["created_at"],
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

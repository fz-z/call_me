import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import AgentOut, GrantRequest
from auth import get_current_user, require_admin

router = APIRouter(prefix="/api/agents", tags=["permissions"])


@router.post("/{agent_id}/grant", response_model=AgentOut)
def grant_permission(agent_id: str, body: GrantRequest, admin: dict = Depends(require_admin)):
    """Grant access by creating an independent copy of the agent for the target user.
    The copy has the same voice_id but can be edited independently by the new owner."""
    db = _sync_conn()
    try:
        user_row = db.execute("SELECT id, username FROM users WHERE username = ?", (body.username,)).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        agent_row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not agent_row:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Check if user already has a copy (same source voice_id + same original alias)
        existing = db.execute(
            "SELECT id FROM agents WHERE voice_id = ? AND owner_id = ? AND alias = ?",
            (agent_row["voice_id"], user_row["id"], agent_row["alias"]),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="User already has a copy of this agent")

        # Create independent copy for the target user
        copy_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, source_agent_id, voice_pool_id, model_config_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (copy_id, agent_row["alias"], agent_row["voice_id"], agent_row["system_prompt"], user_row["id"], agent_id, agent_row["voice_pool_id"], agent_row["model_config_id"], now),
        )
        db.commit()
        return AgentOut(
            id=copy_id, alias=agent_row["alias"], voice_id=agent_row["voice_id"],
            voice_pool_id=agent_row["voice_pool_id"],
            system_prompt=agent_row["system_prompt"], owner_id=user_row["id"],
            source_agent_id=agent_id, model_config_id=agent_row["model_config_id"],
            created_at=now,
        )
    finally:
        db.close()


@router.delete("/{agent_id}/grant/{username}", status_code=204)
def revoke_permission(agent_id: str, username: str, admin: dict = Depends(require_admin)):
    """Revoke by deleting the user's copy of the agent."""
    db = _sync_conn()
    try:
        user_row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        agent_row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not agent_row:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Delete the user's copy by source_agent_id
        result = db.execute(
            "DELETE FROM agents WHERE source_agent_id = ? AND owner_id = ?",
            (agent_id, user_row["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="No user copy found for this agent")
        db.commit()
    finally:
        db.close()
    return None

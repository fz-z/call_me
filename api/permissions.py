import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import PermissionOut, GrantRequest
from auth import get_current_user, require_admin

router = APIRouter(prefix="/api/agents", tags=["permissions"])


@router.post("/{agent_id}/grant", response_model=PermissionOut)
def grant_permission(agent_id: str, body: GrantRequest, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        user_row = db.execute("SELECT id FROM users WHERE username = ?", (body.username,)).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        agent_row = db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not agent_row:
            raise HTTPException(status_code=404, detail="Agent not found")

        existing = db.execute(
            "SELECT 1 FROM permissions WHERE agent_id = ? AND user_id = ?",
            (agent_id, user_row["id"]),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Permission already exists")

        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO permissions (agent_id, user_id, granted_by, created_at) VALUES (?, ?, ?, ?)",
            (agent_id, user_row["id"], admin["id"], now),
        )
        db.commit()
        return PermissionOut(agent_id=agent_id, user_id=user_row["id"], granted_by=admin["id"], created_at=now)
    finally:
        db.close()


@router.delete("/{agent_id}/grant/{username}", status_code=204)
def revoke_permission(agent_id: str, username: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        user_row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        result = db.execute(
            "DELETE FROM permissions WHERE agent_id = ? AND user_id = ?",
            (agent_id, user_row["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Permission not found")
        db.commit()
    finally:
        db.close()
    return None

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import UserOut, AgentOut
from auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT id, username, role, created_at FROM users ORDER BY created_at").fetchall()
        return [UserOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/agents", response_model=list[AgentOut])
def list_all_agents(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
        return [AgentOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/users/{username}/agents", response_model=list[AgentOut])
def list_user_agents(username: str, admin: dict = Depends(require_admin)):
    """View all agents owned by a specific user (admin only)."""
    db = _sync_conn()
    try:
        user_row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not user_row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="User not found")
        rows = db.execute(
            "SELECT * FROM agents WHERE owner_id = ? ORDER BY created_at DESC",
            (user_row["id"],),
        ).fetchall()
        return [AgentOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.delete("/users/{username}", status_code=204)
def delete_user(username: str, admin: dict = Depends(require_admin)):
    """Delete a user and all their agents. Cannot delete self."""
    if username == admin["username"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    db = _sync_conn()
    try:
        user_row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        db.execute("DELETE FROM agents WHERE owner_id = ?", (user_row["id"],))
        db.execute("DELETE FROM users WHERE id = ?", (user_row["id"],))
        db.commit()
    finally:
        db.close()
    return None


@router.get("/root-agents", response_model=list[AgentOut])
def list_root_agents(admin: dict = Depends(require_admin)):
    """List all root agents (source_agent_id IS NULL)."""
    db = _sync_conn()
    try:
        rows = db.execute("""
            SELECT * FROM agents
            WHERE source_agent_id IS NULL
            ORDER BY created_at DESC
        """).fetchall()
        return [AgentOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/agents/{agent_id}/copies", response_model=list[AgentOut])
def list_agent_copies(agent_id: str, admin: dict = Depends(require_admin)):
    """List all copies of a root agent."""
    db = _sync_conn()
    try:
        root = db.execute(
            "SELECT id FROM agents WHERE id = ? AND source_agent_id IS NULL",
            (agent_id,),
        ).fetchone()
        if not root:
            raise HTTPException(status_code=404, detail="Root agent not found")

        rows = db.execute(
            "SELECT * FROM agents WHERE source_agent_id = ? ORDER BY created_at DESC",
            (agent_id,),
        ).fetchall()
        return [AgentOut(**dict(r)) for r in rows]
    finally:
        db.close()

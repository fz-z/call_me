from fastapi import APIRouter, Depends

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

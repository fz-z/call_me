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

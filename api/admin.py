from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import UserOut, AgentOut, CallLogOut, CallLogListResponse, StatsOverview, StatsTrendItem, StatsTopItem
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

        # Delete call logs for this user's agents first (FK constraint)
        agent_rows = db.execute("SELECT id FROM agents WHERE owner_id = ?", (user_row["id"],)).fetchall()
        for ag in agent_rows:
            db.execute("DELETE FROM call_logs WHERE agent_id = ?", (ag["id"],))
        # Also delete call logs where this user is the caller
        db.execute("DELETE FROM call_logs WHERE caller_user_id = ?", (user_row["id"],))
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


@router.get("/call-logs", response_model=CallLogListResponse)
def list_call_logs(
    agent_id: str | None = None,
    user_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(require_admin),
):
    db = _sync_conn()
    try:
        where_clauses = []
        params = []

        if agent_id:
            where_clauses.append("cl.agent_id = ?")
            params.append(agent_id)
        if user_id:
            where_clauses.append("cl.caller_user_id = ?")
            params.append(user_id)
        if status:
            where_clauses.append("cl.status = ?")
            params.append(status)

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        total_row = db.execute(
            f"SELECT COUNT(*) as c FROM call_logs cl {where}", params
        ).fetchone()
        total = total_row["c"]

        offset = (page - 1) * page_size
        rows = db.execute(
            f"""SELECT cl.*, a.alias as agent_alias, u.username as caller_username
                FROM call_logs cl
                JOIN agents a ON cl.agent_id = a.id
                JOIN users u ON cl.caller_user_id = u.id
                {where}
                ORDER BY cl.started_at DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()

        items = [CallLogOut(**dict(r)) for r in rows]
        return CallLogListResponse(items=items, total=total, page=page, page_size=page_size)
    finally:
        db.close()


@router.get("/stats/overview", response_model=StatsOverview)
def stats_overview(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        total = db.execute("SELECT COUNT(*) as c FROM call_logs").fetchone()["c"]
        today = db.execute(
            "SELECT COUNT(*) as c FROM call_logs WHERE date(started_at) = date('now')"
        ).fetchone()["c"]
        total_dur = db.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) as s FROM call_logs WHERE status = 'completed'"
        ).fetchone()["s"]
        active = db.execute(
            "SELECT COUNT(DISTINCT caller_user_id) as c FROM call_logs"
        ).fetchone()["c"]
        return StatsOverview(
            total_calls=total,
            today_calls=today,
            total_duration_seconds=total_dur,
            active_users=active,
        )
    finally:
        db.close()


@router.get("/stats/trend", response_model=list[StatsTrendItem])
def stats_trend(days: int = 30, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute(
            """SELECT date(started_at) as date, COUNT(*) as count
               FROM call_logs
               WHERE started_at >= date('now', ?)
               GROUP BY date(started_at)
               ORDER BY date ASC""",
            (f"-{days} days",),
        ).fetchall()
        return [StatsTrendItem(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/stats/top-agents", response_model=list[StatsTopItem])
def stats_top_agents(limit: int = 10, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute(
            """SELECT cl.agent_id as id, a.alias as name, COUNT(*) as count
               FROM call_logs cl
               JOIN agents a ON cl.agent_id = a.id
               GROUP BY cl.agent_id
               ORDER BY count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [StatsTopItem(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/stats/top-users", response_model=list[StatsTopItem])
def stats_top_users(limit: int = 10, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute(
            """SELECT cl.caller_user_id as id, u.username as name, COUNT(*) as count
               FROM call_logs cl
               JOIN users u ON cl.caller_user_id = u.id
               GROUP BY cl.caller_user_id
               ORDER BY count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [StatsTopItem(**dict(r)) for r in rows]
    finally:
        db.close()

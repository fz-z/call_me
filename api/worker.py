import os

from fastapi import APIRouter, Depends, Header, HTTPException

from database import _sync_conn
from config_utils import resolve_agent_runtime_config

router = APIRouter(prefix="/api/internal/worker", tags=["worker-internal"])


def require_worker_secret(x_worker_secret: str | None = Header(default=None)) -> None:
    expected = os.environ.get("WORKER_INTERNAL_SECRET") or os.environ.get("JWT_SECRET", "")
    if not expected or x_worker_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/agent-runtime/{agent_id}")
def get_agent_runtime(agent_id: str, _: None = Depends(require_worker_secret)):
    """Agent worker only: resolve LLM/TTS keys server-side (never sent to clients)."""
    db = _sync_conn()
    try:
        agent_row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not agent_row:
            raise HTTPException(status_code=404, detail="Agent not found")
        return resolve_agent_runtime_config(db, agent_row)
    finally:
        db.close()

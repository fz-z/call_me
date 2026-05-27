import os
import uuid
import json
import asyncio as _asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from livekit import api as lk_api

from database import _sync_conn
from models import TokenRequest, TokenResponse, CallLogEndRequest
from auth import get_current_user
from config_utils import public_agent_config_payload
from worker import require_worker_secret

router = APIRouter(prefix="/api/call", tags=["call"])

LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")

# Keep LIVEKIT_URL for token generation (ws_url)
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")


def _user_can_access(db, agent_id: str, user_id: str, role: str) -> bool:
    if role == "admin":
        return True
    row = db.execute("SELECT owner_id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    return row is not None and row["owner_id"] == user_id


@router.post("/token", response_model=TokenResponse)
def get_call_token(body: TokenRequest, user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        agent_row = db.execute("SELECT * FROM agents WHERE id = ?", (body.agent_id,)).fetchone()
        if not agent_row:
            raise HTTPException(status_code=404, detail="Agent not found")

        if not _user_can_access(db, body.agent_id, user["id"], user["role"]):
            raise HTTPException(status_code=403, detail="No permission to use this agent")

        room_name = f"call_{uuid.uuid4().hex[:12]}"

        # Record call start
        call_log_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO call_logs (id, agent_id, caller_user_id, room_name, started_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (call_log_id, body.agent_id, user["id"], room_name, now, "running"),
        )
        db.commit()

        agent_config = json.dumps(
            public_agent_config_payload(db, agent_row, call_log_id=call_log_id)
        )

        token = lk_api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET) \
            .with_identity(f"user_{user['username']}") \
            .with_name(user["username"]) \
            .with_attributes({"agent_config": agent_config}) \
            .with_grants(lk_api.VideoGrants(room_join=True, room=room_name)) \
            .to_jwt()

        ws_url = LIVEKIT_URL.replace("https://", "wss://").replace("http://", "ws://")
        return TokenResponse(token=token, room_url=ws_url)
    finally:
        db.close()


@router.patch("/admin/call-logs/{call_log_id}/end", status_code=204)
def end_call_log(
    call_log_id: str,
    body: CallLogEndRequest,
    _: None = Depends(require_worker_secret),
):
    """Worker callback: mark a call log as ended (requires X-Worker-Secret)."""
    db = _sync_conn()
    try:
        ended_at = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE call_logs SET status = ?, ended_at = ?, duration_seconds = ? WHERE id = ?",
            (body.status, ended_at, body.duration_seconds, call_log_id),
        )
        db.commit()
    finally:
        db.close()
    return None

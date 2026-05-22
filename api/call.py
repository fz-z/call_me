import os
import uuid
import json

from fastapi import APIRouter, Depends, HTTPException
from livekit import api as lk_api

from database import _sync_conn
from models import TokenRequest, TokenResponse
from auth import get_current_user

router = APIRouter(prefix="/api/call", tags=["call"])

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")


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
        agent_config = json.dumps({
            "agent_id": agent_row["id"],
            "alias": agent_row["alias"],
            "system_prompt": agent_row["system_prompt"],
            "voice_id": agent_row["voice_id"],
        })

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

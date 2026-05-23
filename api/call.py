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
        # Fetch model_config if agent has one
        model_config = None
        if agent_row["model_config_id"]:
            mc_row = db.execute(
                "SELECT * FROM model_configs WHERE id = ?",
                (agent_row["model_config_id"],),
            ).fetchone()
            if mc_row:
                model_config = {
                    "provider": mc_row["provider"],
                    "model": mc_row["model"],
                    "api_key": mc_row["api_key"],
                    "temperature": mc_row["temperature"],
                    "max_tokens": mc_row["max_tokens"],
                }

        # Fetch tts_config if agent has one
        tts_config = None
        if agent_row["tts_config_id"]:
            tc_row = db.execute(
                "SELECT * FROM tts_configs WHERE id = ?",
                (agent_row["tts_config_id"],),
            ).fetchone()
            if tc_row:
                tts_config = {
                    "provider": tc_row["provider"],
                    "model": tc_row["model"],
                    "api_key": tc_row["api_key"],
                }

        agent_config = json.dumps({
            "agent_id": agent_row["id"],
            "alias": agent_row["alias"],
            "system_prompt": agent_row["system_prompt"],
            "voice_id": agent_row["voice_id"],
            "model_config": model_config,
            "tts_config": tts_config,
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

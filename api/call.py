import os
import uuid
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from livekit import api as lk_api

from database import _sync_conn
from models import TokenRequest, TokenResponse, CallLogEndRequest
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

        # Record call start
        call_log_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO call_logs (id, agent_id, caller_user_id, room_name, started_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (call_log_id, body.agent_id, user["id"], room_name, now, "running"),
        )
        db.commit()

        # Fetch model_config (use agent's or fallback to first available in DB)
        model_config = None
        mc_id = agent_row["model_config_id"]
        if not mc_id:
            default_mc = db.execute(
                "SELECT id FROM model_configs ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if default_mc:
                mc_id = default_mc["id"]
        if mc_id:
            mc_row = db.execute(
                "SELECT mc.*, ak.api_key as resolved_key FROM model_configs mc LEFT JOIN api_keys ak ON mc.api_key_id = ak.id WHERE mc.id = ?",
                (mc_id,),
            ).fetchone()
            if mc_row:
                model_config = {
                    "provider": mc_row["provider"],
                    "model": mc_row["model"],
                    "api_key": mc_row["resolved_key"] or mc_row["api_key"] or "",
                    "temperature": mc_row["temperature"],
                    "max_tokens": mc_row["max_tokens"],
                }

        # Fetch tts_config (use agent's or fallback to first available in DB)
        tts_config = None
        tc_id = agent_row["tts_config_id"]
        if not tc_id:
            default_tc = db.execute(
                "SELECT id FROM tts_configs ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if default_tc:
                tc_id = default_tc["id"]
        if tc_id:
            tc_row = db.execute(
                "SELECT tc.*, ak.api_key as resolved_key FROM tts_configs tc LEFT JOIN api_keys ak ON tc.api_key_id = ak.id WHERE tc.id = ?",
                (tc_id,),
            ).fetchone()
            if tc_row:
                tts_config = {
                    "provider": tc_row["provider"],
                    "model": tc_row["model"],
                    "api_key": tc_row["resolved_key"] or tc_row["api_key"] or "",
                }

        # Fallback voice_id: if agent has none, use first voice from pool
        voice_id = agent_row["voice_id"]
        if not voice_id:
            default_voice = db.execute(
                "SELECT voice_id FROM voices ORDER BY type, name LIMIT 1"
            ).fetchone()
            if default_voice:
                voice_id = default_voice["voice_id"]

        agent_config = json.dumps({
            "agent_id": agent_row["id"],
            "alias": agent_row["alias"],
            "system_prompt": agent_row["system_prompt"],
            "voice_id": voice_id,
            "model_config": model_config,
            "tts_config": tts_config,
            "call_log_id": call_log_id,
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


@router.patch("/admin/call-logs/{call_log_id}/end", status_code=204)
def end_call_log(call_log_id: str, body: CallLogEndRequest):
    """Worker callback: mark a call log as ended. No auth (internal call from agent worker)."""
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

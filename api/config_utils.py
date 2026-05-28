"""Shared helpers for API key masking and agent runtime config resolution."""


def mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}...{api_key[-4:]}"


def _resolve_voice_id(db, agent_row) -> str | None:
    voice_id = agent_row["voice_id"]
    if voice_id:
        return voice_id
    default_voice = db.execute(
        "SELECT voice_id FROM voices ORDER BY type, name LIMIT 1"
    ).fetchone()
    return default_voice["voice_id"] if default_voice else None


def _resolve_model_config(db, agent_row) -> dict | None:
    mc_id = agent_row["model_config_id"]
    if not mc_id:
        default_mc = db.execute(
            "SELECT id FROM model_configs ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if default_mc:
            mc_id = default_mc["id"]
    if not mc_id:
        return None
    mc_row = db.execute(
        "SELECT mc.*, ak.api_key as resolved_key FROM model_configs mc "
        "LEFT JOIN api_keys ak ON mc.api_key_id = ak.id WHERE mc.id = ?",
        (mc_id,),
    ).fetchone()
    if not mc_row:
        return None
    return {
        "provider": mc_row["provider"],
        "model": mc_row["model"],
        "api_key": mc_row["resolved_key"] or mc_row["api_key"] or "",
        "temperature": mc_row["temperature"],
        "max_tokens": mc_row["max_tokens"],
    }


def _resolve_tts_config(db, agent_row) -> dict | None:
    tc_id = agent_row["tts_config_id"]
    if not tc_id:
        default_tc = db.execute(
            "SELECT id FROM tts_configs ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if default_tc:
            tc_id = default_tc["id"]
    if not tc_id:
        return None
    tc_row = db.execute(
        "SELECT tc.*, ak.api_key as resolved_key FROM tts_configs tc "
        "LEFT JOIN api_keys ak ON tc.api_key_id = ak.id WHERE tc.id = ?",
        (tc_id,),
    ).fetchone()
    if not tc_row:
        return None
    return {
        "provider": tc_row["provider"],
        "model": tc_row["model"],
        "api_key": tc_row["resolved_key"] or tc_row["api_key"] or "",
    }


def resolve_agent_runtime_config(db, agent_row) -> dict:
    """Full pipeline config for the agent worker (includes API keys)."""
    return {
        "agent_id": agent_row["id"],
        "alias": agent_row["alias"],
        "system_prompt": agent_row["system_prompt"],
        "voice_id": _resolve_voice_id(db, agent_row),
        "model_config": _resolve_model_config(db, agent_row),
        "tts_config": _resolve_tts_config(db, agent_row),
    }


def public_agent_config_payload(db, agent_row, *, call_log_id: str) -> dict:
    """Config embedded in LiveKit token (encrypted JWT) — includes model/tts configs
    with API keys so the agent worker can configure LLM/TTS dynamically."""
    runtime = resolve_agent_runtime_config(db, agent_row)
    return {
        "agent_id": runtime["agent_id"],
        "alias": runtime["alias"],
        "system_prompt": runtime["system_prompt"],
        "voice_id": runtime["voice_id"],
        "model_config": runtime["model_config"],
        "tts_config": runtime["tts_config"],
        "call_log_id": call_log_id,
    }

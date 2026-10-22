"""Shared helpers for API key masking and agent runtime config resolution."""

from fastapi import HTTPException

from runtime_bindings import resolve_voice_binding


def mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}...{api_key[-4:]}"


def _optional_config_id(value: str | None) -> str | None:
    return (value.strip() or None) if value is not None else None


def validate_agent_runtime_selection(
    db,
    *,
    runtime_mode: str | None,
    voice_pool_id: str | None,
    model_config_id: str | None,
    tts_config_id: str | None,
    realtime_config_id: str | None,
) -> dict:
    """Validate and normalize the complete runtime selection for an Agent.

    Pipeline Agents retain the existing optional LLM/TTS selection and default
    resolution behavior. Realtime Agents instead require one exact realtime
    configuration and a voice binding for that configuration; their classic
    LLM/TTS fields are deliberately cleared so they can never become an
    accidental realtime fallback.
    """
    if not voice_pool_id or not voice_pool_id.strip():
        raise HTTPException(status_code=400, detail="voice_pool_id is required")

    voice = db.execute(
        "SELECT id, voice_id FROM voices WHERE id = ?", (voice_pool_id,)
    ).fetchone()
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found in pool")

    mode = (runtime_mode or "pipeline").strip()
    if mode not in {"pipeline", "realtime"}:
        raise HTTPException(status_code=400, detail="runtime_mode must be pipeline or realtime")

    model_config_id = _optional_config_id(model_config_id)
    tts_config_id = _optional_config_id(tts_config_id)
    realtime_config_id = _optional_config_id(realtime_config_id)

    if mode == "pipeline":
        if not voice["voice_id"]:
            raise HTTPException(status_code=400, detail="Classic TTS voice is not available for this voice")
        if model_config_id and not db.execute(
            "SELECT id FROM model_configs WHERE id = ?", (model_config_id,)
        ).fetchone():
            raise HTTPException(status_code=400, detail="model_config_id not found")
        if tts_config_id and not db.execute(
            "SELECT id FROM tts_configs WHERE id = ?", (tts_config_id,)
        ).fetchone():
            raise HTTPException(status_code=400, detail="tts_config_id not found")
        return {
            "runtime_mode": "pipeline",
            "voice_pool_id": voice_pool_id,
            "voice_id": voice["voice_id"],
            "model_config_id": model_config_id,
            "tts_config_id": tts_config_id,
            "realtime_config_id": None,
        }

    if not realtime_config_id:
        raise HTTPException(status_code=400, detail="realtime_config_id is required for realtime agents")
    realtime_config = db.execute(
        "SELECT id FROM realtime_configs WHERE id = ?", (realtime_config_id,)
    ).fetchone()
    if not realtime_config:
        raise HTTPException(status_code=400, detail="realtime_config_id not found")
    if not resolve_voice_binding(db, voice_pool_id, "realtime", realtime_config_id):
        raise HTTPException(
            status_code=400,
            detail="Voice has no binding for the selected realtime configuration",
        )
    return {
        "runtime_mode": "realtime",
        "voice_pool_id": voice_pool_id,
        "voice_id": voice["voice_id"],
        "model_config_id": None,
        "tts_config_id": None,
        "realtime_config_id": realtime_config_id,
    }


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


def _resolve_realtime_config(db, agent_row) -> dict | None:
    config_id = agent_row["realtime_config_id"]
    voice_pool_id = agent_row["voice_pool_id"]
    if not config_id or not voice_pool_id:
        return None
    config = db.execute(
        "SELECT rc.*, ak.api_key AS resolved_key FROM realtime_configs rc "
        "LEFT JOIN api_keys ak ON rc.api_key_id = ak.id WHERE rc.id = ?",
        (config_id,),
    ).fetchone()
    binding = resolve_voice_binding(db, voice_pool_id, "realtime", config_id)
    if not config or not binding:
        return None
    return {
        "name": config["name"],
        "provider": config["provider"],
        "model": config["model"],
        "endpoint": config["endpoint"],
        "api_key": config["resolved_key"] or config["api_key"] or "",
        "voice_id": binding["provider_voice_id"],
    }


def resolve_agent_runtime_config(db, agent_row) -> dict:
    """Return one discriminated, secret-bearing runtime payload for the Worker."""
    runtime_mode = agent_row["runtime_mode"] or "pipeline"
    base = {
        "agent_id": agent_row["id"],
        "alias": agent_row["alias"],
        "system_prompt": agent_row["system_prompt"],
        "runtime_mode": runtime_mode,
        "speech_rate": float(agent_row["speech_rate"] or 1.0),
        "allow_interruptions": bool(agent_row["allow_interruptions"]),
    }
    if runtime_mode == "realtime":
        base["realtime_config"] = _resolve_realtime_config(db, agent_row)
        return base

    # Existing rows and all pipeline Agents preserve legacy default resolution.
    return {
        **base,
        "voice_id": _resolve_voice_id(db, agent_row),
        "model_config": _resolve_model_config(db, agent_row),
        "tts_config": _resolve_tts_config(db, agent_row),
    }


def public_agent_config_payload(db, agent_row, *, call_log_id: str) -> dict:
    """Return only non-secret metadata safe to embed in a client LiveKit token."""
    return {
        "agent_id": agent_row["id"],
        "runtime_mode": agent_row["runtime_mode"] or "pipeline",
        "call_log_id": call_log_id,
    }

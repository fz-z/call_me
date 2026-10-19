import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth import require_admin
from database import _sync_conn
from models import RealtimeConfigCreate, RealtimeConfigOut, RealtimeConfigUpdate


SUPPORTED_PROVIDER = "qwen"
SUPPORTED_MODEL = "qwen-audio-3.1-realtime-plus"

router = APIRouter(prefix="/api/admin/realtime-configs", tags=["realtime-configs"])


def _realtime_config_out(row) -> RealtimeConfigOut:
    data = dict(row)
    data.pop("api_key", None)
    return RealtimeConfigOut(**data)


def _validate_provider_and_model(provider: str, model: str) -> None:
    if provider != SUPPORTED_PROVIDER:
        raise HTTPException(status_code=400, detail="Provider must be qwen")
    if model != SUPPORTED_MODEL:
        raise HTTPException(
            status_code=400,
            detail="Model must be qwen-audio-3.1-realtime-plus",
        )


def _resolve_api_key_id(db, api_key_id: str | None, api_key: str | None, provider: str) -> str | None:
    """Resolve a legacy supplied key to its provider key record and validate references."""
    if not api_key_id and api_key:
        key_row = db.execute(
            "SELECT id FROM api_keys WHERE provider = ? LIMIT 1", (provider,)
        ).fetchone()
        if key_row:
            api_key_id = key_row["id"]

    if api_key_id:
        key_row = db.execute(
            "SELECT provider FROM api_keys WHERE id = ?", (api_key_id,)
        ).fetchone()
        if not key_row:
            raise HTTPException(status_code=400, detail="API key not found")
        if key_row["provider"] != provider:
            raise HTTPException(
                status_code=400, detail="API key provider does not match config provider"
            )
    return api_key_id


@router.get("", response_model=list[RealtimeConfigOut])
def list_configs(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT * FROM realtime_configs ORDER BY created_at DESC").fetchall()
        return [_realtime_config_out(row) for row in rows]
    finally:
        db.close()


@router.post("", response_model=RealtimeConfigOut)
def create_config(body: RealtimeConfigCreate, admin: dict = Depends(require_admin)):
    _validate_provider_and_model(body.provider, body.model)
    db = _sync_conn()
    try:
        existing = db.execute(
            "SELECT id FROM realtime_configs WHERE name = ?", (body.name,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Config name already exists")

        api_key_id = _resolve_api_key_id(
            db, body.api_key_id, body.api_key, body.provider
        )
        config_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO realtime_configs "
            "(id, name, provider, model, api_key_id, api_key, endpoint, region, capabilities_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                config_id,
                body.name,
                body.provider,
                body.model,
                api_key_id,
                body.api_key or "",
                body.endpoint,
                body.region,
                body.capabilities_json,
                now,
            ),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM realtime_configs WHERE id = ?", (config_id,)
        ).fetchone()
        return _realtime_config_out(row)
    finally:
        db.close()


@router.patch("/{config_id}", response_model=RealtimeConfigOut)
def update_config(
    config_id: str, body: RealtimeConfigUpdate, admin: dict = Depends(require_admin)
):
    db = _sync_conn()
    try:
        row = db.execute(
            "SELECT * FROM realtime_configs WHERE id = ?", (config_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Config not found")

        provider = body.provider if body.provider is not None else row["provider"]
        model = body.model if body.model is not None else row["model"]
        _validate_provider_and_model(provider, model)

        api_key_id = body.api_key_id if body.api_key_id is not None else row["api_key_id"]
        api_key = body.api_key if body.api_key is not None else row["api_key"]
        api_key_id = _resolve_api_key_id(db, api_key_id, api_key, provider)

        db.execute(
            "UPDATE realtime_configs SET "
            "name=?, provider=?, model=?, api_key_id=?, api_key=?, endpoint=?, region=?, capabilities_json=? "
            "WHERE id=?",
            (
                body.name if body.name is not None else row["name"],
                provider,
                model,
                api_key_id,
                api_key,
                body.endpoint if body.endpoint is not None else row["endpoint"],
                body.region if body.region is not None else row["region"],
                body.capabilities_json
                if body.capabilities_json is not None
                else row["capabilities_json"],
                config_id,
            ),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM realtime_configs WHERE id = ?", (config_id,)
        ).fetchone()
        return _realtime_config_out(row)
    finally:
        db.close()


@router.delete("/{config_id}", status_code=204)
def delete_config(config_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        existing = db.execute(
            "SELECT id FROM realtime_configs WHERE id = ?", (config_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Config not found")

        agent_references = db.execute(
            "SELECT COUNT(*) AS count FROM agents WHERE realtime_config_id = ?",
            (config_id,),
        ).fetchone()["count"]
        binding_references = db.execute(
            "SELECT COUNT(*) AS count FROM voice_runtime_bindings WHERE runtime_config_id = ?",
            (config_id,),
        ).fetchone()["count"]
        reference_count = agent_references + binding_references
        if reference_count:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Config is referenced by agents or voice bindings",
                    "reference_count": reference_count,
                },
            )

        db.execute("DELETE FROM realtime_configs WHERE id = ?", (config_id,))
        db.commit()
    finally:
        db.close()
    return None

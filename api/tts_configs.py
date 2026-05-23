import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import TtsConfigCreate, TtsConfigUpdate, TtsConfigOut
from auth import require_admin

router = APIRouter(prefix="/api/admin/tts-configs", tags=["tts-configs"])


@router.get("", response_model=list[TtsConfigOut])
def list_configs(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT * FROM tts_configs ORDER BY created_at DESC").fetchall()
        return [TtsConfigOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.post("", response_model=TtsConfigOut)
def create_config(body: TtsConfigCreate, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM tts_configs WHERE name = ?", (body.name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Config name already exists")

        config_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        api_key_id = body.api_key_id
        # If api_key_id is not provided, try to resolve by provider
        if not api_key_id and body.api_key:
            key_row = db.execute(
                "SELECT id FROM api_keys WHERE provider = ? LIMIT 1", (body.provider,)
            ).fetchone()
            if key_row:
                api_key_id = key_row["id"]

        db.execute(
            "INSERT INTO tts_configs (id, name, provider, model, api_key, api_key_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (config_id, body.name, body.provider, body.model, body.api_key or "", api_key_id, now),
        )
        db.commit()
        return TtsConfigOut(
            id=config_id, name=body.name, provider=body.provider,
            model=body.model, api_key=body.api_key, api_key_id=api_key_id, created_at=now,
        )
    finally:
        db.close()


@router.patch("/{config_id}", response_model=TtsConfigOut)
def update_config(config_id: str, body: TtsConfigUpdate, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        row = db.execute("SELECT * FROM tts_configs WHERE id = ?", (config_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Config not found")

        # Resolve api_key_id: explicit value > existing value > lookup by provider
        api_key_id = body.api_key_id
        if api_key_id is None:
            api_key_id = row["api_key_id"]
        if not api_key_id and body.api_key:
            provider = body.provider if body.provider is not None else row["provider"]
            key_row = db.execute(
                "SELECT id FROM api_keys WHERE provider = ? LIMIT 1", (provider,)
            ).fetchone()
            if key_row:
                api_key_id = key_row["id"]

        db.execute(
            "UPDATE tts_configs SET name=?, provider=?, model=?, api_key=?, api_key_id=? WHERE id=?",
            (
                body.name if body.name is not None else row["name"],
                body.provider if body.provider is not None else row["provider"],
                body.model if body.model is not None else row["model"],
                body.api_key if body.api_key is not None else row["api_key"],
                api_key_id,
                config_id,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM tts_configs WHERE id = ?", (config_id,)).fetchone()
        return TtsConfigOut(**dict(row))
    finally:
        db.close()


@router.delete("/{config_id}", status_code=204)
def delete_config(config_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM tts_configs WHERE id = ?", (config_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Config not found")

        db.execute("UPDATE agents SET tts_config_id = NULL WHERE tts_config_id = ?", (config_id,))
        db.execute("DELETE FROM tts_configs WHERE id = ?", (config_id,))
        db.commit()
    finally:
        db.close()
    return None

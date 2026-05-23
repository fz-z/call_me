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
        db.execute(
            "INSERT INTO tts_configs (id, name, provider, model, api_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (config_id, body.name, body.provider, body.model, body.api_key, now),
        )
        db.commit()
        return TtsConfigOut(
            id=config_id, name=body.name, provider=body.provider,
            model=body.model, api_key=body.api_key, created_at=now,
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

        db.execute(
            "UPDATE tts_configs SET name=?, provider=?, model=?, api_key=? WHERE id=?",
            (
                body.name if body.name is not None else row["name"],
                body.provider if body.provider is not None else row["provider"],
                body.model if body.model is not None else row["model"],
                body.api_key if body.api_key is not None else row["api_key"],
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

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import ApiKeyCreate, ApiKeyUpdate, ApiKeyOut
from auth import require_admin
from config_utils import mask_api_key

router = APIRouter(prefix="/api/admin/api-keys", tags=["api-keys"])


def _api_key_out(row) -> ApiKeyOut:
    data = dict(row)
    preview = mask_api_key(data.pop("api_key", ""))
    return ApiKeyOut(**data, api_key_preview=preview)


@router.get("", response_model=list[ApiKeyOut])
def list_keys(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT * FROM api_keys ORDER BY created_at").fetchall()
        return [_api_key_out(r) for r in rows]
    finally:
        db.close()


@router.post("", response_model=ApiKeyOut)
def create_key(body: ApiKeyCreate, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM api_keys WHERE name = ?", (body.name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Key name already exists")
        kid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO api_keys (id, name, provider, api_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (kid, body.name, body.provider, body.api_key, now),
        )
        db.commit()
        row = db.execute("SELECT * FROM api_keys WHERE id = ?", (kid,)).fetchone()
        return _api_key_out(row)
    finally:
        db.close()


@router.patch("/{key_id}", response_model=ApiKeyOut)
def update_key(key_id: str, body: ApiKeyUpdate, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        row = db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Key not found")
        new_key = row["api_key"]
        if body.api_key is not None and body.api_key.strip():
            new_key = body.api_key.strip()
        db.execute(
            "UPDATE api_keys SET name=?, provider=?, api_key=? WHERE id=?",
            (body.name or row["name"], body.provider or row["provider"], new_key, key_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        return _api_key_out(row)
    finally:
        db.close()


@router.delete("/{key_id}", status_code=204)
def delete_key(key_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        db.execute("UPDATE model_configs SET api_key_id = NULL WHERE api_key_id = ?", (key_id,))
        db.execute("UPDATE tts_configs SET api_key_id = NULL WHERE api_key_id = ?", (key_id,))
        db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        db.commit()
    finally:
        db.close()
    return None

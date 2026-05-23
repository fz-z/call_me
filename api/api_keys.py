import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import ApiKeyCreate, ApiKeyUpdate, ApiKeyOut
from auth import require_admin

router = APIRouter(prefix="/api/admin/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
def list_keys(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT * FROM api_keys ORDER BY created_at").fetchall()
        return [ApiKeyOut(**dict(r)) for r in rows]
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
        return ApiKeyOut(id=kid, name=body.name, provider=body.provider, api_key=body.api_key, created_at=now)
    finally:
        db.close()


@router.patch("/{key_id}", response_model=ApiKeyOut)
def update_key(key_id: str, body: ApiKeyUpdate, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        row = db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Key not found")
        db.execute(
            "UPDATE api_keys SET name=?, provider=?, api_key=? WHERE id=?",
            (body.name or row["name"], body.provider or row["provider"], body.api_key or row["api_key"], key_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        return ApiKeyOut(**dict(row))
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

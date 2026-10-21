import asyncio
import base64
import uuid
import os
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database import _sync_conn
from models import VoiceOut, VoiceCreate, VoiceManualCreate, VoiceUpdate, TtsConfigOut, VoiceTtsLinkRequest, AuditionRequest, AuditionResponse, RealtimeAuditionRequest, VoiceRuntimeBindingOut
from auth import require_admin
from voice_enrollment import enroll_voice
from tts_strategy import get_tts_strategy
from runtime_bindings import list_voice_bindings, resolve_voice_binding
from realtime_audition import (
    synthesize_realtime_preview, RealtimeAuditionTooLarge,
    RealtimeAuditionNoAudio, RealtimeAuditionRejected,
)
from realtime_configs import SUPPORTED_MODEL, SUPPORTED_PROVIDER
from temporary_voice_audio import publish_voice_audio, remove_published_voice_audio

router = APIRouter(prefix="/api/admin/voices", tags=["voices"])


def _normalize_provider(provider: str) -> str:
    """Normalize provider names to canonical form (qwen / volcengine / deepseek / etc)."""
    p = (provider or "").lower()
    if any(kw in p for kw in ("qwen", "dashscope", "百炼", "bailian", "阿里", "alibaba")):
        return "qwen"
    if any(kw in p for kw in ("volcengine", "volc", "bytedance", "火山", "字节")):
        return "qwen"  # uses same DashScope-compatible audition flow
    if "deepseek" in p:
        return "deepseek"
    return p


def _voice_clone_is_supported(capabilities_json: str) -> bool:
    try:
        capabilities = json.loads(capabilities_json or "{}")
    except json.JSONDecodeError:
        return False
    return isinstance(capabilities, dict) and capabilities.get("voice_clone") is True


def _voice_enrollment_endpoint() -> str | None:
    override = os.environ.get("QWEN_VOICE_ENROLLMENT_API_URL", "").strip()
    if override:
        return override
    workspace = os.environ.get("DASHSCOPE_WORKSPACE", "").strip()
    if workspace:
        return (
            f"https://{workspace}.cn-beijing.maas.aliyuncs.com/"
            "api/v1/services/audio/tts/customization"
        )
    return None


def _enrollment_endpoint(realtime_endpoint: str | None) -> str | None:
    """Map a Model Studio realtime WebSocket URL to its enrollment HTTP API.

    The endpoint stored on a realtime configuration is for conversations, e.g.
    ``wss://<workspace>.../api-ws/v1/realtime``. Voice enrollment is a separate
    REST operation in that same workspace, so POSTing to the WebSocket URL can
    never create a cloned voice.
    """
    if not realtime_endpoint:
        return None

    parsed = urlsplit(realtime_endpoint)
    if (
        parsed.scheme in {"ws", "wss"}
        and parsed.path.rstrip("/") == "/api-ws/v1/realtime"
        and parsed.netloc
    ):
        return urlunsplit(
            (
                "https" if parsed.scheme == "wss" else "http",
                parsed.netloc,
                "/api/v1/services/audio/tts/customization",
                "",
                "",
            )
        )
    return realtime_endpoint


def _get_realtime_config(db, realtime_config_id: str):
    config = db.execute(
        "SELECT rc.*, COALESCE(ak.api_key, rc.api_key, '') AS resolved_api_key "
        "FROM realtime_configs rc LEFT JOIN api_keys ak ON ak.id = rc.api_key_id "
        "WHERE rc.id = ?",
        (realtime_config_id,),
    ).fetchone()
    if not config:
        raise HTTPException(status_code=404, detail="Realtime config not found")
    if config["provider"] != SUPPORTED_PROVIDER or config["model"] != SUPPORTED_MODEL:
        raise HTTPException(status_code=400, detail="Realtime config is not a supported Qwen configuration")
    if not _voice_clone_is_supported(config["capabilities_json"]):
        raise HTTPException(status_code=400, detail="Realtime config must declare voice_clone capability")
    if not config["resolved_api_key"]:
        raise HTTPException(status_code=400, detail="Realtime config has no valid API key")
    return config


async def _enroll_audio(api_key: str, target_model: str, endpoint: str | None, voice_name: str, audio_bytes: bytes, content_type: str) -> str:
    token, audio_url = publish_voice_audio(audio_bytes, content_type)
    try:
        return await enroll_voice(
            audio_bytes,
            content_type,
            api_key,
            voice_name=voice_name,
            target_model=target_model,
            endpoint=endpoint,
            audio_url=audio_url,
        )
    except Exception as error:
        message = str(error)
        if api_key:
            message = message.replace(api_key, "[密钥已隐藏]")
        message = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [密钥已隐藏]", message)
        message = message.replace(audio_url, "[临时音频地址]")
        message = message[:500].strip()
        raise HTTPException(
            status_code=502,
            detail=f"百炼音色复刻失败：{message or '未返回错误详情'}",
        ) from error
    finally:
        remove_published_voice_audio(token)


async def _enroll_realtime_audio(config, voice_name: str, audio_bytes: bytes, content_type: str) -> str:
    return await _enroll_audio(
        config["resolved_api_key"],
        config["model"],
        _enrollment_endpoint(config["endpoint"]),
        voice_name,
        audio_bytes,
        content_type,
    )


@router.get("", response_model=list[VoiceOut])
def list_voices(
    tts_config_id: str | None = None,
    admin: dict = Depends(require_admin),
):
    db = _sync_conn()
    try:
        if tts_config_id:
            rows = db.execute(
                "SELECT v.* FROM voices v JOIN voice_tts_links vl ON v.id = vl.voice_id WHERE vl.tts_config_id = ? ORDER BY v.type, v.name",
                (tts_config_id,),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM voices ORDER BY type, name").fetchall()
        return [VoiceOut(**dict(r), has_classic_voice=bool(r["voice_id"])) for r in rows]
    finally:
        db.close()


@router.post("", response_model=VoiceOut)
async def create_voice(
    name: str = Form(...),
    audio_file: UploadFile = File(...),
    tts_config_id: str | None = Form(None),
    admin: dict = Depends(require_admin),
):
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    audio_bytes = await audio_file.read()
    content_type = audio_file.content_type or "audio/wav"

    # The TTS configuration owns the provider key. Prefer its linked API key so
    # uploads keep working when the bootstrap .env key is stale or absent.
    tts_model = None
    if tts_config_id:
        db = _sync_conn()
        try:
            tc = db.execute(
                "SELECT tc.model, tc.api_key, COALESCE(ak.api_key, '') AS resolved_key "
                "FROM tts_configs tc LEFT JOIN api_keys ak ON tc.api_key_id = ak.id "
                "WHERE tc.id = ?",
                (tts_config_id,),
            ).fetchone()
            if tc:
                tts_model = tc["model"]
                api_key = tc["resolved_key"] or tc["api_key"] or api_key
        finally:
            db.close()

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="No DashScope API key configured for voice enrollment",
        )

    try:
        dashscope_voice_id = await _enroll_audio(
            api_key,
            tts_model or os.environ.get("SEED_TTS_VC_MODEL", "qwen3-tts-vc-realtime-2026-01-15"),
            _voice_enrollment_endpoint(),
            name,
            audio_bytes,
            content_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"百炼音色复刻失败：{str(e)[:500]}") from e

    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM voices WHERE name = ?", (name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Voice name already exists")

        voice_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
            (voice_id, name, dashscope_voice_id, "cloned", now),
        )
        if tts_config_id:
            tts_exists = db.execute("SELECT id FROM tts_configs WHERE id = ?", (tts_config_id,)).fetchone()
            if tts_exists:
                db.execute(
                    "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
                    (voice_id, tts_config_id),
                )
        db.commit()
        return VoiceOut(id=voice_id, name=name, type="cloned", has_classic_voice=True, created_at=now)
    finally:
        db.close()


@router.post("/manual", response_model=VoiceOut)
def create_voice_manual(body: VoiceManualCreate, admin: dict = Depends(require_admin)):
    if body.type not in ("builtin", "cloned"):
        raise HTTPException(status_code=400, detail="type must be 'builtin' or 'cloned'")

    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM voices WHERE name = ?", (body.name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Voice name already exists")

        voice_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
            (voice_id, body.name, body.voice_id, body.type, now),
        )
        if body.tts_config_id:
            tts_exists = db.execute("SELECT id FROM tts_configs WHERE id = ?", (body.tts_config_id,)).fetchone()
            if tts_exists:
                db.execute(
                    "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
                    (voice_id, body.tts_config_id),
                )
        db.commit()
        return VoiceOut(id=voice_id, name=body.name, type=body.type, has_classic_voice=bool(body.voice_id), created_at=now)
    finally:
        db.close()


@router.patch("/{voice_id}", response_model=VoiceOut)
def update_voice(voice_id: str, body: VoiceUpdate, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")

        if body.name is not None:
            existing = db.execute("SELECT id FROM voices WHERE name = ? AND id != ?", (body.name, voice_id)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Voice name already exists")
            db.execute("UPDATE voices SET name = ? WHERE id = ?", (body.name, voice_id))

        if body.audition_text is not None:
            db.execute("UPDATE voices SET audition_text = ? WHERE id = ?", (body.audition_text, voice_id))

        db.commit()
        updated = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        return VoiceOut(**dict(updated), has_classic_voice=bool(updated["voice_id"]))
    finally:
        db.close()


@router.delete("/{voice_id}", status_code=204)
def delete_voice(voice_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        refs = db.execute(
            "SELECT COUNT(*) as c FROM agents WHERE voice_pool_id = ?", (voice_id,)
        ).fetchone()["c"]
        if refs > 0:
            raise HTTPException(status_code=400, detail=f"Voice is used by {refs} agent(s)")

        db.execute("DELETE FROM voices WHERE id = ?", (voice_id,))
        db.commit()
    finally:
        db.close()
    return None


@router.get("/{voice_id}/runtime-bindings", response_model=list[VoiceRuntimeBindingOut])
def get_voice_runtime_bindings(voice_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT id FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        return [VoiceRuntimeBindingOut(**binding) for binding in list_voice_bindings(db, voice_id)]
    finally:
        db.close()


@router.post("/{voice_id}/realtime-bindings", response_model=VoiceRuntimeBindingOut)
async def create_realtime_binding(
    voice_id: str,
    realtime_config_id: str = Form(...),
    audio_file: UploadFile = File(...),
    authorization_confirmed: bool = Form(...),
    admin: dict = Depends(require_admin),
):
    if not authorization_confirmed:
        raise HTTPException(status_code=400, detail="Reference-audio authorization must be confirmed")

    db = _sync_conn()
    try:
        voice = db.execute("SELECT id, name FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        config = _get_realtime_config(db, realtime_config_id)
        voice_name = voice["name"]
        audio_bytes = await audio_file.read(10 * 1024 * 1024 + 1)
        if len(audio_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Reference audio must be 10 MB or smaller")
        content_type = audio_file.content_type or "audio/wav"
        provider_voice_id = await _enroll_realtime_audio(config, voice_name, audio_bytes, content_type)

        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO voice_runtime_bindings "
            "(id, voice_pool_id, runtime_kind, runtime_config_id, provider_voice_id, created_at) "
            "VALUES (?, ?, 'realtime', ?, ?, ?) "
            "ON CONFLICT(voice_pool_id, runtime_kind, runtime_config_id) DO UPDATE SET "
            "provider_voice_id = excluded.provider_voice_id, created_at = excluded.created_at",
            (str(uuid.uuid4()), voice_id, realtime_config_id, provider_voice_id, now),
        )
        db.commit()
        binding = next(
            item
            for item in list_voice_bindings(db, voice_id)
            if item["runtime_kind"] == "realtime" and item["runtime_config_id"] == realtime_config_id
        )
        return VoiceRuntimeBindingOut(**binding)
    finally:
        db.close()


@router.post("/realtime", response_model=VoiceOut, status_code=201)
async def create_realtime_voice(
    name: str = Form(...),
    realtime_config_id: str = Form(...),
    audio_file: UploadFile = File(...),
    authorization_confirmed: bool = Form(...),
    admin: dict = Depends(require_admin),
):
    """Create a voice-pool entry and its realtime binding without any TTS link."""
    if not authorization_confirmed:
        raise HTTPException(status_code=400, detail="Reference-audio authorization must be confirmed")
    cleaned_name = name.strip()
    if not cleaned_name:
        raise HTTPException(status_code=400, detail="Voice name is required")

    db = _sync_conn()
    try:
        if db.execute("SELECT id FROM voices WHERE name = ?", (cleaned_name,)).fetchone():
            raise HTTPException(status_code=409, detail="Voice name already exists")
        config = _get_realtime_config(db, realtime_config_id)
    finally:
        db.close()

    suffix = os.path.splitext(audio_file.filename or "")[1].lower()
    if suffix not in {".wav", ".mp3", ".m4a"}:
        raise HTTPException(status_code=400, detail="Reference audio must be WAV, MP3, or M4A")
    audio_bytes = await audio_file.read(10 * 1024 * 1024 + 1)
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Reference audio must be 10 MB or smaller")
    content_type = audio_file.content_type or "audio/wav"
    provider_voice_id = await _enroll_realtime_audio(config, cleaned_name, audio_bytes, content_type)

    now = datetime.now(timezone.utc).isoformat()
    voice_id = str(uuid.uuid4())
    db = _sync_conn()
    try:
        db.execute(
            "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, '', 'cloned', ?)",
            (voice_id, cleaned_name, now),
        )
        db.execute(
            "INSERT INTO voice_runtime_bindings "
            "(id, voice_pool_id, runtime_kind, runtime_config_id, provider_voice_id, created_at) "
            "VALUES (?, ?, 'realtime', ?, ?, ?)",
            (str(uuid.uuid4()), voice_id, realtime_config_id, provider_voice_id, now),
        )
        db.commit()
        return VoiceOut(id=voice_id, name=cleaned_name, type="cloned", has_classic_voice=False, created_at=now)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/{voice_id}/tts-configs", response_model=list[TtsConfigOut])
def get_voice_tts_configs(voice_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute(
            "SELECT tc.* FROM tts_configs tc JOIN voice_tts_links vl ON tc.id = vl.tts_config_id WHERE vl.voice_id = ?",
            (voice_id,),
        ).fetchall()
        return [TtsConfigOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.post("/{voice_id}/tts-configs", status_code=204)
def link_voice_tts(voice_id: str, body: VoiceTtsLinkRequest, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT id, voice_id FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        if not voice["voice_id"]:
            raise HTTPException(status_code=400, detail="Classic TTS voice is not available; clone audio for a TTS model first")
        tts = db.execute("SELECT id FROM tts_configs WHERE id = ?", (body.tts_config_id,)).fetchone()
        if not tts:
            raise HTTPException(status_code=404, detail="TTS config not found")

        db.execute(
            "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
            (voice_id, body.tts_config_id),
        )
        db.commit()
    finally:
        db.close()
    return None


@router.delete("/{voice_id}/tts-configs/{tts_id}", status_code=204)
def unlink_voice_tts(voice_id: str, tts_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        db.execute(
            "DELETE FROM voice_tts_links WHERE voice_id = ? AND tts_config_id = ?",
            (voice_id, tts_id),
        )
        db.commit()
    finally:
        db.close()
    return None


@router.post("/{voice_id}/realtime-bindings/{realtime_config_id}/audition", response_model=AuditionResponse)
async def audition_realtime_binding(
    voice_id: str, realtime_config_id: str, body: RealtimeAuditionRequest,
    admin: dict = Depends(require_admin),
):
    db = _sync_conn()
    try:
        binding = resolve_voice_binding(db, voice_id, "realtime", realtime_config_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Realtime voice binding not found")
        config = _get_realtime_config(db, realtime_config_id)
        preview_args = {
            "api_key": config["resolved_api_key"], "endpoint": config["endpoint"],
            "model": config["model"], "voice_id": binding["provider_voice_id"],
            "text": body.text,
        }
    finally:
        db.close()
    try:
        wav = await synthesize_realtime_preview(**preview_args)
    except asyncio.TimeoutError as error:
        raise HTTPException(status_code=504, detail="实时音色试听超时，请稍后重试。") from error
    except RealtimeAuditionTooLarge as error:
        raise HTTPException(status_code=413, detail="试听音频过长，请缩短文案。") from error
    except RealtimeAuditionNoAudio as error:
        raise HTTPException(status_code=502, detail="实时模型未生成音频，请检查音色绑定或稍后重试。") from error
    except RealtimeAuditionRejected as error:
        raise HTTPException(status_code=502, detail="实时模型拒绝了试听请求，请检查模型配置后重试。") from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="实时音色试听生成失败，请检查模型配置后重试。") from error
    return AuditionResponse(audio_base64=base64.b64encode(wav).decode(), mime_type="audio/wav")


@router.post("/{voice_id}/audition", response_model=AuditionResponse)
async def audition_voice(voice_id: str, body: AuditionRequest, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")

        query = (
            "SELECT tc.*, ak.api_key as resolved_key FROM tts_configs tc "
            "JOIN voice_tts_links vl ON tc.id = vl.tts_config_id "
            "LEFT JOIN api_keys ak ON tc.api_key_id = ak.id "
            "WHERE vl.voice_id = ?"
        )
        params = [voice_id]
        if body.tts_config_id:
            query += " AND tc.id = ?"
            params.append(body.tts_config_id)
        query += " ORDER BY tc.created_at ASC LIMIT 1"
        tts_row = db.execute(query, params).fetchone()
        if not tts_row:
            raise HTTPException(status_code=400, detail="Voice has no matching linked TTS config")
    finally:
        db.close()

    provider = _normalize_provider(tts_row["provider"] or "")
    if provider != "qwen":
        raise HTTPException(status_code=400, detail=f"Audition not supported for provider: {tts_row['provider']}")

    model = tts_row["model"] or ""
    try:
        strategy = get_tts_strategy(model)
        audio_base64, mime_type = await strategy.synthesize(tts_row, voice["voice_id"], body.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {e}")

    return {"audio_base64": audio_base64, "mime_type": mime_type}

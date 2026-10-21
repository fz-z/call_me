from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    created_at: str


class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class AdminCreateUser(BaseModel):
    username: str
    password: str = "aB@12345"


class ChangePassword(BaseModel):
    old_password: str
    new_password: str


class AdminResetPassword(BaseModel):
    new_password: str = "aB@12345"


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class AgentCreate(BaseModel):
    alias: str
    system_prompt: str = ""
    voice_pool_id: str
    model_config_id: Optional[str] = None
    tts_config_id: Optional[str] = None
    runtime_mode: str = "pipeline"
    realtime_config_id: Optional[str] = None
    photo_url: Optional[str] = None
    speech_rate: float = 1.0


class AgentUpdate(BaseModel):
    alias: Optional[str] = None
    system_prompt: Optional[str] = None
    model_config_id: Optional[str] = None
    voice_pool_id: Optional[str] = None
    tts_config_id: Optional[str] = None
    runtime_mode: Optional[str] = None
    realtime_config_id: Optional[str] = None
    photo_url: Optional[str] = None
    speech_rate: Optional[float] = None


class AgentOut(BaseModel):
    id: str
    alias: str
    voice_pool_id: Optional[str] = None
    system_prompt: str
    owner_id: str
    source_agent_id: Optional[str] = None
    model_config_id: Optional[str] = None
    tts_config_id: Optional[str] = None
    runtime_mode: str = "pipeline"
    realtime_config_id: Optional[str] = None
    photo_url: Optional[str] = None
    created_at: str
    speech_rate: float = 1.0


class PermissionOut(BaseModel):
    agent_id: str
    user_id: str
    granted_by: str
    created_at: str


class GrantRequest(BaseModel):
    username: str


class TokenRequest(BaseModel):
    agent_id: str


class TokenResponse(BaseModel):
    token: str
    room_url: str


class ApiKeyOut(BaseModel):
    id: str
    name: str
    provider: str
    api_key_preview: str
    created_at: str


class ApiKeyCreate(BaseModel):
    name: str
    provider: str
    api_key: str


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    api_key: Optional[str] = None


class ModelConfigCreate(BaseModel):
    name: str
    provider: str
    model: str
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048


class ModelConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ModelConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    api_key_id: Optional[str] = None
    temperature: float
    max_tokens: int
    created_at: str


class TtsConfigCreate(BaseModel):
    name: str
    provider: str
    model: str
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    supports_voice_clone: bool = True


class TtsConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    supports_voice_clone: Optional[bool] = None


class TtsConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    api_key_id: Optional[str] = None
    supports_voice_clone: bool = True
    created_at: str


class RealtimeConfigCreate(BaseModel):
    name: str
    provider: str
    model: str
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    endpoint: str = ""
    region: str = ""
    capabilities_json: str = "{}"


class RealtimeConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    endpoint: Optional[str] = None
    region: Optional[str] = None
    capabilities_json: Optional[str] = None


class RealtimeConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    api_key_id: Optional[str] = None
    endpoint: str
    region: str
    capabilities_json: str
    created_at: str


class VoiceTtsLinkRequest(BaseModel):
    tts_config_id: str


class VoiceOut(BaseModel):
    id: str
    name: str
    type: str
    created_at: str


class VoiceRuntimeBindingOut(BaseModel):
    """A binding summary safe for administrative API responses."""

    id: str
    voice_pool_id: str
    runtime_kind: str
    runtime_config_id: str
    runtime_config_name: str
    runtime_config_model: str
    created_at: str


class VoiceRuntimeBindingCreate(BaseModel):
    runtime_kind: str
    runtime_config_id: str
    provider_voice_id: str


class VoiceCreate(BaseModel):
    name: str


class VoiceManualCreate(BaseModel):
    name: str
    voice_id: str
    type: str = "cloned"
    tts_config_id: Optional[str] = None


class VoiceUpdate(BaseModel):
    name: Optional[str] = None
    audition_text: Optional[str] = None


class AuditionRequest(BaseModel):
    text: str
    tts_config_id: Optional[str] = None


class AuditionResponse(BaseModel):
    audio_base64: str
    mime_type: str


class SipBindRequest(BaseModel):
    phone_number: str


class SipStatusResponse(BaseModel):
    bound_number: Optional[str] = None
    trunk_id: Optional[str] = None
    status: str = "unbound"


class CallLogOut(BaseModel):
    id: str
    agent_id: str
    agent_alias: str
    caller_user_id: str
    caller_username: str
    room_name: str
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: str
    transcript: Optional[str] = None
    runtime_mode: str = "pipeline"
    provider: Optional[str] = None
    model: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None


class CallLogEndRequest(BaseModel):
    status: str = "completed"
    duration_seconds: int
    transcript: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None

    @field_validator("failure_stage")
    @classmethod
    def sanitize_failure_stage(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        sanitized = re.sub(r"[^a-z0-9_.-]+", "_", value.strip().lower())[:64]
        return sanitized or None

    @field_validator("failure_reason")
    @classmethod
    def sanitize_failure_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        sanitized = " ".join(value.split())[:256]
        sanitized = re.sub(r"(?i)bearer\s+[^\s]+", "Bearer [redacted]", sanitized)
        sanitized = re.sub(r"\bsk-[A-Za-z0-9_-]+\b", "[redacted]", sanitized)
        return sanitized or None


class CallLogListResponse(BaseModel):
    items: list[CallLogOut]
    total: int
    page: int
    page_size: int


class StatsOverview(BaseModel):
    total_calls: int
    today_calls: int
    total_duration_seconds: int
    active_users: int


class StatsTrendItem(BaseModel):
    date: str
    count: int


class StatsTopItem(BaseModel):
    id: str
    name: str
    count: int

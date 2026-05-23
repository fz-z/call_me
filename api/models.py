from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


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


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class AgentCreate(BaseModel):
    alias: str
    system_prompt: str = ""
    voice_pool_id: str


class AgentUpdate(BaseModel):
    alias: Optional[str] = None
    system_prompt: Optional[str] = None
    model_config_id: Optional[str] = None
    voice_pool_id: Optional[str] = None
    tts_config_id: Optional[str] = None


class AgentOut(BaseModel):
    id: str
    alias: str
    voice_id: str
    voice_pool_id: Optional[str] = None
    system_prompt: str
    owner_id: str
    source_agent_id: Optional[str] = None
    model_config_id: Optional[str] = None
    tts_config_id: Optional[str] = None
    created_at: str


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
    api_key: str
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
    api_key: Optional[str] = None
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


class TtsConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None


class TtsConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    created_at: str


class VoiceTtsLinkRequest(BaseModel):
    tts_config_id: str


class VoiceOut(BaseModel):
    id: str
    name: str
    voice_id: str
    type: str
    created_at: str


class VoiceCreate(BaseModel):
    name: str


class SipBindRequest(BaseModel):
    phone_number: str


class SipStatusResponse(BaseModel):
    bound_number: Optional[str] = None
    trunk_id: Optional[str] = None
    status: str = "unbound"

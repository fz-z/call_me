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


class AgentUpdate(BaseModel):
    alias: Optional[str] = None
    system_prompt: Optional[str] = None


class AgentOut(BaseModel):
    id: str
    alias: str
    voice_id: str
    system_prompt: str
    owner_id: str
    source_agent_id: Optional[str] = None
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


class SipBindRequest(BaseModel):
    phone_number: str


class SipStatusResponse(BaseModel):
    bound_number: Optional[str] = None
    trunk_id: Optional[str] = None
    status: str = "unbound"

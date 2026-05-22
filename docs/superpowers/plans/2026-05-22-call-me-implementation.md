# call_me Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a voice AI calling app where users create Agents (cloned voice + personality), admin controls access, and anyone with permission can call an agent via Flutter app. Deployable with `docker compose up -d`.

**Architecture:** Two Docker services (api + agent). api is a FastAPI server with SQLite handling auth, agent CRUD, permissions, and LiveKit token generation. agent is a LiveKit Agent Worker running the STT → LLM → TTS pipeline, reading agent config from participant attributes at call time. Flutter app for iOS/Android provides the UI.

**Tech Stack:** Python/FastAPI, SQLite (aiosqlite), LiveKit Agents, DashScope (STT/LLM/TTS/Voice Enrollment), Flutter, Docker Compose.

---

## Phase 1: Project Scaffolding

### Task 1: Root project setup

**Files:**
- Create: `api/pyproject.toml`
- Create: `agent/pyproject.toml`
- Create: `.env.example`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create api/pyproject.toml**

```toml
[project]
name = "call-me-api"
version = "1.0.0"
requires-python = ">=3.10, <3.14"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pyjwt>=2.9.0",
    "passlib[bcrypt]>=1.7.4",
    "aiohttp>=3.10.0",
    "aiosqlite>=0.20.0",
    "python-dotenv>=1.0.0",
    "python-multipart>=0.0.12",
    "livekit-api>=1.0.0",
]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Create agent/pyproject.toml**

```toml
[project]
name = "call-me-agent"
version = "1.0.0"
requires-python = ">=3.10, <3.14"
dependencies = [
    "livekit-agents[openai,silero,turn-detector]~=1.3",
    "livekit-plugins-noise-cancellation~=0.2",
    "dashscope>=1.25.6",
    "python-dotenv>=1.0.0",
    "aiohttp>=3.10.0",
]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 3: Create .env.example**

```
DASHSCOPE_API_KEY=sk-xxx
LIVEKIT_URL=wss://xxx.livekit.cloud
LIVEKIT_API_KEY=APIxxx
LIVEKIT_API_SECRET=xxx
QWEN_TTS_MODEL=qwen3-tts-vc-realtime-2026-01-15
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
JWT_SECRET=changeme
```

- [ ] **Step 4: Create docker-compose.yml**

```yaml
services:
  api:
    build: ./api
    ports: ["8000:8000"]
    env_file: .env
    volumes: ["api_data:/data"]

  agent:
    build: ./agent
    env_file: .env

volumes:
  api_data:
```

- [ ] **Step 5: Verify scaffolding**

```bash
cd /Users/zhangfuzhen/Projects/call_me && ls api/pyproject.toml agent/pyproject.toml .env.example docker-compose.yml
```

- [ ] **Step 6: Commit**

```bash
git add api/pyproject.toml agent/pyproject.toml .env.example docker-compose.yml
git commit -m "feat: project scaffolding with pyproject.toml and docker-compose"
```

---

## Phase 2: API — Database & Models

### Task 2: Database layer

**Files:**
- Create: `api/database.py`

- [ ] **Step 1: Write database.py**

```python
import os
import sqlite3
import uuid
from datetime import datetime, timezone

import aiosqlite
from passlib.context import CryptContext

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/call_me.db")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _ensure_dir():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)


def _sync_conn() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def get_db() -> aiosqlite.Connection:
    _ensure_dir()
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    """Called at startup. Creates tables and seeds admin account."""
    conn = _sync_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                alias TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                system_prompt TEXT NOT NULL DEFAULT '',
                owner_id TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS permissions (
                agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                granted_by TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                PRIMARY KEY (agent_id, user_id)
            );
        """)

        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin")
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (admin_username,)
        ).fetchone()
        if not existing:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), admin_username, pwd_context.hash(admin_password), "admin", now),
            )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 2: Verify init_db works**

```bash
cd /Users/zhangfuzhen/Projects/call_me && python3 -c "
import os, sys
os.environ['DATABASE_PATH'] = '/tmp/test_call_me.db'
sys.path.insert(0, 'api')
from database import init_db, _sync_conn
init_db()
c = _sync_conn()
print(dict(c.execute('SELECT * FROM users').fetchone()))
c.close()
"
```

- [ ] **Step 3: Commit**

```bash
git add api/database.py
git commit -m "feat: database layer with schema and admin seed"
```

### Task 3: Pydantic models

**Files:**
- Create: `api/models.py`

- [ ] **Step 1: Write models.py**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add api/models.py
git commit -m "feat: Pydantic models for API request/response"
```

---

## Phase 3: API — Auth

### Task 4: Auth routes (register, login, JWT middleware)

**Files:**
- Create: `api/auth.py`
- Create: `api/main.py`

- [ ] **Step 1: Write auth.py**

```python
import os
import uuid
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import get_db, pwd_context
from models import UserRegister, UserLogin, AuthResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()
JWT_SECRET = os.environ.get("JWT_SECRET", "changeme")
JWT_ALGORITHM = "HS256"


def create_token(user_id: str, username: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {"id": payload["sub"], "username": payload["username"], "role": payload["role"]}
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


@router.post("/register", response_model=AuthResponse)
async def register(body: UserRegister):
    db = await get_db()
    try:
        existing = await db.execute("SELECT id FROM users WHERE username = ?", (body.username,))
        if await existing.fetchone():
            raise HTTPException(status_code=400, detail="Username already taken")

        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, body.username, pwd_context.hash(body.password), "user", now),
        )
        await db.commit()

        token = create_token(user_id, body.username, "user")
        return AuthResponse(token=token, user=UserOut(id=user_id, username=body.username, role="user", created_at=now))
    finally:
        await db.close()


@router.post("/login", response_model=AuthResponse)
async def login(body: UserLogin):
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM users WHERE username = ?", (body.username,))
        user = await row.fetchone()
        if not user or not pwd_context.verify(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        token = create_token(user["id"], user["username"], user["role"])
        return AuthResponse(
            token=token,
            user=UserOut(id=user["id"], username=user["username"], role=user["role"], created_at=user["created_at"]),
        )
    finally:
        await db.close()
```

- [ ] **Step 2: Write main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from auth import router as auth_router
# future imports: agents, permissions, admin, call, sip

app = FastAPI(title="call_me API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.on_event("startup")
async def startup():
    init_db()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 3: Test auth endpoints**

```bash
cd api && pip install fastapi uvicorn pyjwt "passlib[bcrypt]" aiosqlite python-dotenv python-multipart
DATABASE_PATH=/tmp/test_call_me_auth.db ADMIN_USERNAME=admin ADMIN_PASSWORD=test JWT_SECRET=test uvicorn main:app --port 8001 &
sleep 2
# Test register
curl -s -X POST http://localhost:8001/api/auth/register -H "Content-Type: application/json" -d '{"username":"alice","password":"secret"}' | python3 -m json.tool
# Test login
curl -s -X POST http://localhost:8001/api/auth/login -H "Content-Type: application/json" -d '{"username":"alice","password":"secret"}' | python3 -m json.tool
kill %1
```

- [ ] **Step 4: Commit**

```bash
git add api/auth.py api/main.py
git commit -m "feat: auth routes with register, login, JWT"
```

---

## Phase 4: API — Agent CRUD

### Task 5: Agent endpoints (create, list, get, update, delete)

**Files:**
- Create: `api/agents.py`
- Modify: `api/main.py`

- [ ] **Step 1: Write agent creation helper (DashScope voice enrollment)**

Create `api/voice_enrollment.py`:

```python
import base64
import json
import os
import aiohttp


async def enroll_voice(audio_bytes: bytes, mime_type: str, api_key: str) -> str:
    """Upload audio to DashScope qwen-voice-enrollment, return voice_id."""
    b64 = base64.b64encode(audio_bytes).decode("utf-8")
    data_uri = f"data:{mime_type};base64,{b64}"

    payload = {
        "model": "qwen-voice-enrollment",
        "input": {
            "action": "create",
            "target_model": os.environ.get("QWEN_TTS_MODEL", "qwen3-tts-vc-realtime-2026-01-15"),
            "preferred_name": "voice",
            "audio": {"data": data_uri},
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    api_url = os.environ.get(
        "QWEN_VOICE_ENROLLMENT_API_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization",
    )

    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, headers=headers, json=payload) as resp:
            raw = await resp.read()
            if resp.status >= 400:
                snippet = raw[:2000].decode("utf-8", errors="replace")
                raise RuntimeError(f"Voice enrollment failed HTTP {resp.status}: {snippet}")
            obj = json.loads(raw.decode("utf-8"))
            return obj["output"]["voice"]
```

- [ ] **Step 2: Write agents.py**

```python
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database import get_db
from models import AgentOut, AgentCreate, AgentUpdate
from auth import get_current_user, require_admin
from voice_enrollment import enroll_voice

router = APIRouter(prefix="/api/agents", tags=["agents"])


async def _user_can_access(db, agent_id: str, user_id: str, role: str) -> bool:
    if role == "admin":
        return True
    row = await db.execute("SELECT owner_id FROM agents WHERE id = ?", (agent_id,))
    agent = await row.fetchone()
    if not agent:
        return False
    if agent["owner_id"] == user_id:
        return True
    perm = await db.execute(
        "SELECT 1 FROM permissions WHERE agent_id = ? AND user_id = ?", (agent_id, user_id)
    )
    return await perm.fetchone() is not None


@router.post("", response_model=AgentOut)
async def create_agent(
    alias: str = Form(...),
    system_prompt: str = Form(""),
    audio_file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="DASHSCOPE_API_KEY not configured")

    audio_bytes = await audio_file.read()
    content_type = audio_file.content_type or "audio/wav"

    try:
        voice_id = await enroll_voice(audio_bytes, content_type, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice enrollment failed: {e}")

    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, alias, voice_id, system_prompt, user["id"], now),
        )
        await db.commit()
        return AgentOut(
            id=agent_id, alias=alias, voice_id=voice_id,
            system_prompt=system_prompt, owner_id=user["id"], created_at=now,
        )
    finally:
        await db.close()


@router.get("", response_model=list[AgentOut])
async def list_agents(user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute(
            """SELECT a.* FROM agents a
               LEFT JOIN permissions p ON a.id = p.agent_id AND p.user_id = ?
               WHERE a.owner_id = ? OR p.user_id = ?
               ORDER BY a.created_at DESC""",
            (user["id"], user["id"], user["id"]),
        )
        agents = await rows.fetchall()
        return [AgentOut(**dict(r)) for r in agents]
    finally:
        await db.close()


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        if not await _user_can_access(db, agent_id, user["id"], user["role"]):
            raise HTTPException(status_code=404, detail="Agent not found")
        row = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return AgentOut(**dict(agent))
    finally:
        await db.close()


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, body: AgentUpdate, user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        if not await _user_can_access(db, agent_id, user["id"], user["role"]):
            raise HTTPException(status_code=404, detail="Agent not found")

        row = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent["owner_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only owner or admin can update")

        new_alias = body.alias if body.alias is not None else agent["alias"]
        new_prompt = body.system_prompt if body.system_prompt is not None else agent["system_prompt"]
        await db.execute(
            "UPDATE agents SET alias = ?, system_prompt = ? WHERE id = ?",
            (new_alias, new_prompt, agent_id),
        )
        await db.commit()
        return AgentOut(
            id=agent_id, alias=new_alias, voice_id=agent["voice_id"],
            system_prompt=new_prompt, owner_id=agent["owner_id"], created_at=agent["created_at"],
        )
    finally:
        await db.close()


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent["owner_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only owner or admin can delete")

        await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await db.commit()
    finally:
        await db.close()
    return None
```

- [ ] **Step 3: Update main.py to include agents router**

In `api/main.py`, add after the auth_router import and include:

```python
from agents import router as agents_router
# ...
app.include_router(agents_router)
```

- [ ] **Step 4: Commit**

```bash
git add api/voice_enrollment.py api/agents.py api/main.py
git commit -m "feat: agent CRUD with voice enrollment"
```

---

## Phase 5: API — Permissions & Admin

### Task 6: Permission and admin endpoints

**Files:**
- Create: `api/permissions.py`
- Create: `api/admin.py`
- Modify: `api/main.py`

- [ ] **Step 1: Write permissions.py**

```python
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import get_db
from models import PermissionOut, GrantRequest
from auth import get_current_user, require_admin

router = APIRouter(prefix="/api/agents", tags=["permissions"])


@router.post("/{agent_id}/grant", response_model=PermissionOut)
async def grant_permission(agent_id: str, body: GrantRequest, admin: dict = Depends(require_admin)):
    db = await get_db()
    try:
        user_row = await db.execute("SELECT id FROM users WHERE username = ?", (body.username,))
        user = await user_row.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        agent_row = await db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,))
        if not await agent_row.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

        existing = await db.execute(
            "SELECT 1 FROM permissions WHERE agent_id = ? AND user_id = ?",
            (agent_id, user["id"]),
        )
        if await existing.fetchone():
            raise HTTPException(status_code=409, detail="Permission already exists")

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO permissions (agent_id, user_id, granted_by, created_at) VALUES (?, ?, ?, ?)",
            (agent_id, user["id"], admin["id"], now),
        )
        await db.commit()
        return PermissionOut(agent_id=agent_id, user_id=user["id"], granted_by=admin["id"], created_at=now)
    finally:
        await db.close()


@router.delete("/{agent_id}/grant/{username}", status_code=204)
async def revoke_permission(agent_id: str, username: str, admin: dict = Depends(require_admin)):
    db = await get_db()
    try:
        user_row = await db.execute("SELECT id FROM users WHERE username = ?", (username,))
        user = await user_row.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        result = await db.execute(
            "DELETE FROM permissions WHERE agent_id = ? AND user_id = ?",
            (agent_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Permission not found")
        await db.commit()
    finally:
        await db.close()
    return None
```

- [ ] **Step 2: Write admin.py**

```python
from fastapi import APIRouter, Depends

from database import get_db
from models import UserOut, AgentOut
from auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
async def list_users(admin: dict = Depends(require_admin)):
    db = await get_db()
    try:
        rows = await db.execute("SELECT id, username, role, created_at FROM users ORDER BY created_at")
        users = await rows.fetchall()
        return [UserOut(**dict(r)) for r in users]
    finally:
        await db.close()


@router.get("/agents", response_model=list[AgentOut])
async def list_all_agents(admin: dict = Depends(require_admin)):
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM agents ORDER BY created_at DESC")
        agents = await rows.fetchall()
        return [AgentOut(**dict(r)) for r in agents]
    finally:
        await db.close()
```

- [ ] **Step 3: Update main.py to include new routers**

Add imports and router includes for `permissions` and `admin`.

- [ ] **Step 4: Commit**

```bash
git add api/permissions.py api/admin.py api/main.py
git commit -m "feat: permission grant/revoke and admin endpoints"
```

---

## Phase 6: API — Call Token & SIP

### Task 7: Call token and SIP endpoints

**Files:**
- Create: `api/call.py`
- Create: `api/sip.py`
- Modify: `api/main.py`

- [ ] **Step 1: Write call.py**

```python
import os
import uuid
import json

from fastapi import APIRouter, Depends, HTTPException
from livekit import api as lk_api

from database import get_db
from models import TokenRequest, TokenResponse
from auth import get_current_user

router = APIRouter(prefix="/api/call", tags=["call"])

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")


async def _user_can_access(db, agent_id: str, user_id: str, role: str) -> bool:
    if role == "admin":
        return True
    row = await db.execute("SELECT owner_id FROM agents WHERE id = ?", (agent_id,))
    agent = await row.fetchone()
    if not agent:
        return False
    if agent["owner_id"] == user_id:
        return True
    perm = await db.execute(
        "SELECT 1 FROM permissions WHERE agent_id = ? AND user_id = ?", (agent_id, user_id)
    )
    return await perm.fetchone() is not None


@router.post("/token", response_model=TokenResponse)
async def get_call_token(body: TokenRequest, user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        agent_row = await db.execute("SELECT * FROM agents WHERE id = ?", (body.agent_id,))
        agent = await agent_row.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        if not await _user_can_access(db, body.agent_id, user["id"], user["role"]):
            raise HTTPException(status_code=403, detail="No permission to use this agent")

        room_name = f"call_{uuid.uuid4().hex[:12]}"
        agent_config = json.dumps({
            "agent_id": agent["id"],
            "alias": agent["alias"],
            "system_prompt": agent["system_prompt"],
            "voice_id": agent["voice_id"],
        })

        token = lk_api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET) \
            .with_identity(f"user_{user['username']}") \
            .with_name(user["username"]) \
            .with_attributes({"agent_config": agent_config}) \
            .with_grants(lk_api.VideoGrants(room_join=True, room=room_name)) \
            .to_jwt()

        ws_url = LIVEKIT_URL.replace("https://", "wss://").replace("http://", "ws://")
        return TokenResponse(token=token, room_url=ws_url)
    finally:
        await db.close()
```

- [ ] **Step 2: Write sip.py**

```python
import os

from fastapi import APIRouter, Depends

from models import SipBindRequest, SipStatusResponse
from auth import require_admin

router = APIRouter(prefix="/api/sip", tags=["sip"])

# In-memory state for MVP
_sip_state = {"bound_number": None, "trunk_id": None}


@router.post("/bind", response_model=SipStatusResponse)
async def bind_sip(body: SipBindRequest, admin: dict = Depends(require_admin)):
    # For MVP, store the binding in memory.
    # Full implementation: call LiveKit Cloud SIP API to create a SIP trunk.
    _sip_state["bound_number"] = body.phone_number
    _sip_state["trunk_id"] = "trunk_mvp_placeholder"
    return SipStatusResponse(
        bound_number=body.phone_number,
        trunk_id=_sip_state["trunk_id"],
        status="bound",
    )


@router.get("/status", response_model=SipStatusResponse)
async def get_sip_status(admin: dict = Depends(require_admin)):
    return SipStatusResponse(
        bound_number=_sip_state["bound_number"],
        trunk_id=_sip_state["trunk_id"],
        status="bound" if _sip_state["bound_number"] else "unbound",
    )
```

- [ ] **Step 3: Update main.py to include call and sip routers**

```python
from call import router as call_router
from sip import router as sip_router
# ...
app.include_router(call_router)
app.include_router(sip_router)
```

- [ ] **Step 4: Commit**

```bash
git add api/call.py api/sip.py api/main.py
git commit -m "feat: call token generation and SIP binding endpoints"
```

---

## Phase 7: Agent Worker

### Task 8: Agent worker (voice AI pipeline)

**Files:**
- Create: `agent/qwen_tts.py` (copy from reference, modify voice_id handling)
- Create: `agent/qwen_asr_realtime_stt.py` (copy from reference)
- Create: `agent/agent.py`

- [ ] **Step 1: Copy qwen_tts.py from reference project**

```bash
cp /Users/zhangfuzhen/PycharmProjects/agent-starter-python/src/qwen_tts.py agent/qwen_tts.py
```

The QwenTTS class already accepts `voice_id` as a parameter — this is used for the cloned voice.

- [ ] **Step 2: Copy qwen_asr_realtime_stt.py from reference project**

```bash
cp /Users/zhangfuzhen/PycharmProjects/agent-starter-python/src/qwen_asr_realtime_stt.py agent/qwen_asr_realtime_stt.py
```

- [ ] **Step 3: Write agent/agent.py**

```python
import json
import logging
import os

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    ModelSettings,
    room_io,
)
from livekit.plugins import noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from qwen_asr_realtime_stt import QwenASRRealtimeSTT
from qwen_tts import QwenTTS

load_dotenv("/.env")  # Docker: .env mounted at root
logger = logging.getLogger("agent")


class CallMeAgent(Agent):
    def __init__(self, system_prompt: str) -> None:
        super().__init__(instructions=system_prompt)


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # Read agent config from the first participant's attributes
    agent_config_str = None
    for p in ctx.room.remote_participants.values():
        attrs = p.attributes
        if attrs and "agent_config" in attrs:
            agent_config_str = attrs["agent_config"]
            break

    if not agent_config_str:
        # Check local participant attributes
        attrs = ctx.room.local_participant.attributes
        if attrs and "agent_config" in attrs:
            agent_config_str = attrs["agent_config"]

    if not agent_config_str:
        logger.warning("No agent_config in participant attributes, using defaults")
        system_prompt = "你是一位贴心的语音智能助手。"
        voice_id = None
    else:
        config = json.loads(agent_config_str)
        system_prompt = config.get("system_prompt", "你是一位贴心的语音智能助手。")
        voice_id = config.get("voice_id")

    # LLM
    llm_provider = os.getenv("LLM_PROVIDER", "qwen").strip().lower()
    if llm_provider == "qwen":
        qwen_base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        llm = openai.LLM(
            model=os.getenv("QWEN_MODEL", "qwen3-max"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=qwen_base_url,
            temperature=0.7,
        )
    elif llm_provider == "deepseek":
        llm = openai.LLM.with_deepseek(model="deepseek-chat", temperature=0.7)
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {llm_provider}")

    # STT
    stt_provider = os.getenv("STT_PROVIDER", "livekit").strip().lower()
    if stt_provider == "qwen":
        stt = QwenASRRealtimeSTT.from_env()
    else:
        stt_model = os.getenv("STT_MODEL", "deepgram/nova-2").strip()
        stt_language = os.getenv("STT_LANGUAGE", "zh-CN").strip()
        from livekit.agents import inference
        stt = inference.STT(model=stt_model, language=stt_language)

    # TTS — pass voice_id if available for cloned voice
    tts_provider = os.getenv("TTS_PROVIDER", "qwen").strip().lower()
    if tts_provider == "qwen":
        tts_model = os.getenv("QWEN_TTS_MODEL", "qwen3-tts-vc-realtime-2026-01-15")
        tts = QwenTTS(
            api_url=os.getenv("QWEN_TTS_API_URL", "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"),
            api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            model=tts_model,
            voice_id=voice_id,
        )
    else:
        from livekit.agents import inference
        tts = inference.TTS(model=os.getenv("ELEVENLABS_TTS_MODEL", "elevenlabs/eleven_flash_v2_5"))

    logger.info("pipeline config", extra={
        "room": ctx.room.name,
        "agent_config": agent_config_str,
        "llm_provider": llm_provider,
        "tts_provider": tts_provider,
    })

    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    await session.start(
        agent=CallMeAgent(system_prompt=system_prompt),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
```

- [ ] **Step 4: Commit**

```bash
git add agent/
git commit -m "feat: agent worker with dynamic system_prompt and voice_id"
```

---

## Phase 8: Docker & Deployment

### Task 9: Dockerfiles

**Files:**
- Create: `api/Dockerfile`
- Create: `agent/Dockerfile`

- [ ] **Step 1: Write api/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY *.py .

RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write agent/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY *.py .

CMD ["python", "agent.py", "start"]
```

- [ ] **Step 3: Build and test**

```bash
cd /Users/zhangfuzhen/Projects/call_me
docker compose build
```

- [ ] **Step 4: Commit**

```bash
git add api/Dockerfile agent/Dockerfile
git commit -m "feat: Dockerfiles for api and agent"
```

---

## Phase 9: Flutter App

### Task 10: Flutter project setup and models

**Files:**
- Create: Flutter project via `flutter create`
- Create: `app/lib/models/agent.dart`
- Create: `app/lib/services/api_service.dart`

- [ ] **Step 1: Create Flutter project**

```bash
cd /Users/zhangfuzhen/Projects/call_me && flutter create app --org com.callme --platforms ios,android
```

- [ ] **Step 2: Add dependencies to pubspec.yaml**

In `app/pubspec.yaml`, add under dependencies:
```yaml
dependencies:
  flutter:
    sdk: flutter
  http: ^1.2.0
  shared_preferences: ^2.2.0
  livekit_client: ^2.0.0
  file_picker: ^8.0.0
  provider: ^6.1.0
```

Run `flutter pub get` in the app directory.

- [ ] **Step 3: Write models/agent.dart**

```dart
class Agent {
  final String id;
  final String alias;
  final String voiceId;
  final String systemPrompt;
  final String ownerId;
  final String createdAt;

  Agent({
    required this.id,
    required this.alias,
    required this.voiceId,
    required this.systemPrompt,
    required this.ownerId,
    required this.createdAt,
  });

  factory Agent.fromJson(Map<String, dynamic> json) {
    return Agent(
      id: json['id'],
      alias: json['alias'],
      voiceId: json['voice_id'],
      systemPrompt: json['system_prompt'],
      ownerId: json['owner_id'],
      createdAt: json['created_at'],
    );
  }
}

class User {
  final String id;
  final String username;
  final String role;
  final String createdAt;

  User({required this.id, required this.username, required this.role, required this.createdAt});

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      id: json['id'],
      username: json['username'],
      role: json['role'],
      createdAt: json['created_at'],
    );
  }
}
```

- [ ] **Step 4: Write services/api_service.dart**

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/agent.dart';

class ApiService {
  String? _baseUrl;
  String? _token;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _baseUrl = prefs.getString('server_url') ?? 'http://10.0.2.2:8000';
    _token = prefs.getString('token');
  }

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_token != null) 'Authorization': 'Bearer $_token',
  };

  void setBaseUrl(String url) => _baseUrl = url;
  String? get token => _token;

  // Auth
  Future<User> register(String username, String password) async {
    final r = await http.post(
      Uri.parse('$_baseUrl/api/auth/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}),
    );
    final data = jsonDecode(r.body);
    if (r.statusCode == 200) {
      await _saveToken(data['token']);
      return User.fromJson(data['user']);
    }
    throw Exception(data['detail'] ?? 'Register failed');
  }

  Future<User> login(String username, String password) async {
    final r = await http.post(
      Uri.parse('$_baseUrl/api/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}),
    );
    final data = jsonDecode(r.body);
    if (r.statusCode == 200) {
      await _saveToken(data['token']);
      return User.fromJson(data['user']);
    }
    throw Exception(data['detail'] ?? 'Login failed');
  }

  Future<void> _saveToken(String token) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('token', token);
  }

  // Agents
  Future<List<Agent>> listAgents() async {
    final r = await http.get(Uri.parse('$_baseUrl/api/agents'), headers: _headers);
    if (r.statusCode == 200) {
      final list = jsonDecode(r.body) as List;
      return list.map((e) => Agent.fromJson(e)).toList();
    }
    throw Exception('Failed to list agents');
  }

  Future<Agent> createAgent(String alias, String systemPrompt, String filePath) async {
    final uri = Uri.parse('$_baseUrl/api/agents');
    final request = http.MultipartRequest('POST', uri)
      ..headers['Authorization'] = 'Bearer $_token'
      ..fields['alias'] = alias
      ..fields['system_prompt'] = systemPrompt
      ..files.add(await http.MultipartFile.fromPath('audio_file', filePath));
    final streamed = await request.send();
    final r = await http.Response.fromStream(streamed);
    if (r.statusCode == 200) {
      return Agent.fromJson(jsonDecode(r.body));
    }
    throw Exception('Failed to create agent');
  }

  Future<void> deleteAgent(String id) async {
    final r = await http.delete(Uri.parse('$_baseUrl/api/agents/$id'), headers: _headers);
    if (r.statusCode != 204) throw Exception('Failed to delete agent');
  }

  // Call
  Future<Map<String, String>> getCallToken(String agentId) async {
    final r = await http.post(
      Uri.parse('$_baseUrl/api/call/token'),
      headers: _headers,
      body: jsonEncode({'agent_id': agentId}),
    );
    if (r.statusCode == 200) {
      final data = jsonDecode(r.body);
      return {'token': data['token'], 'room_url': data['room_url']};
    }
    throw Exception('Failed to get call token');
  }

  // Admin
  Future<List<Map<String, dynamic>>> listAllAgents() async {
    final r = await http.get(Uri.parse('$_baseUrl/api/admin/agents'), headers: _headers);
    if (r.statusCode == 200) {
      return (jsonDecode(r.body) as List).cast<Map<String, dynamic>>();
    }
    throw Exception('Failed to list all agents');
  }

  Future<void> grantPermission(String agentId, String username) async {
    final r = await http.post(
      Uri.parse('$_baseUrl/api/agents/$agentId/grant'),
      headers: _headers,
      body: jsonEncode({'username': username}),
    );
    if (r.statusCode != 200) throw Exception('Failed to grant permission');
  }

  Future<void> revokePermission(String agentId, String username) async {
    final r = await http.delete(
      Uri.parse('$_baseUrl/api/agents/$agentId/grant/$username'),
      headers: _headers,
    );
    if (r.statusCode != 204) throw Exception('Failed to revoke permission');
  }

  // Settings
  Future<void> logout() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
  }
}
```

- [ ] **Step 5: Commit**

```bash
git add app/
git commit -m "feat: Flutter project setup with models and API service"
```

### Task 11: Flutter — Login screen

**Files:**
- Create: `app/lib/screens/login_screen.dart`
- Modify: `app/lib/main.dart`

- [ ] **Step 1: Write login_screen.dart**

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import 'home_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _loading = false;
  String? _error;

  Future<void> _submit(bool isRegister) async {
    setState(() { _loading = true; _error = null; });
    try {
      final api = context.read<ApiService>();
      if (isRegister) {
        await api.register(_username.text.trim(), _password.text);
      } else {
        await api.login(_username.text.trim(), _password.text);
      }
      if (mounted) {
        Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const HomeScreen()));
      }
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.call, size: 64, color: Colors.blue),
              const SizedBox(height: 16),
              const Text('call_me', style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold)),
              const SizedBox(height: 32),
              TextField(controller: _username, decoration: const InputDecoration(labelText: 'Username')),
              const SizedBox(height: 12),
              TextField(controller: _password, obscureText: true, decoration: const InputDecoration(labelText: 'Password')),
              if (_error != null) Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(_error!, style: const TextStyle(color: Colors.red)),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _loading ? null : () => _submit(false),
                  child: const Text('Login'),
                ),
              ),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton(
                  onPressed: _loading ? null : () => _submit(true),
                  child: const Text('Register'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
```

- [ ] **Step 2: Write main.dart**

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'services/api_service.dart';
import 'screens/login_screen.dart';
import 'screens/home_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final api = ApiService();
  await api.init();

  runApp(
    ChangeNotifierProvider.value(value: api),
    const CallMeApp(),
  );
}

class CallMeApp extends StatelessWidget {
  const CallMeApp({super.key});

  @override
  Widget build(BuildContext context) {
    final api = context.read<ApiService>();
    final loggedIn = api.token != null;

    return MaterialApp(
      title: 'call_me',
      theme: ThemeData(primarySwatch: Colors.blue, useMaterial3: true),
      home: loggedIn ? const HomeScreen() : const LoginScreen(),
    );
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add app/lib/screens/login_screen.dart app/lib/main.dart
git commit -m "feat: Flutter login/register screen"
```

### Task 12: Flutter — Home, Call, and Agent screens (placeholder with key UI)

**Files:**
- Create: `app/lib/screens/home_screen.dart`
- Create: `app/lib/screens/call_screen.dart`
- Create: `app/lib/screens/agent_list_screen.dart`
- Create: `app/lib/screens/agent_create_screen.dart`
- Create: `app/lib/screens/settings_screen.dart`

- [ ] **Step 1: Write home_screen.dart**

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../models/agent.dart';
import 'call_screen.dart';
import 'agent_list_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<Agent> _agents = [];
  Agent? _selectedAgent;
  bool _loading = true;
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    _loadAgents();
  }

  Future<void> _loadAgents() async {
    final api = context.read<ApiService>();
    try {
      final agents = await api.listAgents();
      setState(() {
        _agents = agents;
        _loading = false;
        if (_selectedAgent == null && agents.isNotEmpty) _selectedAgent = agents.first;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  Future<void> _startCall() async {
    if (_selectedAgent == null) return;
    final api = context.read<ApiService>();
    try {
      final result = await api.getCallToken(_selectedAgent!.id);
      if (mounted) {
        Navigator.push(context, MaterialPageRoute(
          builder: (_) => CallScreen(
            agent: _selectedAgent!,
            token: result['token']!,
            roomUrl: result['room_url']!,
          ),
        ));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Call failed: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      _buildHome(),
      const AgentListScreen(),
      const SettingsScreen(),
    ];

    return Scaffold(
      appBar: AppBar(title: const Text('call_me')),
      body: screens[_currentIndex],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (i) => setState(() => _currentIndex = i),
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: 'Home'),
          BottomNavigationBarItem(icon: Icon(Icons.person), label: 'Agents'),
          BottomNavigationBarItem(icon: Icon(Icons.settings), label: 'Settings'),
        ],
      ),
    );
  }

  Widget _buildHome() {
    return Center(
      child: _loading
          ? const CircularProgressIndicator()
          : Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.smart_toy, size: 80, color: Colors.blue),
                  const SizedBox(height: 16),
                  if (_agents.isEmpty)
                    const Text('No agents available', style: TextStyle(fontSize: 16, color: Colors.grey))
                  else ...[
                    DropdownButton<Agent>(
                      value: _selectedAgent,
                      isExpanded: true,
                      items: _agents.map((a) => DropdownMenuItem(value: a, child: Text(a.alias))).toList(),
                      onChanged: (a) => setState(() => _selectedAgent = a),
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: ElevatedButton.icon(
                        onPressed: _startCall,
                        icon: const Icon(Icons.call, size: 28),
                        label: const Text('Start Call', style: TextStyle(fontSize: 18)),
                      ),
                    ),
                  ],
                ],
              ),
            ),
    );
  }
}
```

- [ ] **Step 2: Write call_screen.dart**

```dart
import 'package:flutter/material.dart';
import 'package:livekit_client/livekit_client.dart';
import '../models/agent.dart';

class CallScreen extends StatefulWidget {
  final Agent agent;
  final String token;
  final String roomUrl;

  const CallScreen({super.key, required this.agent, required this.token, required this.roomUrl});

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  Room? _room;
  bool _connected = false;
  final _duration = Stopwatch();

  @override
  void initState() {
    super.initState();
    _connect();
  }

  Future<void> _connect() async {
    final room = Room();
    room.addListener(() {
      if (mounted) setState(() => _connected = room.state == ConnectionState.connected);
    });
    try {
      await room.connect(widget.roomUrl, widget.token);
      _duration.start();
      setState(() => _room = room);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Connection failed: $e')));
        Navigator.pop(context);
      }
    }
  }

  Future<void> _hangup() async {
    await _room?.disconnect();
    _duration.stop();
    if (mounted) Navigator.pop(context);
  }

  @override
  void dispose() {
    _room?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(widget.agent.alias, style: const TextStyle(color: Colors.white, fontSize: 20)),
            const SizedBox(height: 24),
            const Icon(Icons.mic, size: 64, color: Colors.green),
            const SizedBox(height: 16),
            StreamBuilder(
              stream: Stream.periodic(const Duration(seconds: 1)),
              builder: (_, __) => Text(
                '${_duration.elapsed.inMinutes}:${(_duration.elapsed.inSeconds % 60).toString().padLeft(2, '0')}',
                style: const TextStyle(color: Colors.white70, fontSize: 24),
              ),
            ),
            const SizedBox(height: 48),
            FloatingActionButton(
              onPressed: _hangup,
              backgroundColor: Colors.red,
              child: const Icon(Icons.call_end, color: Colors.white, size: 32),
            ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 3: Write agent_list_screen.dart** (agents list with create/delete, admin grant)

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../models/agent.dart';
import 'agent_create_screen.dart';

class AgentListScreen extends StatefulWidget {
  const AgentListScreen({super.key});

  @override
  State<AgentListScreen> createState() => _AgentListScreenState();
}

class _AgentListScreenState extends State<AgentListScreen> {
  List<Agent> _agents = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final api = context.read<ApiService>();
    try {
      _agents = await api.listAgents();
    } catch (_) {}
    setState(() => _loading = false);
  }

  Future<void> _delete(String id) async {
    final api = context.read<ApiService>();
    await api.deleteAgent(id);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Agents')),
      floatingActionButton: FloatingActionButton(
        onPressed: () async {
          final created = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => const AgentCreateScreen()));
          if (created == true) _load();
        },
        child: const Icon(Icons.add),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _agents.isEmpty
              ? const Center(child: Text('No agents'))
              : ListView.builder(
                  itemCount: _agents.length,
                  itemBuilder: (_, i) {
                    final a = _agents[i];
                    return ListTile(
                      title: Text(a.alias),
                      subtitle: Text(a.systemPrompt, maxLines: 1, overflow: TextOverflow.ellipsis),
                      trailing: IconButton(icon: const Icon(Icons.delete_outline), onPressed: () => _delete(a.id)),
                    );
                  },
                ),
    );
  }
}
```

- [ ] **Step 4: Write agent_create_screen.dart**

```dart
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';

class AgentCreateScreen extends StatefulWidget {
  const AgentCreateScreen({super.key});

  @override
  State<AgentCreateScreen> createState() => _AgentCreateScreenState();
}

class _AgentCreateScreenState extends State<AgentCreateScreen> {
  final _alias = TextEditingController();
  final _systemPrompt = TextEditingController();
  String? _filePath;
  String? _fileName;
  bool _loading = false;

  Future<void> _pickFile() async {
    final result = await FilePicker.platform.pickFiles(type: FileType.audio);
    if (result != null && result.files.single.path != null) {
      setState(() {
        _filePath = result.files.single.path!;
        _fileName = result.files.single.name;
      });
    }
  }

  Future<void> _submit() async {
    if (_filePath == null || _alias.text.trim().isEmpty) return;
    setState(() => _loading = true);
    try {
      final api = context.read<ApiService>();
      await api.createAgent(_alias.text.trim(), _systemPrompt.text.trim(), _filePath!);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Agent created!')));
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed: $e')));
      }
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Create Agent')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            TextField(controller: _alias, decoration: const InputDecoration(labelText: 'Alias (name)')),
            const SizedBox(height: 12),
            TextField(controller: _systemPrompt, maxLines: 4, decoration: const InputDecoration(labelText: 'Personality / System Prompt')),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: _pickFile,
              icon: const Icon(Icons.audio_file),
              label: Text(_fileName ?? 'Pick audio file (wav/mp3/m4a)'),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _loading ? null : _submit,
                child: _loading ? const CircularProgressIndicator() : const Text('Create Agent'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 5: Write settings_screen.dart**

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/api_service.dart';
import 'login_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _serverUrl = TextEditingController();
  final _phoneNumber = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    _serverUrl.text = prefs.getString('server_url') ?? 'http://10.0.2.2:8000';
  }

  Future<void> _saveUrl() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_url', _serverUrl.text.trim());
    context.read<ApiService>().setBaseUrl(_serverUrl.text.trim());
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Server URL saved')));
  }

  Future<void> _logout() async {
    await context.read<ApiService>().logout();
    if (mounted) {
      Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LoginScreen()), (_) => false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Server URL', style: TextStyle(fontWeight: FontWeight.bold)),
          TextField(controller: _serverUrl, decoration: const InputDecoration(hintText: 'http://your-server:8000')),
          const SizedBox(height: 8),
          ElevatedButton(onPressed: _saveUrl, child: const Text('Save')),
          const Divider(height: 32),
          const Text('SIP Binding (Admin)', style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          TextField(controller: _phoneNumber, decoration: const InputDecoration(hintText: '+86 138xxxx8888')),
          const SizedBox(height: 8),
          ElevatedButton(onPressed: () {}, child: const Text('Bind')),
          const Spacer(),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(onPressed: _logout, child: const Text('Logout')),
          ),
        ],
      ),
    );
  }
}
```

- [ ] **Step 6: Commit**

```bash
git add app/lib/screens/
git commit -m "feat: Flutter screens — home, call, agent list, create, settings"
```

---

## Phase 10: Final Integration & Test

### Task 13: End-to-end smoke test

- [ ] **Step 1: Start services**

```bash
cd /Users/zhangfuzhen/Projects/call_me
cp .env.example .env
# Fill in actual keys in .env
docker compose up -d
```

- [ ] **Step 2: Test API health**

```bash
curl http://localhost:8000/api/health
```

- [ ] **Step 3: Test register → login → create agent → get token**

```bash
# Register
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/register -H "Content-Type: application/json" -d '{"username":"test","password":"test"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
echo "Token: $TOKEN"

# List agents (empty)
curl -s http://localhost:8000/api/agents -H "Authorization: Bearer $TOKEN"

# Create agent (requires a real audio file)
# curl -X POST http://localhost:8000/api/agents -H "Authorization: Bearer $TOKEN" -F "alias=TestAgent" -F "system_prompt=Be helpful" -F "audio_file=@sample.wav"
```

- [ ] **Step 4: Commit any fixes**

```bash
git add -A && git commit -m "chore: integration fixes from smoke test"
```

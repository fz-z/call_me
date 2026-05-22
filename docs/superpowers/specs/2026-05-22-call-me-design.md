# call_me Design Spec

## Overview

A voice AI calling app with voice cloning and agent personas. Each Agent = a cloned voice + a personality (system prompt). Users create agents, admins grant access, anyone with permission can call an agent. SIP phone number binding lets external callers reach an agent.

**End state of this spec cycle:** a working MVP deployable via `docker compose up -d` on a single server, with a Flutter mobile app for iOS and Android.

## Core Abstraction: Agent

An Agent is the fundamental unit of the system — a callable AI entity:

```
Agent {
  id: string
  alias: string               human-readable name, e.g. "温柔客服Cherry"
  voice_id: string            DashScope cloned voice ID
  system_prompt: string       personality / persona instructions for the LLM
  owner_id: string            user who created it
  created_at: datetime
}
```

A user selects an Agent and calls it. The Agent Worker dynamically injects the agent's `system_prompt` and `voice_id` into the voice AI pipeline. Different agents can share the same voice but have different personalities, or vice versa.

## Goals

- **Deploy with one command** — Docker Compose pulls up everything
- **Use with no friction** — open the Flutter app, log in, pick an agent, tap call
- **Voice cloning** — upload a short audio clip, get a cloned voice back
- **Agent personas** — each agent has its own voice + personality
- **Permission control** — owner has automatic access; admin grants access to others
- **SIP binding** — bind a real phone number so external callers reach an agent

## Non-goals (MVP)

- Contact lists and call history
- Multi-user concurrent calls to the same agent
- Push notifications
- Agent-to-agent handoffs

## User Roles

| Role | Capabilities |
|------|-------------|
| **admin** | Create agents, manage all agents, grant/revoke agent access to any user, bind SIP |
| **user** | Create agents (auto-owner), use owned agents, use agents granted by admin |

There is exactly one admin account, seeded on first deployment.

## Architecture

```
  ┌──────────────┐          ┌──────────────┐          ┌──────────────┐
  │  api (FastAPI)│          │ agent (Worker)│          │   SQLite     │
  │              │          │              │          │              │
  │ - 用户认证    │          │ - STT+LLM+TTS │          │ users        │
  │ - Agent CRUD │          │ - 动态注入     │          │ agents       │
  │ - 权限管理    │          │   system_prompt│         │ permissions  │
  │ - Token 生成  │          │   和 voice_id  │          │              │
  │ - SIP 管理   │          │              │          │              │
  └──────┬───────┘          └──────┬───────┘          └──────────────┘
         │                         │
         ▼                         ▼
   DashScope API             LiveKit Cloud
   (Voice Enrollment)        (WebRTC / SIP / Agent Dispatch)
```

- **api** — FastAPI. User auth, agent CRUD, permission management, LiveKit token generation, SIP binding. SQLite for persistence.
- **agent** — LiveKit Agent Worker. Registers with LiveKit Cloud. When dispatched to a room, reads agent config (system_prompt + voice_id) and runs the STT → LLM → TTS pipeline.
- **SQLite** — single file, lives in the api container (or a shared volume). Three tables: `users`, `agents`, `permissions`.

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Mobile app | Flutter | Single codebase for iOS + Android; LiveKit has Flutter components |
| Backend API | Python / FastAPI | Same ecosystem as agent-starter-python; reuse DashScope integration |
| Agent | Python / livekit-agents | Proven pipeline from reference project |
| Database | SQLite | Zero-setup persistence, sufficient for MVP |
| Deployment | Docker Compose | One-command deploy on any Linux server |
| External | LiveKit Cloud + DashScope | No self-hosted WebRTC or GPU infra needed |

## Database Schema

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',   -- 'admin' | 'user'
    created_at TEXT NOT NULL
);

CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    voice_id TEXT NOT NULL,
    system_prompt TEXT NOT NULL DEFAULT '',
    owner_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE permissions (
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    granted_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, user_id)
);
```

**Permission resolution:**
- Owner of an agent always has access (implicit, no permissions row needed)
- Admin can grant any agent to any user (creates a permissions row)
- A user's available agents = `agents WHERE owner_id = self UNION agents WHERE permissions.user_id = self`

## API Endpoints

All endpoints except register/login require JWT Bearer token. Admin-only endpoints check `role == 'admin'`.

```
Auth
POST  /api/auth/register         {username, password} → {token, user}
POST  /api/auth/login            {username, password} → {token, user}

Agents (authenticated users)
POST  /api/agents                multipart {audio_file, alias, system_prompt} → {agent}
GET   /api/agents                → [{agent}]  (user's accessible agents)
GET   /api/agents/{id}           → {agent}
PATCH /api/agents/{id}           {alias?, system_prompt?} → {agent}
DELETE /api/agents/{id}          → 204  (owner or admin only)

Permissions (admin only)
POST  /api/agents/{id}/grant     {username} → {permission}
DELETE /api/agents/{id}/grant/{username} → 204

Admin (admin only)
GET   /api/admin/users           → [{user}]
GET   /api/admin/agents          → [{agent}]  (all agents with owner info)

Call
POST  /api/call/token            {agent_id} → {token, room_url}

SIP (admin only)
POST  /api/sip/bind              {phone_number} → {trunk_id, status}
GET   /api/sip/status            → {bound_number, trunk_id, status}
```

## Flutter App Screens

### Screen 1: Login / Register

- Username + password fields
- Login and Register buttons
- On success → navigate to Home

### Screen 2: Home

- Agent picker (dropdown or list showing accessible agents)
- Current agent display: alias + owner tag (mine / shared)
- "Start Call" button (large, primary action)
- Bottom nav: Home | Agents | Settings

### Screen 3: Call

- Agent alias and voice name display
- Waveform animation while AI speaks
- Call duration timer
- Hangup button (red, prominent)
- Mute toggle

### Screen 4: Agent Management

- Tab: "My Agents" — list of agents user created
- Tab: "Shared with Me" — agents granted by admin
- "Create Agent" button → opens creation flow
- Each agent card: alias, system prompt preview, voice indicator
- Tap agent → detail view (edit alias/prompt, delete)
- Admin additionally sees "All Agents" tab with grant/revoke controls

### Agent Config Delivery

The agent worker needs `system_prompt` and `voice_id` to configure the pipeline. Rather than sharing the SQLite volume, agent config is embedded in the LiveKit room metadata at token generation time:

1. `POST /api/call/token` → api reads agent from SQLite → generates token with `{"agent_id": "...", "system_prompt": "...", "voice_id": "..."}` in the participant attributes
2. Agent worker joins room → reads participant attributes → configures LLM and TTS accordingly
3. No cross-container database access needed.

### Screen 5: Agent Creation

- Pick audio file from device (wav/mp3/m4a)
- Text field: alias (e.g. "温柔客服Cherry")
- Text area: system prompt / personality description
- Upload & create → returns to agent list

### Screen 6: Settings

- Server URL configuration
- SIP binding (admin only): phone number input, bind/unbind, status display
- Logout

## Agent Creation Flow

1. User taps "Create Agent" in agent management
2. Selects audio file from device (30s–5min, wav/mp3/m4a)
3. Enters alias and system prompt
4. App uploads to `POST /api/agents` (multipart: audio_file + alias + system_prompt)
5. API calls DashScope `qwen-voice-enrollment` → gets voice_id
6. API inserts agent row (with voice_id) into SQLite
7. API inserts implicit permission (owner access)
8. Returns agent object to app
9. Agent appears in user's agent list, ready to call

## Call Flow

1. User selects an agent and taps "Start Call"
2. App calls `POST /api/call/token` with `agent_id` (JWT auth)
3. API verifies user has permission to use this agent
4. API reads agent from SQLite, generates a LiveKit token with agent config embedded in participant attributes: `{agent_id, system_prompt, voice_id}`
5. App connects to LiveKit room using the token
6. LiveKit Cloud dispatches the agent worker to the room
7. Agent worker reads participant attributes, extracts system_prompt + voice_id
8. Agent worker configures LLM with system_prompt and TTS with voice_id
9. STT → LLM → TTS pipeline runs for the conversation
10. User hangs up → app disconnects → agent session ends

## SIP Flow (admin only)

1. Admin binds a phone number in Settings
2. API calls LiveKit Cloud SIP API, creates a SIP trunk pointing to the agent worker
3. LiveKit routes inbound calls to the agent worker
4. Agent worker answers with the default agent (or admin-configurable per SIP trunk)
5. External caller → SIP → LiveKit → agent answers

## Deployment

Single `docker-compose.yml` with two services:

```yaml
services:
  api:
    build: ./api
    ports: ["8000:8000"]
    env_file: .env
    volumes: ["api_data:/data"]    # SQLite file persists here

  agent:
    build: ./agent
    env_file: .env

volumes:
  api_data:
```

Agent worker does not need database access — agent config is embedded in the LiveKit token at call time.

User provides a `.env` file:

```
DASHSCOPE_API_KEY=sk-xxx
LIVEKIT_URL=wss://xxx.livekit.cloud
LIVEKIT_API_KEY=APIxxx
LIVEKIT_API_SECRET=xxx
QWEN_TTS_MODEL=qwen3-tts-vc-realtime-2026-01-15
ADMIN_USERNAME=admin
ADMIN_PASSWORD=xxx
JWT_SECRET=xxx
```

First launch seeds the admin account. Then `docker compose up -d` and it's running.

## Project Structure

```
call_me/
├── api/                    # FastAPI backend
│   ├── Dockerfile
│   ├── main.py            # App entrypoint, route registration
│   ├── auth.py            # Register, login, JWT
│   ├── agents.py          # Agent CRUD endpoints
│   ├── permissions.py     # Grant/revoke endpoints (admin)
│   ├── admin.py           # Admin dashboard endpoints
│   ├── call.py            # Token generation
│   ├── sip.py             # SIP binding endpoints
│   ├── models.py          # SQLAlchemy / Pydantic models
│   ├── database.py        # SQLite connection + seed
│   └── requirements.txt
├── agent/                  # LiveKit Agent Worker
│   ├── Dockerfile
│   ├── agent.py           # Voice AI pipeline (STT + LLM + TTS)
│   ├── qwen_tts.py        # Qwen TTS adapter (from reference project)
│   ├── qwen_asr.py        # Qwen ASR adapter (from reference project)
│   └── requirements.txt
├── app/                    # Flutter mobile app
│   └── (flutter project)
├── docker-compose.yml
├── .env.example
└── docs/
    └── superpowers/specs/2026-05-22-call-me-design.md
```

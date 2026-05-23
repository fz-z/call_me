# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

call_me is a voice AI calling app. Each **Agent** = a cloned voice + a personality (system prompt). Users create agents, admins grant access, users call agents via Flutter app. Backend is two Docker services (api + agent worker), deployed with Docker Compose. Uses LiveKit Cloud for real-time communication and DashScope (Alibaba Cloud) for STT/LLM/TTS/voice cloning.

## Key Commands

```bash
# Docker (recommended)
docker compose up -d              # Start both services
docker compose up -d --build agent  # Rebuild + restart agent
docker logs call_me-agent-1 --tail 30  # View agent logs

# Local development
cd api && pip install -e . && uvicorn main:app --reload
cd agent && pip install -e . && python agent.py console  # Terminal voice chat

# Run tests (31 tests)
cd api && python3 -m pytest tests/ -v

# Flutter
cd app && flutter pub get && flutter run -d chrome
```

## Architecture

```
Flutter App  →  api (FastAPI:8000)  →  LiveKit Cloud  ←  agent (Worker)
                    │    SQLite                           │  reads config from
                    │  users/agents/                      │  participant attrs
                    │  permissions                        │
                    ▼                                     ▼
              DashScope API                    DashScope (STT/LLM/TTS)
              (Voice Enrollment only)          + Deepgram (STT via LiveKit)
```

- **api** — Auth, Agent CRUD, voice enrollment, permissions, LiveKit token generation, SIP binding. SQLite for persistence. Agent config embedded in LiveKit token attributes.
- **agent** — LiveKit Agent Worker. Connects → polls for user participant → reads agent_config (system_prompt + voice_id) → runs STT→LLM→TTS pipeline.
- **No inter-service communication** — agent config is embedded in LiveKit token attributes at call time. Worker has no database access.

## Voice Pipeline

```
User speaks → STT (Deepgram via LiveKit) → text
text → LLM (Qwen via DashScope OpenAI-compatible API) → response text
response text → TTS (Qwen WebSocket streaming) → audio → User hears
```

TTS uses `qwen3-tts-vc-realtime` model via WebSocket for low-latency streaming. Built-in voices (Cherry) and cloned voice IDs both work.

## Data Model

SQLite in Docker volume `api_data`: `/data/call_me.db`

```sql
users (id, username, password_hash, role, created_at)
agents (id, alias, voice_id, system_prompt, owner_id, created_at)
permissions (agent_id, user_id, granted_by, created_at)
```

Admin seeded from `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars. Seed agent created from `SEED_AGENT_*` vars if configured.

## Permission Model

- Owner has automatic access to their agents
- Admin (`role == "admin"`) can grant any agent to any user
- A user's accessible agents = owned agents UNION granted agents

## File Organization

```
api/              FastAPI backend (16 endpoints, 31 tests)
  main.py         App entry, all router mounting, CORS, health check
  auth.py         Register, login, JWT, get_current_user, require_admin
  agents.py       Agent CRUD (POST multipart, GET/PATCH/DELETE)
  permissions.py  Grant/revoke access (admin only)
  admin.py        List users, list all agents (admin only)
  call.py         Generate LiveKit token with agent_config in attributes
  sip.py          SIP phone binding (MVP in-memory)
  voice_enrollment.py  DashScope qwen-voice-enrollment HTTP API
  database.py     SQLite schema, init_db(), admin seed, agent seed
  models.py       Pydantic request/response schemas
  tests/          4 test files, 31 unit tests

agent/            LiveKit Agent Worker
  agent.py        Main pipeline: connect→poll agent_config→STT→LLM→TTS
  qwen_tts.py     Qwen TTS adapter (WebSocket realtime + HTTP fallback)
  qwen_asr_realtime_stt.py  Qwen ASR adapter (WebSocket realtime)
  simple_qwen_tts.py  Simplified HTTP-only TTS (non-streaming, backup)

app/              Flutter mobile app (6 screens)
  lib/main.dart
  lib/models/agent.dart         VoiceAgent + User models
  lib/services/api_service.dart REST client (auth, agents, call, admin)
  lib/screens/
    login_screen.dart           Register/Login
    home_screen.dart            Agent dropdown + call button + bottom nav
    call_screen.dart            LiveKit WebRTC + mic publishing + hangup
    agent_list_screen.dart      List/create/delete agents + admin shield icon
    agent_detail_screen.dart    Edit alias + system_prompt
    agent_create_screen.dart    Upload audio + set alias + system_prompt
    admin_screen.dart           All agents + grant/revoke + user list
    settings_screen.dart        Server URL + SIP binding + logout
```

## Key Integration Points

- **Agent config delivery**: `api/call.py` embeds `{agent_id, alias, system_prompt, voice_id}` in LiveKit token participant attributes. `agent/agent.py` polls remote participants for these after connecting.
- **Call flow**: Flutter `call_screen.dart` publishes local mic via `LocalAudioTrack.create()` → connects to LiveKit room → Agent dispatched → config read → pipeline runs.
- **Voice enrollment**: `api/agents.py` POST handler calls `voice_enrollment.enroll_voice()` → DashScope → returns voice_id → inserts agent row.
- **TTS voice_id vs voice**: QwenTTS passes `voice_id` param to DashScope. Built-in voices (Cherry) and cloned IDs both work as the "voice" parameter in the API call.

## Known Issues

- Flutter Web (Chrome): `livekit_client` WebRTC may have audio issues vs native mobile. Test with `flutter run` on simulator/device for full functionality.
- `@app.on_event("startup")` is deprecated FastAPI API — should migrate to lifespan handlers.
- `preemptive_generation` and `turn_detection` deprecated in LiveKit Agents v1.5 — should migrate to `turn_handling=TurnHandlingOptions(...)`.
- SIP binding is MVP placeholder (in-memory state, no actual trunk creation).

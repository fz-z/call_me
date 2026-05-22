# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

call_me is a voice AI calling app. Users create **Agents** (cloned voice + personality/system prompt), admins grant access, users call agents via Flutter app. Backend is two Docker services (api + agent worker), deployed with Docker Compose. Uses LiveKit Cloud for real-time communication and DashScope (Alibaba Cloud) for STT/LLM/TTS/voice cloning.

## Key Commands

```bash
# Install API deps and run
cd api && pip install -e . && uvicorn main:app --reload

# Run tests (31 tests)
cd api && python3 -m pytest tests/ -v

# Type checking
cd api && ruff check .

# Docker Compose (production)
docker compose up -d

# Full pipeline test (requires .env with real keys)
cd api && uvicorn main:app --port 8000 &
curl -X POST http://localhost:8000/api/auth/register -H "Content-Type: application/json" -d '{"username":"test","password":"test"}'
```

## Architecture

```
Flutter App  →  api (FastAPI)  →  LiveKit Cloud  ←  agent (Worker)
                    │                                    │
                    ▼                                    ▼
              SQLite (users/      DashScope (STT/LLM/TTS/Voice Enrollment)
              agents/permissions)
```

- **api** — Auth, Agent CRUD, voice enrollment, permissions, LiveKit token generation, SIP binding. Uses SQLite.
- **agent** — LiveKit Agent Worker running STT → LLM → TTS pipeline. Reads system_prompt + voice_id from participant attributes at call time.
- **No inter-service communication** — agent config is embedded in LiveKit token attributes at call time. Worker has no database access.

## Core Abstraction

**Agent** = cloned voice (voice_id from DashScope) + personality (system_prompt for LLM). Users select an agent, tap call, the agent answers with its specific voice and persona.

## Permission Model

- Owner has automatic access to their agents
- Admin (`role == "admin"`) can grant any agent to any user via `POST /api/agents/{id}/grant`
- A user's accessible agents = owned agents + granted agents
- Exactly one admin account, seeded on first deployment from `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars

## File Organization

```
api/              FastAPI backend (16 endpoints, 31 tests)
  main.py         App entry, router mounting, CORS, health check
  auth.py         Register, login, JWT Bearer, require_admin dependency
  agents.py       Agent CRUD (create with file upload, list/get/update/delete)
  permissions.py  Grant/revoke access (admin only)
  admin.py        List users, list all agents (admin only)
  call.py         Generate LiveKit token with agent_config in attributes
  sip.py          SIP phone number binding (MVP placeholder)
  voice_enrollment.py  DashScope qwen-voice-enrollment API
  database.py     SQLite schema (users/agents/permissions), admin seed
  models.py       Pydantic request/response models
  tests/          4 test files, 31 unit tests

agent/            LiveKit Agent Worker
  agent.py        Main pipeline (STT+LLM+TTS), reads agent_config from participant attrs
  qwen_tts.py     Qwen TTS adapter (supports voice cloning via voice_id)
  qwen_asr_realtime_stt.py  Qwen ASR realtime adapter

app/              Flutter mobile app
  lib/main.dart
  lib/models/agent.dart
  lib/services/api_service.dart
  lib/screens/    login, home, call, agent_list, agent_create, settings
```

## Required Environment Variables

```
DASHSCOPE_API_KEY    DashScope API key (Alibaba Cloud)
LIVEKIT_URL          LiveKit server URL (wss://...livekit.cloud)
LIVEKIT_API_KEY      LiveKit API key
LIVEKIT_API_SECRET   LiveKit API secret
QWEN_TTS_MODEL       TTS model (default: qwen3-tts-vc-realtime-2026-01-15)
ADMIN_USERNAME       Admin username (default: admin)
ADMIN_PASSWORD       Admin password (default: admin)
JWT_SECRET           JWT signing secret (default: changeme)
```

## Notes

- Voice enrollment expects audio files (wav/mp3/m4a, 30s–5min)
- Agent system_prompt can be any Chinese or English text — this becomes the LLM's persona
- STT/LLM/TTS providers are configurable via env vars: `LLM_PROVIDER`, `STT_PROVIDER`, `TTS_PROVIDER`
- SIP binding uses in-memory state for MVP (no actual trunk creation)
- `@app.on_event("startup")` is deprecated FastAPI API — should migrate to lifespan handlers

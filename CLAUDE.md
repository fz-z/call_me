# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

call_me is a voice AI calling app. Users call AI Agents (cloned voice + personality). Web admin manages agents and permissions. Two Docker services (api + agent). Uses LiveKit Cloud for realtime communication and DashScope for STT/LLM/TTS/voice cloning.

## Key Commands

```bash
# Full deploy
docker compose up -d

# Rebuild specific service
docker compose up -d --build agent

# View logs
docker logs call_me-agent-1 --tail 30

# Run API tests (31 tests)
cd api && python3 -m pytest tests/ -v

# Local API dev
cd api && uvicorn main:app --reload

# Vue admin dev
cd web-admin && npm run dev

# Vue admin build (for production)
cd web-admin && npm run build && docker compose up -d api

# Flutter
cd app && flutter run -d chrome
```

## Architecture

```
Flutter App ──LiveKit Cloud── Agent Worker (STT+LLM+TTS)
     │                              │ reads agent_config
     │                              │ from participant attrs
     ▼                              ▼
  api (FastAPI) ──────────── DashScope API
     │
     ├── SQLite (users/agents/permissions)
     └── Serves web-admin static files at /admin/
```

- **api**: Auth, Agent CRUD, permissions, LiveKit token with embedded agent_config, SIP. SQLite persistence. Serves Vue admin.
- **agent**: LiveKit Agent Worker. Connects to room → polls remote_participants for agent_config → STT→LLM→TTS pipeline. No DB access.
- **web-admin**: Vue 3 SPA, served from api container. Agent list, user list, grant/revoke, delete user.

## Core Concepts

**Agent** = voice_id (DashScope cloned voice or built-in like Cherry) + system_prompt (LLM personality).

**Root Agent vs Copy**: root agents have `source_agent_id IS NULL`. Copies have `source_agent_id` pointing to root. Grant creates a copy owned by the target user. Each user edits their own copy's system_prompt independently.

**Agent Config Delivery**: `api/call.py` embeds `{agent_id, alias, system_prompt, voice_id}` in LiveKit token participant attributes. `agent/agent.py` reads from remote participants after connect.

## Permission Model

- Owner has automatic access to their agents (root or copy)
- Admin grants an agent → creates independent copy for target user
- Revoke deletes the user's copy

## File Map

```
api/              FastAPI (16 endpoints, 31 tests)
  main.py         Entry, router mounting, CORS, static /admin/ mount
  auth.py         Register, login, JWT, get_current_user, require_admin
  agents.py       Agent CRUD, list by owner/role
  permissions.py  Grant (create copy), revoke (delete copy)
  admin.py        Root agents, copies, users CRUD, delete user
  call.py         LiveKit token with agent_config in attrs
  sip.py          SIP binding (MVP placeholder)
  voice_enrollment.py  DashScope voice enrollment HTTP
  database.py     SQLite schema + migration + admin/agent seed
  models.py       Pydantic schemas (AgentOut includes source_agent_id)

agent/            LiveKit Agent Worker
  agent.py        TurnHandlingOptions + STT/LLM/TTS pipeline
  qwen_tts.py     Qwen TTS (WebSocket realtime + HTTP fallback)
  qwen_asr_realtime_stt.py  Qwen ASR WebSocket
  simple_qwen_tts.py  HTTP-only TTS (backup)

web-admin/        Vue 3 Admin Panel
  src/api.js      Axios client with JWT interceptor
  src/router.js   Hash-mode routes (/login, /agents, /users)
  src/views/      LoginView, AgentListView, AgentDetailView,
                  UserListView, UserDetailView
  src/components/ AgentForm.vue, GrantDialog.vue (searchable dropdown)

app/              Flutter App (call-only, admin removed)
  lib/screens/    login, home, call, agent_list, agent_detail, settings
  lib/services/   api_service.dart (no admin methods)
```

## Key Details

- TTS default is `qwen3-tts-vc-realtime` via WebSocket streaming (low latency)
- Turn detection uses `TurnHandlingOptions` (not deprecated `turn_detection` param)
- Username validated on register/login (strip, min 2 chars, not empty)
- Vue admin assets must be built with `base: '/admin/'` in vite.config.js
- Docker volume `./web-admin/dist:/app/static` serves the admin frontend
- `.env` is gitignored; `.env.example` is the template

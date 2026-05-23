# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

call_me is a voice AI calling app. Users call AI Agents (cloned voice + personality). Web admin manages agents, users, permissions, and config pools. Two Docker services (api + agent). Uses LiveKit Cloud for realtime and DashScope for STT/LLM/TTS/voice cloning.

## Key Commands

```bash
# Deploy
docker compose up -d

# Rebuild specific service
docker compose up -d --build agent

# View logs
docker logs call_me-agent-1 --tail 30

# API tests (31 tests)
cd api && python3 -m pytest tests/ -v

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
     │                              │ reads {system_prompt,
     │                              │  voice_id, model_config,
     │                              │  tts_config} from token attrs
     ▼                              ▼
  api (FastAPI:8000) ──────── DashScope API
     │  SQLite
     │  users/agents/permissions
     │  model_configs/tts_configs/api_keys/voices/voice_tts_links
     └── serves web-admin static at /admin/
```

## Config Architecture

**First-run seeding**: `.env` values (API keys, voice names, TTS models) initialize DB config pools. After that, .env changes don't affect behavior — all config is managed via Web Admin.

**Token delivery**: `api/call.py` always embeds `model_config` and `tts_config` in the LiveKit token. If agent has no config set, it auto-embeds the first available config from DB. Agent worker only uses `.env` as emergency fallback when DB is completely empty.

## Config Pools

All admin-managed via Web Admin. Agents reference configs by ID; null/empty = auto-use DB default.

| Pool | Table | FK on agents |
|------|-------|-------------|
| API Keys | api_keys | (via model_configs/tts_configs) |
| LLM Models | model_configs | model_config_id |
| TTS Models | tts_configs | tts_config_id |
| Voices | voices + voice_tts_links | voice_pool_id |

**Voice-TTS links** are many-to-many. Agent creation and pipeline edit both cascade: pick TTS → filter compatible voices → pick voice → pick LLM → write persona.

## Agent Config Delivery

`api/call.py` embeds full pipeline config in LiveKit token (always resolves to a real config, never null):

```json
{
  "agent_id": "...", "alias": "...", "system_prompt": "...",
  "voice_id": "Cherry",
  "model_config": {"provider":"qwen","model":"qwen-plus","api_key":"sk-xxx",...},
  "tts_config": {"provider":"qwen","model":"qwen3-tts-flash-realtime","api_key":"sk-xxx"}
}
```

Worker reads → dynamically configures LLM + TTS.

## File Map

```
api/
  main.py              Entry, all routers, CORS, /admin static mount
  auth.py              Register, login, JWT, get_current_user, require_admin
  agents.py            Agent CRUD (JSON body, no audio upload)
  permissions.py       Grant (create copy), revoke (delete copy)
  admin.py             Root agents, copies, users, per-user agents
  call.py              LiveKit token with embedded agent/model/tts config (auto-resolves defaults)
  model_configs.py     LLM model pool CRUD (api_key_id FK)
  tts_configs.py       TTS model pool CRUD (api_key_id FK)
  api_keys.py          API Key pool CRUD
  voices.py            Voice pool CRUD + voice-TTS link management
  voice_enrollment.py  DashScope voice enrollment HTTP
  database.py          All migrations + first-run-only seeds
  models.py            Pydantic schemas for all entities

agent/
  agent.py             TurnHandlingOptions + dynamic LLM/TTS from token + speak-first greeting
  qwen_tts.py          Qwen TTS (WebSocket realtime + HTTP fallback)
  qwen_asr_realtime_stt.py  Qwen ASR WebSocket

web-admin/src/
  views/               LoginView, AgentListView, AgentDetailView,
                       UserListView, UserDetailView, ModelConfigListView,
                       TtsConfigListView, VoicePoolView, ApiKeyListView
  components/          AgentForm (4-step wizard), ModelConfigForm,
                       GrantDialog, ModelConfigForm, AgentForm
```

## Key Details

- First startup seeds from .env; subsequent restarts don't overwrite DB configs.
- Admin can edit agent pipeline config (voice, LLM, TTS) directly from Agent detail page.
- Admin can edit any user's agent system prompt from Agent detail and User detail pages.
- Agent speaks first on call connect (LLM-generated greeting).
- STT default: `livekit` (Deepgram via LiveKit Cloud). Global config, not per-agent.
- Turn detection uses `TurnHandlingOptions` API.
- Agent creation is JSON body (no multipart). `voice_pool_id` is required.
- FK validation on create_agent: voice_pool_id, tts_config_id, model_config_id checked before INSERT.
- `.env` is gitignored; `.env.example` is template with all configurable defaults documented.

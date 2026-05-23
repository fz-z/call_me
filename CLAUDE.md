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

## Config Pools

Three admin-managed pools. Agents can optionally reference entries. If null, falls back to `.env`.

| Pool | Table | FK on agents |
|------|-------|-------------|
| API Keys | api_keys | (via model_configs/tts_configs) |
| LLM Models | model_configs | model_config_id |
| TTS Models | tts_configs | tts_config_id |
| Voices | voices + voice_tts_links | voice_pool_id |

**Voice-TTS links** are many-to-many. Agent creation wizard cascades: pick TTS → filter compatible voices → pick voice → pick LLM → write persona.

## Agent Config Delivery

`api/call.py` embeds full pipeline config in LiveKit token:

```json
{
  "agent_id": "...", "alias": "...", "system_prompt": "...",
  "voice_id": "Cherry",
  "model_config": {"provider":"qwen","model":"qwen3-max","api_key":"sk-xxx",...},
  "tts_config": {"provider":"qwen","model":"qwen3-tts-flash-realtime","api_key":"sk-xxx"}
}
```

Worker reads → dynamically configures LLM + TTS. Falls back to `.env` if null.

## File Map

```
api/
  main.py              Entry, all routers, CORS, /admin static mount
  auth.py              Register, login, JWT, get_current_user, require_admin
  agents.py            Agent CRUD (JSON body, no audio upload)
  permissions.py       Grant (create copy), revoke (delete copy)
  admin.py             Root agents, copies, users, per-user agents
  call.py              LiveKit token with embedded agent/model/tts config
  model_configs.py     LLM model pool CRUD (api_key_id FK)
  tts_configs.py       TTS model pool CRUD (api_key_id FK)
  api_keys.py          API Key pool CRUD
  voices.py            Voice pool CRUD + voice-TTS link management
  voice_enrollment.py  DashScope voice enrollment HTTP
  database.py          All migrations + seeds
  models.py            Pydantic schemas for all entities

agent/
  agent.py             TurnHandlingOptions + dynamic LLM/TTS from token
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

- TTS default: `qwen3-tts-flash-realtime` (WebSocket streaming). VC model for cloned voices.
- STT default: `livekit` (Deepgram via LiveKit Cloud).
- Turn detection uses `TurnHandlingOptions` API.
- Agent creation is JSON body (no multipart). `voice_pool_id` is required.
- FK validation on create_agent: voice_pool_id, tts_config_id, model_config_id checked before INSERT.
- `.env` is gitignored; `.env.example` is template.
- API keys auto-seeded from `DASHSCOPE_API_KEY` and `DEEPSEEK_API_KEY`.
- TTS configs auto-seeded: 通义通用TTS + 通义VC, with voice links.

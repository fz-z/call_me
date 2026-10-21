# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

call_me is a voice AI calling app. Users call AI Agents (cloned voice + personality). Web admin manages agents, users, permissions, and configuration pools. The API and Agent Worker are deployed as two Docker services and connect to a LiveKit Server. Agents are either classic STT → LLM → TTS pipelines or full-duplex Qwen realtime sessions.

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
Flutter App ──LiveKit Server── Agent Worker (pipeline or realtime adapter)
     │                              │ reads token metadata, then fetches
     │                              │ Worker-private runtime configuration
     ▼                              ▼
  api (FastAPI:8000) ──────── DashScope API
     │  SQLite (/data/call_me.db)
     │  users/agents/permissions/call_logs
     │  model_configs/tts_configs/realtime_configs/api_keys
     │  voices/voice_tts_links/voice_runtime_bindings
     │  /data/photos (agent photo uploads)
     │
     ├── /admin/ (web-admin static)
     ├── /app/   (flutter web build)
     └── /photos/ (uploaded agent photos)

Production: nginx :443 → FastAPI :8000
```

## Config Architecture

**First-run seeding**: `.env` values (API keys, voice names, TTS models) initialize DB config pools. After that, .env changes don't affect behavior — all config is managed via Web Admin.

**Token delivery and secret boundary**: `api/call.py` embeds only `agent_id`, `runtime_mode`, and `call_log_id` in the LiveKit token. The Agent Worker calls `/api/internal/worker/agent-runtime/{agent_id}` with `X-Worker-Secret` to retrieve API keys, exact provider voice bindings, and runtime settings. Never add API keys, provider voice IDs, or full configurations to a token, mobile DTO, external API response, or log.

## Config Pools

All admin-managed via Web Admin. Agents reference configs by ID; null/empty = auto-use DB default.

| Pool | Table | FK on agents |
|------|-------|-------------|
| API Keys | api_keys | (via model_configs/tts_configs) |
| LLM Models | model_configs | model_config_id |
| TTS Models | tts_configs | tts_config_id |
| Voices | voices + voice_tts_links | voice_pool_id |
| Realtime Models | realtime_configs | realtime_config_id |
| Runtime Voice Bindings | voice_runtime_bindings | exact voice/config pair |

**Voice-TTS links** are many-to-many. Pipeline Agent creation cascades: pick TTS → filter compatible voices → pick voice → pick LLM → write persona. Realtime Agent creation selects a Qwen realtime configuration and only voices with an exact `voice_runtime_bindings` entry. It must not fall back to another model or a pipeline configuration.

## Agent Config Delivery

`api/call.py` embeds this non-secret dispatch metadata in the LiveKit token:

```json
{
  "agent_id": "...",
  "runtime_mode": "pipeline",
  "call_log_id": "..."
}
```

Worker fetches its private runtime before dispatch. A `pipeline` Agent preserves dynamic LLM/TTS setup. A `realtime` Agent builds a provider adapter (currently Qwen `qwen-audio-3.1-realtime-plus`) and bridges LiveKit PCM to the provider. Unknown or incomplete realtime runtime fails safely; it never falls back to pipeline.

LiveKit automatic dispatch does not populate `job.metadata` from participant attributes. The Worker tries job metadata first, then connects and reads the caller's `agent_config` participant attribute, which is the current API token contract. Keep both paths when changing dispatch.

## Operating realtime Agents

1. Add/select a Qwen API Key, then create a Realtime Config in Web Admin with the fixed first-release model `qwen-audio-3.1-realtime-plus`.
2. Fill **endpoint** with the appropriate Qwen `wss://` endpoint for the desired region and use **region** as the matching deployment-region label. These are per-record `realtime_configs` fields, not `.env` variables; the Worker appends the configured model query parameter.
3. In the voice library, upload reference audio for the selected realtime configuration and require the administrator to confirm authorization for voice cloning. This creates a model-specific binding; do not reveal or reuse its provider voice ID.
4. Create/update the Agent in `realtime` mode only after that exact binding exists. Verify with a non-production call before rollout.

The Flutter app may display the mode and provider read-only but must not offer mode selection. For a rejected realtime call token it displays `该 Agent 的实时语音服务暂不可用`; other connection failures use the generic connection message.

## File Map

```
api/
  main.py              Entry, all routers, CORS, /admin static mount
  auth.py              Register, login, JWT, get_current_user, require_admin
  agents.py            Agent CRUD (JSON body, no audio upload)
  permissions.py       Grant (create copy), revoke (delete copy)
  admin.py             Root agents, copies, users, per-user agents
  call.py              Metadata-only LiveKit token, call-log initialization
  model_configs.py     LLM model pool CRUD (api_key_id FK)
  tts_configs.py       TTS model pool CRUD (api_key_id FK)
  api_keys.py          API Key pool CRUD
  realtime_configs.py  Realtime model CRUD (first release: Qwen only)
  runtime_bindings.py  Exact model-specific voice-binding lookup
  voices.py            Voice pool CRUD + classic/realtime binding management
  voice_enrollment.py  DashScope voice enrollment HTTP
  database.py          All migrations + first-run-only seeds
  models.py            Pydantic schemas for all entities

agent/
  agent.py             Metadata dispatch + private runtime fetch + pipeline/realtime runners
  realtime/            Provider-neutral bridge/contracts plus Qwen WebSocket adapter
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
- Admin can edit a pipeline Agent (voice, LLM, TTS) or a realtime Agent (realtime config + exact voice binding) directly from Agent detail.
- Admin can edit any user's agent system prompt from Agent detail and User detail pages.
- Agent speaks first on call connect (LLM-generated greeting).
- STT default: `livekit` (Deepgram via LiveKit Cloud). Global config, not per-agent.
- Qwen Audio TTS models (`qwen-audio-*-tts-*`) use the workspace-scoped `SpeechSynthesizer` HTTP API. Both API and Agent Worker need `DASHSCOPE_WORKSPACE` or `QWEN_AUDIO_TTS_API_URL` in the same region as the API key. Provider voice IDs are model-specific and cannot be reused across models.
- Per-Agent `speech_rate` (0.5–2.0, default 1.0) controls speaking speed from the Agent page: pipeline passes `input.rate` to Qwen Audio TTS; realtime passes `session.speech_rate`.
- Turn detection uses `TurnHandlingOptions` API.
- Agent creation is JSON body (no multipart). `voice_pool_id` is required.
- FK validation on create_agent: voice_pool_id, tts_config_id, model_config_id checked before INSERT.
- `.env` is gitignored; `.env.example` is a placeholder-only bootstrap template. Qwen realtime endpoint/region are stored per Realtime Config rather than environment variables.
- When implementation details change in a way that contradicts existing spec/plan docs, update the docs too. Use the same commit. Don't update docs for trivial fixes (typos, style) — only when behavior, architecture, or event flow described in docs is no longer accurate.

# TTS Model Pool + Voice Model Binding Design Spec

## Overview

Add a TTS model pool (`tts_configs`) mirroring the existing LLM model pool. Voices are linked to TTS models via a many-to-many join table. Agent creation becomes a 4-step cascade wizard: TTS model → voice (filtered) → LLM → persona.

## Goals

- **TTS model pool**: Admin adds TTS models (provider, model, api_key)
- **Voice ↔ TTS linkage**: Each voice marked as compatible with one or more TTS models
- **Cascade selection**: Select TTS model first, then only show compatible voices
- **Voice enrollment with TTS binding**: Upload audio → select target TTS model → generate cloned voice → auto-linked
- **Per-agent TTS**: Agent gets `tts_config_id` FK, Worker uses it for TTS config

## Non-goals

- STT model pool (remains .env global)
- End-user TTS model management (admin only)

## Data Model

### New Table: tts_configs

```sql
CREATE TABLE tts_configs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

Pre-seed on first run:

| name | provider | model |
|------|----------|-------|
| 通义通用TTS | qwen | qwen3-tts-flash-realtime |
| 通义VC | qwen | qwen3-tts-vc-realtime-2026-01-15 |

### New Table: voice_tts_links

```sql
CREATE TABLE voice_tts_links (
    voice_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
    tts_config_id TEXT NOT NULL REFERENCES tts_configs(id) ON DELETE CASCADE,
    PRIMARY KEY (voice_id, tts_config_id)
);
```

Pre-seed: built-in voices linked to 通义通用TTS. Existing cloned voices linked to 通义VC.

### Agents Table

Add FK:

```sql
ALTER TABLE agents ADD COLUMN tts_config_id TEXT REFERENCES tts_configs(id);
```

### Token Embedding (call.py)

agent_config now includes `tts_config`:

```json
{
  "agent_id": "...",
  "system_prompt": "...",
  "voice_id": "Cherry",
  "model_config": {...},
  "tts_config": {
    "provider": "qwen",
    "model": "qwen3-tts-flash-realtime",
    "api_key": "sk-xxx"
  }
}
```

## API Changes

### TTS Configs CRUD (admin only)

```
GET    /api/admin/tts-configs              → list all
POST   /api/admin/tts-configs              → create
PATCH  /api/admin/tts-configs/{id}         → update
DELETE /api/admin/tts-configs/{id}         → delete (block if referenced)
```

### Voice ↔ TTS Link Management

```
GET    /api/admin/voices/{id}/tts-configs  → list TTS models compatible with this voice
POST   /api/admin/voices/{id}/tts-configs  → link voice to TTS model {tts_config_id}
DELETE /api/admin/voices/{id}/tts-configs/{tts_id} → unlink
```

### Voice Creation (updated)

```
POST /api/admin/voices  → {name, audio_file, tts_config_id}
```

Upload audio → enrollment → create voice → auto-link to tts_config_id.

### Voice List (updated)

```
GET /api/admin/voices   → includes linked tts_configs list per voice
GET /api/admin/voices?tts_config_id=X  → filter voices by TTS model compatibility
```

### Agent APIs

```
POST /api/agents → {alias, system_prompt, voice_pool_id, tts_config_id, model_config_id?}
PATCH /api/agents/{id} → add tts_config_id
```

## Agent Worker Changes

In `agent.py`, TTS config follows same pattern as LLM model_config:

```python
if config and config.get("tts_config"):
    tc = config["tts_config"]
    if tc["provider"] == "qwen":
        tts = QwenTTS(
            api_url=...,
            api_key=tc["api_key"],
            model=tc["model"],
            voice_id=voice_id,
        )
else:
    # fallback to .env
```

## Web Admin Changes

### Sidebar: add "TTS 模型" link

### New Page: TtsConfigList (mirrors ModelConfigList)

### Voice Pool Page: updated

- Upload form adds TTS model dropdown
- Each voice row shows linked TTS models as tags
- Click tag to link/unlink

### Agent Creation Wizard: 4 steps

1. **TTS 模型**: dropdown from tts_configs
2. **音色**: dropdown filtered by GET /api/admin/voices?tts_config_id=X
3. **LLM**: same as before
4. **人设**: same as before

### AgentDetailView: Pipeline card shows TTS model name

## Deployment

- DB migration: tts_configs + voice_tts_links + seed
- agents FK migration
- Vue build + API rebuild

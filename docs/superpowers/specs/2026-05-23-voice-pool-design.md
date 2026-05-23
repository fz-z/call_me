# Voice Pool + Agent Creation Wizard Design Spec

## Overview

Decouple voice management from agent creation. Introduce a `voices` table (voice pool) storing both built-in and cloned voices. Agent creation becomes a 3-step wizard: pick voice → pick LLM → write persona. No more audio upload during agent creation.

## Goals

- **Voice pool**: Admin manages voices (built-in + cloned) in one place
- **Voice enrollment independent**: Upload audio → generate cloned voice → stored in pool, reusable by any agent
- **Agent creation wizard**: 3 steps with preview at each step
- **Agent no longer needs audio upload**: voice_id selected from pool, model_config_id from pool

## Non-goals

- End-user voice upload (admin only)
- Voice deletion cascading to agents (blocked if in use)

## Data Model

### New Table: voices

```sql
CREATE TABLE voices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,          -- display name
    voice_id TEXT NOT NULL,             -- DashScope voice_id or built-in name
    type TEXT NOT NULL DEFAULT 'cloned', -- 'cloned' | 'builtin'
    created_at TEXT NOT NULL
);
```

Pre-seed built-in voices on first run:

| name | voice_id | type |
|------|----------|------|
| Cherry | Cherry | builtin |
| Stella | Stella | builtin |
| Luna | Luna | builtin |
| Scott | Scott | builtin |
| Kevin | Kevin | builtin |

### Agents Table

Add FK to voices:

```sql
ALTER TABLE agents ADD COLUMN voice_pool_id TEXT REFERENCES voices(id);
```

- `voice_pool_id` points to a voice in the pool
- `voice_id` field kept for backward compatibility (direct DashScope voice_id)

### Existing Data Migration

Existing agents: `voice_id` field contains raw DashScope voice IDs. Migration should create corresponding `voices` entries if they don't exist.

## API Changes

### Voice Pool CRUD (admin only)

```
GET    /api/admin/voices                  → list all voices
POST   /api/admin/voices                  → upload audio → enrollment → create voice {name}
POST   /api/admin/voices/builtin          → add a built-in voice {name, voice_id}
DELETE /api/admin/voices/{id}             → delete (block if referenced by agents)
```

### Agent Creation (changed)

```
POST /api/agents                          → {alias, system_prompt, voice_pool_id, model_config_id?}
```

No more `audio_file` multipart. `voice_pool_id` is required.

### Agent Update

```
PATCH /api/agents/{id}                    → {alias?, system_prompt?, voice_pool_id?, model_config_id?}
```

## Web Admin Changes

### Sidebar: add "声音库" link

### New Page: VoicePoolList

- Table: name, voice_id (truncated), type (内置/克隆 badge), used by N agents, actions
- "上传音频" button → modal: file picker + name input → POST /api/admin/voices
- Built-in voices cannot be deleted
- Cloned voices: delete blocked if referenced

### Agent Creation: replace form with 3-step wizard

**Step 1 - Voice selection:**
- Dropdown/list of all voices from pool
- Preview button (optional, plays sample if available)
- "下一步" →

**Step 2 - LLM selection:**
- Dropdown of model_configs + "系统默认" option
- Shows provider/model/temperature for selected config
- "上一步" / "下一步" →

**Step 3 - Persona & Confirm:**
- Alias input
- System prompt textarea
- Summary card: selected voice + LLM config
- "上一步" / "创建 Agent"

### AgentForm (edit mode): same wizard, pre-filled

### AgentDetailView: update pipeline card to show voice pool name

## Agent Worker

No changes needed. `voice_id` is still embedded in token as DashScope voice ID. The API resolves `voice_pool_id` → `voice_id` at token generation time.

## Future Compatibility

- `model_configs.provider` and `voices.type` are stored as strings, not enums. Adding new providers requires no schema change — only removing the validation whitelist and adding a Worker handler
- Worker LLM path uses OpenAI-compatible API pattern, making it easy to plug in any new provider with compatible endpoint
- TTS and STT remain `.env` global for now; future per-agent override follows the same pattern as model_configs

## Deployment

- DB migration: voices table + seed built-ins
- agents FK migration
- Existing voice_id values: create matching voices entries
- Vue build + API rebuild

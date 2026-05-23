# Model Config Management Design Spec

## Overview

Admin can create named LLM model configurations (provider, model, API key, temperature, etc.) in a global pool. Each Agent can optionally reference one model config. Agent detail page shows the full pipeline (LLM/TTS/STT) at a glance.

## Goals

- **LLM model pool**: Admin creates/edits/deletes named model configurations
- **Per-agent LLM**: Each Agent can select a model config from the pool, or use system default
- **Pipeline visibility**: Agent detail page shows LLM config, TTS voice, STT config
- **STT global**: Remains in `.env`, no per-agent override in MVP

## Non-goals

- Per-agent STT or TTS override
- End-user visible model configs (admin only)
- API key rotation or expiration management

## Data Model

### New Table: model_configs

```sql
CREATE TABLE model_configs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,           -- "默认生产" / "DeepSeek备选"
    provider TEXT NOT NULL,              -- "qwen" | "deepseek"
    model TEXT NOT NULL,                  -- "qwen3-max" | "deepseek-chat"
    api_key TEXT NOT NULL,
    temperature REAL NOT NULL DEFAULT 0.7,
    max_tokens INTEGER NOT NULL DEFAULT 2048,
    created_at TEXT NOT NULL
);
```

### Agents Table: add column

```sql
ALTER TABLE agents ADD COLUMN model_config_id TEXT REFERENCES model_configs(id) ON DELETE SET NULL;
```

- `model_config_id IS NULL` → use system default from `.env`
- `model_config_id = <id>` → use that config

## API Endpoints

### Model Configs CRUD (admin only)

```
GET    /api/admin/model-configs            → list all
POST   /api/admin/model-configs            → create {name, provider, model, api_key, temperature?, max_tokens?}
GET    /api/admin/model-configs/{id}       → get one
PATCH  /api/admin/model-configs/{id}       → update
DELETE /api/admin/model-configs/{id}       → delete (sets referencing agents to NULL)
```

### Agent Update

```
PATCH /api/agents/{id}                     → add model_config_id to body
```

`AgentOut` already includes `model_config_id: Optional[str] = None`.

### Call Token

`POST /api/call/token` → if agent has `model_config_id`, look up `model_configs` and embed full config in token attributes. Otherwise embed `model_config: null` (worker falls back to `.env`).

```json
{
  "agent_id": "...",
  "alias": "温柔客服",
  "system_prompt": "...",
  "voice_id": "Cherry",
  "model_config": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "api_key": "sk-xxx",
    "temperature": 0.7,
    "max_tokens": 2048
  }
}
```

### Admin Dashboard

`GET /api/admin/model-configs/{id}/agents` → list agents using a given model config.

## Agent Worker Changes

In `agent.py`, after reading `agent_config`, if `model_config` is present and non-null:

```python
if config.get("model_config"):
    mc = config["model_config"]
    if mc["provider"] == "deepseek":
        llm = openai.LLM.with_deepseek(
            model=mc["model"],
            api_key=mc["api_key"],
            temperature=mc.get("temperature", 0.7),
        )
    elif mc["provider"] == "qwen":
        llm = openai.LLM(
            model=mc["model"],
            api_key=mc["api_key"],
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=mc.get("temperature", 0.7),
        )
else:
    # fallback to .env defaults (existing logic)
```

## Web Admin Changes

### Sidebar: add "模型配置" link

### New Page: ModelConfigList

- Table: name, provider, model, used by N agents, actions (edit, delete)
- Delete shows confirmation if agents are using this config: "X agents will fall back to system default"

### New Component: ModelConfigForm (modal)

- Fields: name, provider (dropdown: qwen/deepseek), model, api_key (password field), temperature (slider 0-2), max_tokens
- Edit mode: pre-fills from existing config
- API key masked on edit (show last 4 chars, full key only on explicit reveal)

### AgentForm: add model config dropdown

- "System Default (.env)" option + list of all model configs
- Pre-select current config when editing

### AgentDetailView: add Pipeline tab/section

Show card with three rows:
```
LLM: 默认生产 (qwen3-max)  [切换▼]
TTS: Cherry (内置音色)
STT: deepgram/nova-2 (全局配置)
```

## Tech Stack

No new dependencies. Everything uses existing stack: FastAPI, SQLite, Vue 3.

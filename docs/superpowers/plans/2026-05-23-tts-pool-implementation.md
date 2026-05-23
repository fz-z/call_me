# TTS Model Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TTS model pool (tts_configs), voice-tts many-to-many links, 4-step agent creation cascade wizard.

**Architecture:** New tts_configs + voice_tts_links tables. API CRUD for TTS configs + voice link management. Worker reads tts_config from token. Vue wizard: TTS model → voice (cascade filtered) → LLM → persona.

**Tech Stack:** FastAPI, SQLite, Vue 3 (existing, no new deps).

---

### Task 1: DB migration — tts_configs + voice_tts_links + agents FK + seed

**Files:**
- Modify: `api/database.py`
- Modify: `api/models.py`

- [ ] **Step 1: Add migrations and seed in database.py**

In `init_db()`, after voices migration, add:

```python
        # Migration: tts_configs table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tts_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                api_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Migration: voice_tts_links many-to-many table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_tts_links (
                voice_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
                tts_config_id TEXT NOT NULL REFERENCES tts_configs(id) ON DELETE CASCADE,
                PRIMARY KEY (voice_id, tts_config_id)
            )
        """)

        # Migration: add tts_config_id to agents
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN tts_config_id TEXT REFERENCES tts_configs(id)")
        except sqlite3.OperationalError:
            pass

        # Seed TTS configs
        tts_seeds = [
            ("通义通用TTS", "qwen", "qwen3-tts-flash-realtime"),
            ("通义VC", "qwen", "qwen3-tts-vc-realtime-2026-01-15"),
        ]
        tts_ids = {}
        for name, provider, model in tts_seeds:
            existing = conn.execute("SELECT id FROM tts_configs WHERE name = ?", (name,)).fetchone()
            if not existing:
                tid = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO tts_configs (id, name, provider, model, api_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (tid, name, provider, model, os.environ.get("DASHSCOPE_API_KEY", ""), now),
                )
                tts_ids[name] = tid
            else:
                tts_ids[name] = existing["id"]

        # Seed voice_tts_links: built-in voices → 通义通用TTS, cloned voices → 通义VC
        if tts_ids:
            builtin_tts_id = tts_ids.get("通义通用TTS")
            vc_tts_id = tts_ids.get("通义VC")
            builtins = conn.execute("SELECT id FROM voices WHERE type = 'builtin'").fetchall()
            cloned = conn.execute("SELECT id FROM voices WHERE type = 'cloned'").fetchall()
            now = datetime.now(timezone.utc).isoformat()
            for v in builtins:
                if builtin_tts_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
                        (v["id"], builtin_tts_id),
                    )
            for v in cloned:
                if vc_tts_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO voice_tts_links (voice_id, tts_config_id) VALUES (?, ?)",
                        (v["id"], vc_tts_id),
                    )
```

- [ ] **Step 2: Add Pydantic models to api/models.py**

```python
class TtsConfigCreate(BaseModel):
    name: str
    provider: str
    model: str
    api_key: str


class TtsConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class TtsConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    api_key: str
    created_at: str
```

Add `tts_config_id` to `AgentOut` and `AgentUpdate`:

```python
class AgentOut(BaseModel):
    # ... existing fields ...
    tts_config_id: Optional[str] = None
```

```python
class AgentUpdate(BaseModel):
    alias: Optional[str] = None
    system_prompt: Optional[str] = None
    model_config_id: Optional[str] = None
    voice_pool_id: Optional[str] = None
    tts_config_id: Optional[str] = None
```

Add `voice_link` models:

```python
class VoiceTtsLinkRequest(BaseModel):
    tts_config_id: str
```

Update `VoiceOut` to include linked tts:

```python
class VoiceOut(BaseModel):
    id: str
    name: str
    voice_id: str
    type: str
    created_at: str
    tts_configs: list[TtsConfigOut] = []
```

- [ ] **Step 3: Verify**

```bash
cd api && python3 -c "
import os
os.environ['DATABASE_PATH']='/tmp/test_tts.db'
os.environ['ADMIN_USERNAME']='admin'; os.environ['ADMIN_PASSWORD']='test'
os.environ['DASHSCOPE_API_KEY']='sk-test'
from database import init_db, _sync_conn
init_db()
c = _sync_conn()
assert 'tts_configs' in [r['name'] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
assert 'voice_tts_links' in [r['name'] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('OK')
c.close()
"
```

- [ ] **Step 4: Commit**

```bash
git add api/database.py api/models.py
git commit -m "feat: tts_configs + voice_tts_links tables + seed + Pydantic models"
```

---

### Task 2: TTS configs CRUD API + voice link management

**Files:**
- Create: `api/tts_configs.py`
- Modify: `api/voices.py`
- Modify: `api/main.py`

- [ ] **Step 1: Create api/tts_configs.py** — CRUD endpoints mirroring model_configs.py pattern (list, create, update, delete with FK unlink)

- [ ] **Step 2: Update api/voices.py** — add endpoints for link management:
  - `GET /api/admin/voices/{id}/tts-configs` → list linked TTS configs
  - `POST /api/admin/voices/{id}/tts-configs` → link {tts_config_id}
  - `DELETE /api/admin/voices/{id}/tts-configs/{tts_id}` → unlink
  - Update `POST /api/admin/voices` to accept `tts_config_id` form field and auto-link
  - Update `GET /api/admin/voices` to support `?tts_config_id=X` filter
  - Update `GET /api/admin/voices` response to include linked tts_configs

- [ ] **Step 3: Update api/main.py** — register tts_configs router

- [ ] **Step 4: Commit**

---

### Task 3: Update agents API + call.py + Worker

**Files:**
- Modify: `api/agents.py` — PATCH handles tts_config_id, POST includes it
- Modify: `api/permissions.py` — grant copies tts_config_id
- Modify: `api/call.py` — embed tts_config in token
- Modify: `agent/agent.py` — dynamic TTS from tts_config in token, fallback to .env

- [ ] **Step 1: Update POST/PATCH in agents.py** — accept tts_config_id, store it

- [ ] **Step 2: Update grant in permissions.py** — copy tts_config_id to new agent

- [ ] **Step 3: Update call.py** — lookup tts_config and embed in token agent_config

- [ ] **Step 4: Update agent.py** — if tts_config present in token, use it for QwenTTS(); else fallback to .env

- [ ] **Step 5: Commit**

---

### Task 4: Vue — TtsConfigList page + Updated VoicePool page

**Files:**
- Create: `web-admin/src/views/TtsConfigListView.vue`
- Modify: `web-admin/src/views/VoicePoolView.vue`
- Modify: `web-admin/src/router.js` + `App.vue`

- [ ] **Step 1: Write TtsConfigListView.vue** — table with name, provider, model, linked voices count, create/edit/delete modals

- [ ] **Step 2: Update VoicePoolView.vue** — upload form adds TTS model dropdown; each voice row shows linked TTS models as clickable tags; add/remove links

- [ ] **Step 3: Update router + sidebar** — add "TTS 模型" link

- [ ] **Step 4: Commit**

---

### Task 5: Vue — 4-step agent creation wizard

**Files:**
- Modify: `web-admin/src/components/AgentForm.vue`
- Modify: `web-admin/src/views/AgentDetailView.vue`

- [ ] **Step 1: Rewrite AgentForm.vue** — 4 steps: TTS model → voice (cascade filtered by selected TTS) → LLM → persona

- [ ] **Step 2: Update AgentDetailView.vue** — Pipeline card shows TTS model name

- [ ] **Step 3: Commit**

---

### Task 6: Build, deploy, E2E test

**Files:** none (build + test)

- [ ] **Step 1: Copy files + build Vue + rebuild Docker**

- [ ] **Step 2: E2E test** — verify seed data, create agent with TTS config, cascade filtering works

- [ ] **Step 3: Commit any fixes**

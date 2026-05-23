# Voice Pool + Agent Creation Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple voice management from agent creation. Add voices table (voice pool), 3-step agent creation wizard, and voice pool admin page.

**Architecture:** New voices table with FK from agents. API for voice pool CRUD + voice enrollment. POST /api/agents no longer requires audio upload — accepts voice_pool_id instead. Vue wizard replaces single-step agent form.

**Tech Stack:** FastAPI, SQLite, Vue 3 (no new deps).

---

### Task 1: Database migration — voices table + agents FK + built-in seed

**Files:**
- Modify: `api/database.py`
- Modify: `api/models.py`

- [ ] **Step 1: Add voices table migration and seed in database.py**

In `init_db()`, after model_configs migration, add:

```python
        # Migration: voices table for voice pool
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                voice_id TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'cloned',
                created_at TEXT NOT NULL
            )
        """)

        # Migration: add voice_pool_id to agents
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN voice_pool_id TEXT REFERENCES voices(id)")
        except sqlite3.OperationalError:
            pass

        # Seed built-in voices
        builtins = [
            ("Cherry", "Cherry"),
            ("Stella", "Stella"),
            ("Luna", "Luna"),
            ("Scott", "Scott"),
            ("Kevin", "Kevin"),
        ]
        for name, vid in builtins:
            existing = conn.execute(
                "SELECT id FROM voices WHERE name = ?", (name,)
            ).fetchone()
            if not existing:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), name, vid, "builtin", now),
                )
```

- [ ] **Step 2: Add Voice models to api/models.py**

```python
class VoiceOut(BaseModel):
    id: str
    name: str
    voice_id: str
    type: str  # "cloned" | "builtin"
    created_at: str


class VoiceCreate(BaseModel):
    name: str
```

- [ ] **Step 3: Add voice_pool_id to AgentOut**

```python
class AgentOut(BaseModel):
    id: str
    alias: str
    voice_id: str
    voice_pool_id: Optional[str] = None
    system_prompt: str
    owner_id: str
    source_agent_id: Optional[str] = None
    model_config_id: Optional[str] = None
    created_at: str
```

- [ ] **Step 4: Add voice_pool_id to AgentCreate and AgentUpdate**

```python
class AgentCreate(BaseModel):
    alias: str
    system_prompt: str = ""
    voice_pool_id: str


class AgentUpdate(BaseModel):
    alias: Optional[str] = None
    system_prompt: Optional[str] = None
    model_config_id: Optional[str] = None
    voice_pool_id: Optional[str] = None
```

- [ ] **Step 5: Verify migration**

```bash
cd api && python3 -c "
import os
os.environ['DATABASE_PATH']='/tmp/test_voice.db'
os.environ['ADMIN_USERNAME']='admin'; os.environ['ADMIN_PASSWORD']='test'
from database import init_db, _sync_conn
init_db()
c = _sync_conn()
tables = [r['name'] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
assert 'voices' in tables
cols = [r['name'] for r in c.execute('PRAGMA table_info(agents)').fetchall()]
assert 'voice_pool_id' in cols
voices = c.execute('SELECT * FROM voices').fetchall()
assert len(voices) >= 5, f'Expected >=5 built-ins, got {len(voices)}'
print(f'OK: {len(voices)} voices, voice_pool_id column exists')
c.close()
"
```

- [ ] **Step 6: Commit**

```bash
git add api/database.py api/models.py
git commit -m "feat: voices table + FK + built-in seed + Pydantic models"
```

---

### Task 2: API — voice pool CRUD + voice enrollment endpoint

**Files:**
- Create: `api/voices.py`
- Modify: `api/main.py`

- [ ] **Step 1: Create api/voices.py**

```python
import uuid
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database import _sync_conn
from models import VoiceOut, VoiceCreate
from auth import require_admin
from voice_enrollment import enroll_voice

router = APIRouter(prefix="/api/admin/voices", tags=["voices"])


@router.get("", response_model=list[VoiceOut])
def list_voices(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT * FROM voices ORDER BY type, name").fetchall()
        return [VoiceOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.post("", response_model=VoiceOut)
async def create_voice(
    name: str = Form(...),
    audio_file: UploadFile = File(...),
    admin: dict = Depends(require_admin),
):
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="DASHSCOPE_API_KEY not configured")

    audio_bytes = await audio_file.read()
    content_type = audio_file.content_type or "audio/wav"

    try:
        dashscope_voice_id = await enroll_voice(audio_bytes, content_type, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice enrollment failed: {e}")

    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM voices WHERE name = ?", (name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Voice name already exists")

        voice_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO voices (id, name, voice_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
            (voice_id, name, dashscope_voice_id, "cloned", now),
        )
        db.commit()
        return VoiceOut(id=voice_id, name=name, voice_id=dashscope_voice_id, type="cloned", created_at=now)
    finally:
        db.close()


@router.delete("/{voice_id}", status_code=204)
def delete_voice(voice_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        if voice["type"] == "builtin":
            raise HTTPException(status_code=400, detail="Cannot delete built-in voice")

        refs = db.execute(
            "SELECT COUNT(*) as c FROM agents WHERE voice_pool_id = ?", (voice_id,)
        ).fetchone()["c"]
        if refs > 0:
            raise HTTPException(status_code=400, detail=f"Voice is used by {refs} agent(s)")

        db.execute("DELETE FROM voices WHERE id = ?", (voice_id,))
        db.commit()
    finally:
        db.close()
    return None
```

- [ ] **Step 2: Register router in api/main.py**

```python
from voices import router as voices_router
# ...
app.include_router(voices_router)
```

- [ ] **Step 3: Commit**

```bash
git add api/voices.py api/main.py
git commit -m "feat: voice pool CRUD + enrollment endpoint"
```

---

### Task 3: Update agents API to use voice_pool_id

**Files:**
- Modify: `api/agents.py`
- Modify: `api/permissions.py`

- [ ] **Step 1: Rewrite POST /api/agents — no more audio upload**

Replace the `create_agent` function:

```python
@router.post("", response_model=AgentOut)
def create_agent(
    body: AgentCreate,
    user: dict = Depends(get_current_user),
):
    """Create an agent by selecting a voice from the pool. No audio upload."""
    db = _sync_conn()
    try:
        # Lookup voice from pool
        voice = db.execute(
            "SELECT voice_id FROM voices WHERE id = ?", (body.voice_pool_id,)
        ).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found in pool")

        agent_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, voice_pool_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (agent_id, body.alias, voice["voice_id"], body.system_prompt, user["id"], body.voice_pool_id, now),
        )
        db.commit()
        return AgentOut(
            id=agent_id, alias=body.alias, voice_id=voice["voice_id"],
            voice_pool_id=body.voice_pool_id,
            system_prompt=body.system_prompt, owner_id=user["id"], created_at=now,
        )
    finally:
        db.close()
```

Note: Remove FastAPI `UploadFile, File, Form` imports, add `AgentCreate` import if not already. Remove `voice_enrollment` import.

- [ ] **Step 2: Update PATCH /api/agents to handle voice_pool_id**

In `update_agent`, after reading `row`, add voice lookup:

```python
        new_alias = body.alias if body.alias is not None else row["alias"]
        new_prompt = body.system_prompt if body.system_prompt is not None else row["system_prompt"]
        new_model_config_id = body.model_config_id if body.model_config_id is not None else row["model_config_id"]
        new_voice_pool_id = body.voice_pool_id if body.voice_pool_id is not None else row["voice_pool_id"]
        new_voice_id = row["voice_id"]

        if body.voice_pool_id is not None:
            voice_row = db.execute("SELECT voice_id FROM voices WHERE id = ?", (body.voice_pool_id,)).fetchone()
            if not voice_row:
                raise HTTPException(status_code=404, detail="Voice not found")
            new_voice_id = voice_row["voice_id"]

        db.execute(
            "UPDATE agents SET alias=?, system_prompt=?, model_config_id=?, voice_pool_id=?, voice_id=? WHERE id=?",
            (new_alias, new_prompt, new_model_config_id, new_voice_pool_id, new_voice_id, agent_id),
        )
```

- [ ] **Step 3: Update grant endpoint in permissions.py**

In `grant_permission`, copy `voice_pool_id` from source agent:

```python
        db.execute(
            "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, source_agent_id, voice_pool_id, model_config_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (copy_id, agent_row["alias"], agent_row["voice_id"], agent_row["system_prompt"], user_row["id"], agent_id, agent_row["voice_pool_id"], agent_row["model_config_id"], now),
        )
```

- [ ] **Step 4: Commit**

```bash
git add api/agents.py api/permissions.py
git commit -m "feat: agents use voice_pool_id instead of audio upload"
```

---

### Task 4: Vue — VoicePool page + upload component

**Files:**
- Create: `web-admin/src/views/VoicePoolView.vue`
- Modify: `web-admin/src/router.js`
- Modify: `web-admin/src/App.vue`

- [ ] **Step 1: Write VoicePoolView.vue**

Full Vue component with table listing voices (name, voice_id truncated, type badge, referenced agent count) + upload modal. Delete button for cloned voices only.

- [ ] **Step 2: Update router.js**

Add import and route for `/voices` → `VoicePoolView`.

- [ ] **Step 3: Update App.vue sidebar**

Add `<router-link to="/voices">声音库</router-link>`.

- [ ] **Step 4: Commit**

---

### Task 5: Vue — 3-step agent creation wizard

**Files:**
- Rewrite: `web-admin/src/components/AgentForm.vue`

- [ ] **Step 1: Write wizard component**

Three steps managed by `currentStep` ref (1/2/3):

Step 1: Voice selection — dropdown from GET /api/admin/voices, grouped by type
Step 2: LLM selection — dropdown from GET /api/admin/model-configs
Step 3: Alias + system_prompt + summary card + create

Navigation: "上一步" / "下一步" buttons. Step 3 has "创建 Agent".

On create: POST /api/agents {alias, system_prompt, voice_pool_id, model_config_id?}

Edit mode: same wizard, pre-filled from existing agent data.

- [ ] **Step 2: Commit**

---

### Task 6: Build, deploy, E2E test

**Files:** none (build + test)

- [ ] **Step 1: Copy all files to main project, rebuild Docker**

```bash
# Copy from worktree
cp .../api/database.py .../api/models.py .../api/agents.py .../api/permissions.py .../api/voices.py .../api/main.py /Users/zhangfuzhen/Projects/call_me/api/
docker compose up -d --build
```

- [ ] **Step 2: Build Vue and deploy**

```bash
npm run build && docker compose up -d api
```

- [ ] **Step 3: E2E test flow**

```bash
# Login → list voices → upload audio create voice → create agent with voice_pool_id → verify
```

- [ ] **Step 4: Commit any fixes**

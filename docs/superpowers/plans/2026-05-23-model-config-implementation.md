# Model Config Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin creates named LLM model configs in a global pool. Agents optionally reference one. Agent detail page shows full pipeline (LLM/TTS/STT). Worker dynamically configures LLM from token-embedded model_config.

**Architecture:** New model_configs table + agents.model_config_id FK. API CRUD endpoints. Token embeds model_config in agent_config. Worker reads it to override default LLM. Vue pages for management + agent pipeline display.

**Tech Stack:** FastAPI, SQLite, Vue 3 (existing, no new deps).

---

### Task 1: Database migration — model_configs table + agents FK

**Files:**
- Modify: `api/database.py`
- Modify: `api/models.py`

- [ ] **Step 1: Add model_configs table and agents FK migration to database.py**

In `init_db()`, after the `source_agent_id` migration, add:

```python
        # Migration: model_configs table for LLM config pool
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                api_key TEXT NOT NULL,
                temperature REAL NOT NULL DEFAULT 0.7,
                max_tokens INTEGER NOT NULL DEFAULT 2048,
                created_at TEXT NOT NULL
            )
        """)

        # Migration: add model_config_id to agents
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN model_config_id TEXT REFERENCES model_configs(id) ON DELETE SET NULL")
        except sqlite3.OperationalError:
            pass
```

- [ ] **Step 2: Add ModelConfig models to api/models.py**

```python
class ModelConfigCreate(BaseModel):
    name: str
    provider: str  # "qwen" | "deepseek"
    model: str
    api_key: str
    temperature: float = 0.7
    max_tokens: int = 2048


class ModelConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ModelConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    api_key: str
    temperature: float
    max_tokens: int
    created_at: str
```

Also update `AgentOut` to include:

```python
class AgentOut(BaseModel):
    id: str
    alias: str
    voice_id: str
    system_prompt: str
    owner_id: str
    source_agent_id: Optional[str] = None
    model_config_id: Optional[str] = None
    created_at: str
```

And update `AgentUpdate`:

```python
class AgentUpdate(BaseModel):
    alias: Optional[str] = None
    system_prompt: Optional[str] = None
    model_config_id: Optional[str] = None
```

- [ ] **Step 3: Verify migration**

```bash
cd api && python3 -c "
import os
os.environ['DATABASE_PATH']='/tmp/test_mc.db'
os.environ['ADMIN_USERNAME']='admin'
os.environ['ADMIN_PASSWORD']='test'
from database import init_db, _sync_conn
init_db()
c = _sync_conn()
tables = [r['name'] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
assert 'model_configs' in tables, f'Missing model_configs table. Tables: {tables}'
cols = [r['name'] for r in c.execute('PRAGMA table_info(agents)').fetchall()]
assert 'model_config_id' in cols, f'Missing model_config_id column. Cols: {cols}'
print('OK')
c.close()
"
```

- [ ] **Step 4: Commit**

```bash
git add api/database.py api/models.py
git commit -m "feat: model_configs table + agents.model_config_id FK + Pydantic models"
```

---

### Task 2: API — model configs CRUD endpoints

**Files:**
- Create: `api/model_configs.py`
- Modify: `api/main.py`

- [ ] **Step 1: Create api/model_configs.py**

```python
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn
from models import ModelConfigCreate, ModelConfigUpdate, ModelConfigOut
from auth import require_admin

router = APIRouter(prefix="/api/admin/model-configs", tags=["model-configs"])


@router.get("", response_model=list[ModelConfigOut])
def list_configs(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute("SELECT * FROM model_configs ORDER BY created_at DESC").fetchall()
        return [ModelConfigOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.post("", response_model=ModelConfigOut)
def create_config(body: ModelConfigCreate, admin: dict = Depends(require_admin)):
    if body.provider not in ("qwen", "deepseek"):
        raise HTTPException(status_code=400, detail="Provider must be qwen or deepseek")
    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM model_configs WHERE name = ?", (body.name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Config name already exists")

        config_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO model_configs (id, name, provider, model, api_key, temperature, max_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (config_id, body.name, body.provider, body.model, body.api_key, body.temperature, body.max_tokens, now),
        )
        db.commit()
        return ModelConfigOut(
            id=config_id, name=body.name, provider=body.provider, model=body.model,
            api_key=body.api_key, temperature=body.temperature, max_tokens=body.max_tokens, created_at=now,
        )
    finally:
        db.close()


@router.patch("/{config_id}", response_model=ModelConfigOut)
def update_config(config_id: str, body: ModelConfigUpdate, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        row = db.execute("SELECT * FROM model_configs WHERE id = ?", (config_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Config not found")

        db.execute(
            """UPDATE model_configs SET name=?, provider=?, model=?, api_key=?,
               temperature=?, max_tokens=? WHERE id=?""",
            (
                body.name if body.name is not None else row["name"],
                body.provider if body.provider is not None else row["provider"],
                body.model if body.model is not None else row["model"],
                body.api_key if body.api_key is not None else row["api_key"],
                body.temperature if body.temperature is not None else row["temperature"],
                body.max_tokens if body.max_tokens is not None else row["max_tokens"],
                config_id,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM model_configs WHERE id = ?", (config_id,)).fetchone()
        return ModelConfigOut(**dict(row))
    finally:
        db.close()


@router.delete("/{config_id}", status_code=204)
def delete_config(config_id: str, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM model_configs WHERE id = ?", (config_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Config not found")

        # Unlink agents using this config
        db.execute("UPDATE agents SET model_config_id = NULL WHERE model_config_id = ?", (config_id,))
        db.execute("DELETE FROM model_configs WHERE id = ?", (config_id,))
        db.commit()
    finally:
        db.close()
    return None
```

- [ ] **Step 2: Register router in api/main.py**

Add after other router imports:

```python
from model_configs import router as model_configs_router
```

Add after other `app.include_router` calls:

```python
app.include_router(model_configs_router)
```

- [ ] **Step 3: Commit**

```bash
git add api/model_configs.py api/main.py
git commit -m "feat: model configs CRUD endpoints (admin only)"
```

---

### Task 3: API — update call.py to embed model_config

**Files:**
- Modify: `api/call.py`

- [ ] **Step 1: Update get_call_token to include model_config**

In `api/call.py`, after reading `agent_row` and before building `agent_config`, add a query for model_config:

```python
        # Fetch model_config if agent has one
        model_config = None
        if agent_row["model_config_id"]:
            mc_row = db.execute(
                "SELECT * FROM model_configs WHERE id = ?",
                (agent_row["model_config_id"],),
            ).fetchone()
            if mc_row:
                model_config = {
                    "provider": mc_row["provider"],
                    "model": mc_row["model"],
                    "api_key": mc_row["api_key"],
                    "temperature": mc_row["temperature"],
                    "max_tokens": mc_row["max_tokens"],
                }

        agent_config = json.dumps({
            "agent_id": agent_row["id"],
            "alias": agent_row["alias"],
            "system_prompt": agent_row["system_prompt"],
            "voice_id": agent_row["voice_id"],
            "model_config": model_config,
        })
```

- [ ] **Step 2: Commit**

```bash
git add api/call.py
git commit -m "feat: embed model_config in call token when agent has one"
```

---

### Task 4: Agent Worker — use model_config from token

**Files:**
- Modify: `agent/agent.py`

- [ ] **Step 1: Update LLM config logic**

Replace the LLM configuration block (after reading agent_config) with:

```python
    # LLM — use model_config from token if available, otherwise .env default
    if config and config.get("model_config"):
        mc = config["model_config"]
        mc_provider = mc["provider"]
        if mc_provider == "deepseek":
            llm = openai.LLM.with_deepseek(
                model=mc["model"],
                api_key=mc["api_key"],
                temperature=mc.get("temperature", 0.7),
            )
        elif mc_provider == "qwen":
            llm = openai.LLM(
                model=mc["model"],
                api_key=mc["api_key"],
                base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                temperature=mc.get("temperature", 0.7),
            )
        else:
            raise ValueError(f"Unsupported model_config provider: {mc_provider}")
    else:
        # Fallback to .env defaults
        llm_provider = os.getenv("LLM_PROVIDER", "qwen").strip().lower()
        if llm_provider == "qwen":
            qwen_base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            llm = openai.LLM(
                model=os.getenv("QWEN_MODEL", "qwen3-max"),
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url=qwen_base_url,
                temperature=0.7,
            )
        elif llm_provider == "deepseek":
            llm = openai.LLM.with_deepseek(model="deepseek-chat", temperature=0.7)
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {llm_provider}")
```

- [ ] **Step 2: Commit**

```bash
git add agent/agent.py
git commit -m "feat: agent worker uses model_config from token, falls back to .env"
```

---

### Task 5: Rebuild API + Agent, verify backend

**Files:** none (Docker rebuild)

- [ ] **Step 1: Copy files to main project and rebuild**

```bash
cp /Users/zhangfuzhen/Projects/call_me/.worktrees/web-admin/api/database.py /Users/zhangfuzhen/Projects/call_me/api/database.py
cp /Users/zhangfuzhen/Projects/call_me/.worktrees/web-admin/api/models.py /Users/zhangfuzhen/Projects/call_me/api/models.py
cp /Users/zhangfuzhen/Projects/call_me/.worktrees/web-admin/api/model_configs.py /Users/zhangfuzhen/Projects/call_me/api/model_configs.py 2>/dev/null
cp /Users/zhangfuzhen/Projects/call_me/.worktrees/web-admin/api/main.py /Users/zhangfuzhen/Projects/call_me/api/main.py
cp /Users/zhangfuzhen/Projects/call_me/.worktrees/web-admin/api/call.py /Users/zhangfuzhen/Projects/call_me/api/call.py
cp /Users/zhangfuzhen/Projects/call_me/.worktrees/web-admin/agent/agent.py /Users/zhangfuzhen/Projects/call_me/agent/agent.py
docker compose -f /Users/zhangfuzhen/Projects/call_me/docker-compose.yml up -d --build
```

- [ ] **Step 2: Test model configs API**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
H="Authorization: Bearer $TOKEN"

# Create config
curl -s -X POST http://localhost:8000/api/admin/model-configs -H "$H" -H "Content-Type: application/json" -d '{"name":"TestDeepSeek","provider":"deepseek","model":"deepseek-chat","api_key":"sk-test"}' | python3 -m json.tool

# List
curl -s http://localhost:8000/api/admin/model-configs -H "$H" | python3 -c "import sys,json; print(f'Configs: {len(json.load(sys.stdin))}')"

# Update an agent to use it
AGENT_ID=$(curl -s http://localhost:8000/api/agents -H "$H" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
CONFIG_ID=$(curl -s http://localhost:8000/api/admin/model-configs -H "$H" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
curl -s -X PATCH "http://localhost:8000/api/agents/$AGENT_ID" -H "$H" -H "Content-Type: application/json" -d "{\"model_config_id\":\"$CONFIG_ID\"}" | python3 -c "import sys,json; a=json.load(sys.stdin); print(f'Agent model_config_id: {a.get(\"model_config_id\",\"NONE\")}')"

# Verify token includes model_config
curl -s -X POST http://localhost:8000/api/call/token -H "$H" -H "Content-Type: application/json" -d "{\"agent_id\":\"$AGENT_ID\"}" | python3 -c "import sys,json,base64; t=json.load(sys.stdin)['token']; import jwt; d=jwt.decode(t, options={'verify_signature':False}); print('model_config in token:', d.get('attr','{}').get('agent_config','')[:80])"
```

- [ ] **Step 3: Commit any fixes if needed**

---

### Task 6: Vue — ModelConfigList page + ModelConfigForm

**Files:**
- Create: `web-admin/src/views/ModelConfigListView.vue`
- Create: `web-admin/src/components/ModelConfigForm.vue`
- Modify: `web-admin/src/router.js`
- Modify: `web-admin/src/App.vue`

- [ ] **Step 1: Write ModelConfigListView.vue**

```vue
<template>
  <div>
    <div class="page-header">
      <h2>模型配置</h2>
      <button class="btn btn-primary" @click="showForm = true">+ 新建配置</button>
    </div>
    <table>
      <thead><tr>
        <th>名称</th><th>提供商</th><th>模型</th><th>使用此配置的 Agent</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="mc in configs" :key="mc.id">
          <td>{{ mc.name }}</td>
          <td>{{ mc.provider }}</td>
          <td style="color:#4a90d9">{{ mc.model }}</td>
          <td>
            <span v-for="a in mc._agents" :key="a.id" class="tag">{{ a.alias }}</span>
            <span v-if="!mc._agents?.length" style="color:#888;font-size:12px">暂无</span>
          </td>
          <td>
            <button class="btn-ghost" @click="edit(mc)">编辑</button>
            <button class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(mc)">删除</button>
          </td>
        </tr>
        <tr v-if="!configs.length">
          <td colspan="5" style="color:#888;text-align:center;padding:24px">暂无配置。Agent 将使用 .env 系统默认。</td>
        </tr>
      </tbody>
    </table>
    <ModelConfigForm v-if="showForm" :editId="editId" :editData="editData" @close="closeForm" @saved="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';
import ModelConfigForm from '../components/ModelConfigForm.vue';

const configs = ref([]);
const showForm = ref(false);
const editId = ref(null);
const editData = ref(null);

async function load() {
  const [r1, r2] = await Promise.all([
    api.get('/admin/model-configs'),
    api.get('/admin/agents'),
  ]);
  const allAgents = r2.data;
  configs.value = r1.data.map(mc => ({
    ...mc,
    _agents: allAgents.filter(a => a.model_config_id === mc.id),
  }));
}

function edit(mc) { editId.value = mc.id; editData.value = mc; showForm.value = true; }
function closeForm() { showForm.value = false; editId.value = null; editData.value = null; }

async function del(mc) {
  const count = mc._agents?.length || 0;
  const msg = count ? `Delete "${mc.name}"? ${count} agent(s) will fall back to system default.` : `Delete "${mc.name}"?`;
  if (!confirm(msg)) return;
  await api.delete(`/admin/model-configs/${mc.id}`);
  await load();
}

onMounted(load);
</script>
```

- [ ] **Step 2: Write ModelConfigForm.vue**

```vue
<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <form class="modal" @submit.prevent="submit" style="min-width:400px">
      <h3>{{ editId ? '编辑' : '新建' }}模型配置</h3>
      <input v-model="form.name" placeholder="配置名称" required />
      <select v-model="form.provider" required>
        <option value="qwen">qwen (通义千问)</option>
        <option value="deepseek">deepseek</option>
      </select>
      <input v-model="form.model" placeholder="模型名 (如 qwen3-max, deepseek-chat)" required />
      <input v-model="form.api_key" placeholder="API Key" type="password" required />
      <label style="font-size:12px;color:#888">Temperature: {{ form.temperature }}</label>
      <input v-model.number="form.temperature" type="range" min="0" max="2" step="0.1" />
      <input v-model.number="form.max_tokens" placeholder="Max Tokens" type="number" />
      <p v-if="error" class="error">{{ error }}</p>
      <div class="modal-actions">
        <button type="button" class="btn-ghost" @click="$emit('close')">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="loading">保存</button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue';
import api from '../api.js';

const props = defineProps({ editId: String, editData: Object });
const emit = defineEmits(['close', 'saved']);

const form = reactive({
  name: props.editData?.name || '',
  provider: props.editData?.provider || 'qwen',
  model: props.editData?.model || '',
  api_key: props.editData?.api_key || '',
  temperature: props.editData?.temperature ?? 0.7,
  max_tokens: props.editData?.max_tokens ?? 2048,
});
const loading = ref(false);
const error = ref('');

async function submit() {
  loading.value = true; error.value = '';
  try {
    if (props.editId) {
      await api.patch(`/admin/model-configs/${props.editId}`, form);
    } else {
      await api.post('/admin/model-configs', form);
    }
    emit('saved'); emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed';
  } finally { loading.value = false; }
}
</script>

<style scoped>
select { width:100%; padding:8px; margin-bottom:12px; background:#0f0f1a; border:1px solid #333; color:#e0e0e0; border-radius:4px; }
input[type=range] { width:100%; margin-bottom:12px; }
</style>
```

- [ ] **Step 3: Update router.js**

Add route:
```javascript
  { path: '/model-configs', component: ModelConfigListView },
```

Add import:
```javascript
import ModelConfigListView from './views/ModelConfigListView.vue';
```

- [ ] **Step 4: Update App.vue sidebar**

Add before `</nav>`:
```html
        <router-link to="/model-configs">模型配置</router-link>
```

- [ ] **Step 5: Commit**

```bash
git add web-admin/src/views/ModelConfigListView.vue web-admin/src/components/ModelConfigForm.vue web-admin/src/router.js web-admin/src/App.vue
git commit -m "feat: Vue model config list page and form component"
```

---

### Task 7: Vue — update AgentForm + AgentDetailView with pipeline display

**Files:**
- Modify: `web-admin/src/components/AgentForm.vue`
- Modify: `web-admin/src/views/AgentDetailView.vue`

- [ ] **Step 1: Update AgentForm.vue — add model config dropdown**

Add below the systemPrompt textarea, before the file input:

```html
      <select v-model="modelConfigId">
        <option value="">系统默认 (.env)</option>
        <option v-for="mc in modelConfigs" :key="mc.id" :value="mc.id">
          {{ mc.name }} ({{ mc.provider }}/{{ mc.model }})
        </option>
      </select>
```

Add to script:

```javascript
const modelConfigs = ref([]);
const modelConfigId = ref(props.editModelConfigId || '');

onMounted(async () => {
  try {
    const r = await api.get('/admin/model-configs');
    modelConfigs.value = r.data;
  } catch (_) {}
});
```

Update submit() to include model_config_id in both PATCH and POST:

```javascript
if (props.editId) {
  await api.patch(`/agents/${props.editId}`, {
    alias: alias.value,
    system_prompt: systemPrompt.value,
    model_config_id: modelConfigId.value || null,
  });
} else {
  const fd = new FormData();
  fd.append('alias', alias.value);
  fd.append('system_prompt', systemPrompt.value);
  if (modelConfigId.value) fd.append('model_config_id', modelConfigId.value);
  fd.append('audio_file', file.value);
  await api.post('/agents', fd);
}
```

Add to props: `editModelConfigId: String`

Add import: `import { ref, onMounted } from 'vue';`

- [ ] **Step 2: Update AgentDetailView.vue — add pipeline card**

Replace the simple info line (`音色: ... | 人设: ...`) with:

```html
    <div class="pipeline-card" style="background:#1a1a2e;border-radius:8px;padding:16px;margin-bottom:16px">
      <h4 style="margin-bottom:12px">Pipeline 配置</h4>
      <div class="pipeline-row" style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #222">
        <span style="color:#888">LLM</span>
        <span>{{ agent.model_config_id ? (getConfigName(agent.model_config_id)) : '系统默认 (.env)' }}</span>
      </div>
      <div class="pipeline-row" style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #222">
        <span style="color:#888">TTS</span>
        <span>{{ agent.voice_id }}</span>
      </div>
      <div class="pipeline-row" style="display:flex;justify-content:space-between;padding:6px 0">
        <span style="color:#888">STT</span>
        <span style="color:#888">全局配置</span>
      </div>
      <div style="margin-top:8px;font-size:11px;color:#666">LLM 模型在"模型配置"页面管理</div>
    </div>
```

Also load model_configs to resolve names:

```javascript
const modelConfigs = ref([]);

// In load():
const r4 = await api.get('/admin/model-configs').catch(() => ({ data: [] }));
modelConfigs.value = r4.data;

function getConfigName(id) {
  return modelConfigs.value.find(mc => mc.id === id)?.name || id?.substring(0,8);
}
```

- [ ] **Step 3: Commit**

```bash
git add web-admin/src/components/AgentForm.vue web-admin/src/views/AgentDetailView.vue
git commit -m "feat: agent form model config dropdown, agent detail pipeline card"
```

---

### Task 8: Build Vue, deploy, E2E test

**Files:** none (build + test)

- [ ] **Step 1: Build and deploy**

```bash
cd /Users/zhangfuzhen/Projects/call_me/.worktrees/web-admin/web-admin && npm run build
cp -r dist/* /Users/zhangfuzhen/Projects/call_me/web-admin/dist/
docker compose -f /Users/zhangfuzhen/Projects/call_me/docker-compose.yml up -d api
```

- [ ] **Step 2: E2E test**

```bash
# Verify Vue admin loads
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/admin/

# Full flow: create config → assign to agent → get token → verify
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
H="Authorization: Bearer $TOKEN"

# Create config
CONFIG_ID=$(curl -s -X POST http://localhost:8000/api/admin/model-configs -H "$H" -H "Content-Type: application/json" -d '{"name":"DefaultQwen","provider":"qwen","model":"qwen3-max","api_key":"'$DASHSCOPE_API_KEY'"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Assign to agent
AGENT_ID=$(curl -s http://localhost:8000/api/agents -H "$H" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
curl -s -X PATCH "http://localhost:8000/api/agents/$AGENT_ID" -H "$H" -H "Content-Type: application/json" -d "{\"model_config_id\":\"$CONFIG_ID\"}"

# Get token and verify model_config embedded
curl -s -X POST http://localhost:8000/api/call/token -H "$H" -d "{\"agent_id\":\"$AGENT_ID\"}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Token received, length:', len(d['token']))"

echo "E2E complete"
```

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "chore: build and integration fixes for model config"
```

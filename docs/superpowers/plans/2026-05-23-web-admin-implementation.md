# Web Admin Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Vue 3 web admin panel with agent management, user management, and authorization — replacing the Flutter admin panel.

**Architecture:** Vue 3 SPA served as static files from the FastAPI container. Uses existing REST API + new admin-specific endpoints for root agent / copy distinction. JWT auth (admin-only). Hash-mode router.

**Tech Stack:** Vue 3 (Composition API), Vite, Axios, Vue Router (hash mode). Served via FastAPI StaticFiles.

---

### Task 1: Database migration — add source_agent_id

**Files:**
- Modify: `api/database.py`

- [ ] **Step 1: Update init_db() to add source_agent_id column**

In `api/database.py`, add the migration after the CREATE TABLE statements:

```python
# Migration: add source_agent_id to distinguish root agents from copies
try:
    conn.execute("ALTER TABLE agents ADD COLUMN source_agent_id TEXT REFERENCES agents(id)")
except sqlite3.OperationalError:
    pass  # column already exists
```

Insert this right after the CREATE TABLE statements, before the admin seed logic.

- [ ] **Step 2: Verify migration works**

```bash
cd api && DATABASE_PATH=/tmp/test_source.db python3 -c "
import os
os.environ['ADMIN_USERNAME']='admin'
os.environ['ADMIN_PASSWORD']='test'
from database import init_db, _sync_conn
init_db()
c = _sync_conn()
# Check column exists
cols = [r['name'] for r in c.execute('PRAGMA table_info(agents)').fetchall()]
assert 'source_agent_id' in cols
print('OK: source_agent_id column exists')
c.close()
"
```

- [ ] **Step 3: Commit**

```bash
git add api/database.py
git commit -m "feat: add source_agent_id column to agents table for root/copy distinction"
```

---

### Task 2: API — add source_agent_id to model, root agents and copies endpoints

**Files:**
- Modify: `api/models.py`
- Modify: `api/admin.py`
- Modify: `api/permissions.py`

- [ ] **Step 0: Add source_agent_id to AgentOut**

In `api/models.py`, add to `AgentOut`:

```python
class AgentOut(BaseModel):
    id: str
    alias: str
    voice_id: str
    system_prompt: str
    owner_id: str
    source_agent_id: Optional[str] = None
    created_at: str
```

- [ ] **Step 1: Add root-agents and copies endpoints to admin.py**

Add these endpoints to `api/admin.py`:

```python
@router.get("/root-agents", response_model=list[AgentOut])
def list_root_agents(admin: dict = Depends(require_admin)):
    """List all root agents (source_agent_id IS NULL) with owner usernames."""
    db = _sync_conn()
    try:
        rows = db.execute("""
            SELECT a.* FROM agents a
            WHERE a.source_agent_id IS NULL
            ORDER BY a.created_at DESC
        """).fetchall()
        return [AgentOut(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/agents/{agent_id}/copies", response_model=list[AgentOut])
def list_agent_copies(agent_id: str, admin: dict = Depends(require_admin)):
    """List all copies of a root agent with owner info."""
    db = _sync_conn()
    try:
        # Verify agent exists and is a root
        root = db.execute(
            "SELECT id FROM agents WHERE id = ? AND source_agent_id IS NULL",
            (agent_id,),
        ).fetchone()
        if not root:
            raise HTTPException(status_code=404, detail="Root agent not found")

        rows = db.execute(
            "SELECT * FROM agents WHERE source_agent_id = ? ORDER BY created_at DESC",
            (agent_id,),
        ).fetchall()
        return [AgentOut(**dict(r)) for r in rows]
    finally:
        db.close()
```

Add `from fastapi import HTTPException` at the top of admin.py if not present.

- [ ] **Step 2: Update grant endpoint to set source_agent_id**

In `api/permissions.py`, in the `grant_permission` function, change the INSERT to include `source_agent_id`:

```python
db.execute(
    "INSERT INTO agents (id, alias, voice_id, system_prompt, owner_id, source_agent_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
    (copy_id, agent_row["alias"], agent_row["voice_id"], agent_row["system_prompt"], user_row["id"], agent_id, now),
)
```

Also update the revoke endpoint to delete by source_agent_id + owner:

```python
result = db.execute(
    "DELETE FROM agents WHERE source_agent_id = ? AND owner_id = ?",
    (agent_id, user_row["id"]),
)
```

- [ ] **Step 3: Commit**

```bash
git add api/admin.py api/permissions.py
git commit -m "feat: root-agents and copies endpoints, source_agent_id in grant"
```

---

### Task 3: API — delete user endpoint

**Files:**
- Modify: `api/admin.py`

- [ ] **Step 1: Add DELETE /api/admin/users/{username}**

```python
@router.delete("/users/{username}", status_code=204)
def delete_user(username: str, admin: dict = Depends(require_admin)):
    """Delete a user and all their agents. Cannot delete self."""
    if username == admin["username"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    db = _sync_conn()
    try:
        user_row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        # Delete user's agents first (FK cascade handles permissions)
        db.execute("DELETE FROM agents WHERE owner_id = ?", (user_row["id"],))
        db.execute("DELETE FROM users WHERE id = ?", (user_row["id"],))
        db.commit()
    finally:
        db.close()
    return None
```

- [ ] **Step 2: Commit**

```bash
git add api/admin.py
git commit -m "feat: delete user endpoint with cascade agent deletion"
```

---

### Task 4: API — update agents list to exclude copies + fix list_agents

**Files:**
- Modify: `api/agents.py`

- [ ] **Step 1: Fix GET /api/agents to only return root agents for admin, owned for users**

Update the `list_agents` function:

```python
@router.get("", response_model=list[AgentOut])
def list_agents(user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        if user["role"] == "admin":
            # Admin sees all root agents
            rows = db.execute(
                "SELECT * FROM agents WHERE source_agent_id IS NULL ORDER BY created_at DESC"
            ).fetchall()
        else:
            # Regular users see their own agents (roots they own + copies owned)
            rows = db.execute(
                "SELECT * FROM agents WHERE owner_id = ? ORDER BY created_at DESC",
                (user["id"],),
            ).fetchall()
        return [AgentOut(**dict(r)) for r in rows]
    finally:
        db.close()
```

- [ ] **Step 2: Commit**

```bash
git add api/agents.py
git commit -m "fix: agents list returns only root for admin, owned for users"
```

---

### Task 5: Rebuild API and verify new endpoints

**Files:** none (Docker rebuild)

- [ ] **Step 1: Rebuild and test**

```bash
docker compose up -d --build api

# Test root agents
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s http://localhost:8000/api/admin/root-agents -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

- [ ] **Step 2: Commit any fixes if needed**

---

### Task 6: Vue project scaffolding

**Files:**
- Create: `web-admin/` (entire Vue project)

- [ ] **Step 1: Create Vue project with Vite**

```bash
cd /Users/zhangfuzhen/Projects/call_me
npm create vite@latest web-admin -- --template vue
cd web-admin
npm install
npm install axios vue-router@4
```

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p src/views src/components
```

- [ ] **Step 3: Write src/api.js — Axios client with JWT**

```javascript
import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('admin_token');
      localStorage.removeItem('admin_user');
      window.location.hash = '#/login';
    }
    return Promise.reject(error);
  }
);

export default api;
```

- [ ] **Step 4: Write src/router.js**

```javascript
import { createRouter, createWebHashHistory } from 'vue-router';
import LoginView from './views/LoginView.vue';
import AgentListView from './views/AgentListView.vue';
import AgentDetailView from './views/AgentDetailView.vue';
import UserListView from './views/UserListView.vue';
import UserDetailView from './views/UserDetailView.vue';

const routes = [
  { path: '/login', component: LoginView },
  { path: '/', redirect: '/agents' },
  { path: '/agents', component: AgentListView },
  { path: '/agents/:id', component: AgentDetailView, props: true },
  { path: '/users', component: UserListView },
  { path: '/users/:username', component: UserDetailView, props: true },
];

const router = createRouter({ history: createWebHashHistory(), routes });

router.beforeEach((to) => {
  const token = localStorage.getItem('admin_token');
  if (to.path !== '/login' && !token) return '/login';
});

export default router;
```

- [ ] **Step 5: Write src/main.js**

```javascript
import { createApp } from 'vue';
import App from './App.vue';
import router from './router';
import './style.css';

createApp(App).use(router).mount('#app');
```

- [ ] **Step 6: Commit**

```bash
git add web-admin/
git commit -m "feat: Vue project scaffolding with router and API client"
```

---

### Task 7: Vue — App.vue layout + LoginView

**Files:**
- Create: `web-admin/src/App.vue`
- Create: `web-admin/src/views/LoginView.vue`
- Create: `web-admin/src/style.css`

- [ ] **Step 1: Write App.vue — sidebar layout**

```vue
<template>
  <div v-if="$route.path === '/login'">
    <router-view />
  </div>
  <div v-else class="layout">
    <aside class="sidebar">
      <h2 class="logo">call_me Admin</h2>
      <nav>
        <router-link to="/agents">Agent 管理</router-link>
        <router-link to="/users">用户管理</router-link>
      </nav>
      <div class="sidebar-footer">
        <span>{{ username }}</span>
        <button @click="logout">退出</button>
      </div>
    </aside>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
const router = useRouter();
const username = ref('');

onMounted(() => {
  username.value = localStorage.getItem('admin_user') || '';
});

function logout() {
  localStorage.removeItem('admin_token');
  localStorage.removeItem('admin_user');
  router.push('/login');
}
</script>
```

- [ ] **Step 2: Write LoginView.vue**

```vue
<template>
  <div class="login-page">
    <form @submit.prevent="login" class="login-form">
      <h1>call_me Admin</h1>
      <input v-model="form.username" placeholder="用户名" required />
      <input v-model="form.password" type="password" placeholder="密码" required />
      <p v-if="error" class="error">{{ error }}</p>
      <button type="submit" :disabled="loading">登录</button>
    </form>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import api from '../api.js';

const router = useRouter();
const form = reactive({ username: '', password: '' });
const loading = ref(false);
const error = ref('');

async function login() {
  loading.value = true;
  error.value = '';
  try {
    const r = await api.post('/auth/login', form);
    if (r.data.user.role !== 'admin') {
      error.value = '仅限管理员登录';
      return;
    }
    localStorage.setItem('admin_token', r.data.token);
    localStorage.setItem('admin_user', r.data.user.username);
    router.push('/agents');
  } catch (e) {
    error.value = e.response?.data?.detail || '登录失败';
  } finally {
    loading.value = false;
  }
}
</script>
```

- [ ] **Step 3: Write style.css**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f0f1a; color: #e0e0e0; }
.layout { display: flex; min-height: 100vh; }
.sidebar { width: 200px; background: #1a1a2e; padding: 20px; display: flex; flex-direction: column; }
.sidebar .logo { font-size: 18px; margin-bottom: 24px; color: #4a90d9; }
.sidebar nav a { display: block; padding: 10px 8px; color: #ccc; text-decoration: none; border-radius: 4px; margin-bottom: 4px; }
.sidebar nav a:hover, .sidebar nav a.router-link-active { background: #16213e; color: #fff; }
.sidebar-footer { margin-top: auto; display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: #888; }
.sidebar-footer button { background: none; border: 1px solid #666; color: #ccc; padding: 4px 12px; border-radius: 4px; cursor: pointer; }
.content { flex: 1; padding: 24px; }
.login-page { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.login-form { background: #1a1a2e; padding: 32px; border-radius: 8px; width: 320px; }
.login-form h1 { text-align: center; margin-bottom: 24px; color: #4a90d9; }
.login-form input { width: 100%; padding: 10px; margin-bottom: 12px; background: #0f0f1a; border: 1px solid #333; border-radius: 4px; color: #e0e0e0; }
.login-form button { width: 100%; padding: 10px; background: #4a90d9; border: none; border-radius: 4px; color: white; cursor: pointer; }
.login-form button:disabled { opacity: 0.5; }
.error { color: #e74c3c; font-size: 13px; margin-bottom: 8px; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 8px 12px; color: #888; font-size: 12px; border-bottom: 1px solid #333; }
td { padding: 8px 12px; font-size: 13px; border-bottom: 1px solid #222; }
.tag { display: inline-block; background: #2d2d2d; padding: 2px 8px; border-radius: 3px; margin-right: 4px; font-size: 12px; }
.tag .revoke { margin-left: 4px; cursor: pointer; color: #e74c3c; }
.btn { padding: 6px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-primary { background: #4a90d9; color: white; }
.btn-danger { background: none; border: 1px solid #e74c3c; color: #e74c3c; }
.btn-ghost { background: none; border: 1px solid #666; color: #ccc; padding: 4px 12px; border-radius: 3px; font-size: 12px; cursor: pointer; }
.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; }
.modal { background: #1a1a2e; padding: 24px; border-radius: 8px; min-width: 360px; }
.modal h3 { margin-bottom: 16px; }
.modal input, .modal textarea { width: 100%; padding: 8px; margin-bottom: 12px; background: #0f0f1a; border: 1px solid #333; border-radius: 4px; color: #e0e0e0; }
.modal textarea { min-height: 80px; resize: vertical; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { font-size: 20px; }
.back-link { color: #4a90d9; text-decoration: none; font-size: 13px; margin-bottom: 12px; display: inline-block; }
```

- [ ] **Step 4: Commit**

```bash
git add web-admin/src/
git commit -m "feat: App.vue layout, LoginView, and global styles"
```

---

### Task 8: Vue — AgentListView + AgentForm + GrantDialog

**Files:**
- Create: `web-admin/src/views/AgentListView.vue`
- Create: `web-admin/src/components/AgentForm.vue`
- Create: `web-admin/src/components/GrantDialog.vue`

- [ ] **Step 1: Write AgentListView.vue**

```vue
<template>
  <div>
    <div class="page-header">
      <h2>Agent 管理</h2>
      <button class="btn btn-primary" @click="showCreate = true">+ 创建 Agent</button>
    </div>
    <table>
      <thead><tr>
        <th>别名</th><th>音色</th><th>创建者</th><th>已授权用户</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="a in agents" :key="a.id">
          <td>{{ a.alias }}</td>
          <td style="color:#4a90d9;font-size:12px">{{ a.voice_id?.substring(0, 20) }}...</td>
          <td>{{ getOwnerName(a.owner_id) }}</td>
          <td>
            <span v-for="u in a.authorized_users" :key="u" class="tag">
              {{ u }} <span class="revoke" @click="revoke(a.id, u)">✕</span>
            </span>
            <span v-if="!a.authorized_users?.length" style="color:#888;font-size:12px">暂无</span>
          </td>
          <td>
            <button class="btn-ghost" @click="openGrant(a)">授权</button>
            <button class="btn-ghost" style="margin-left:4px" @click="$router.push(`/agents/${a.id}`)">详情</button>
            <button class="btn-ghost" style="margin-left:4px;color:#e74c3c" @click="del(a.id)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>

    <AgentForm v-if="showCreate" @close="showCreate = false" @saved="load" />

    <GrantDialog v-if="grantTarget" :agent="grantTarget" @close="grantTarget = null" @done="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';
import AgentForm from '../components/AgentForm.vue';
import GrantDialog from '../components/GrantDialog.vue';

const agents = ref([]);
const showCreate = ref(false);
const grantTarget = ref(null);

async function load() {
  try {
    const [r1, r2] = await Promise.all([
      api.get('/admin/root-agents'),
      api.get('/admin/users'),
    ]);
    const users = r2.data;
    // Attach authorized user info to each agent
    for (const a of r1.data) {
      const copies = await api.get(`/admin/agents/${a.id}/copies`);
      a.authorized_users = copies.data.map(c => users.find(u => u.id === c.owner_id)?.username || '?');
    }
    agents.value = r1.data;
  } catch (e) { console.error(e); }
}

function getOwnerName(oid) {
  return oid === agents.value.find(a => a.owner_id === oid)?.owner_id ? 'admin' : 'user';
}

async function revoke(agentId, username) {
  if (!confirm(`Revoke ${username}'s access?`)) return;
  await api.delete(`/agents/${agentId}/grant/${username}`);
  await load();
}

async function del(id) {
  if (!confirm('Delete this agent and all copies?')) return;
  await api.delete(`/agents/${id}`);
  await load();
}

function openGrant(a) { grantTarget.value = a; }

onMounted(load);
</script>
```

- [ ] **Step 2: Write AgentForm.vue**

```vue
<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <form class="modal" @submit.prevent="submit">
      <h3>{{ editId ? '编辑' : '创建' }} Agent</h3>
      <input v-model="alias" placeholder="别名" required />
      <textarea v-model="systemPrompt" placeholder="人设描述 (system prompt)"></textarea>
      <input v-if="!editId" type="file" accept="audio/*" @change="onFile" required />
      <p v-if="error" class="error">{{ error }}</p>
      <div class="modal-actions">
        <button type="button" class="btn-ghost" @click="$emit('close')">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="loading">
          {{ loading ? '保存中...' : '保存' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import api from '../api.js';

const props = defineProps({ editId: String, editAlias: String, editPrompt: String });
const emit = defineEmits(['close', 'saved']);

const alias = ref(props.editAlias || '');
const systemPrompt = ref(props.editPrompt || '');
const file = ref(null);
const loading = ref(false);
const error = ref('');

function onFile(e) { file.value = e.target.files[0]; }

async function submit() {
  loading.value = true;
  error.value = '';
  try {
    if (props.editId) {
      await api.patch(`/agents/${props.editId}`, { alias: alias.value, system_prompt: systemPrompt.value });
    } else {
      const fd = new FormData();
      fd.append('alias', alias.value);
      fd.append('system_prompt', systemPrompt.value);
      fd.append('audio_file', file.value);
      await api.post('/agents', fd);
    }
    emit('saved');
    emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed';
  } finally {
    loading.value = false;
  }
}
</script>
```

- [ ] **Step 3: Write GrantDialog.vue**

```vue
<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal">
      <h3>授权 "{{ agent.alias }}"</h3>
      <input v-model="username" placeholder="输入用户名" />
      <p v-if="error" class="error">{{ error }}</p>
      <div class="modal-actions">
        <button class="btn-ghost" @click="$emit('close')">取消</button>
        <button class="btn btn-primary" @click="grant" :disabled="loading">授权</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import api from '../api.js';

const props = defineProps({ agent: Object });
const emit = defineEmits(['close', 'done']);

const username = ref('');
const loading = ref(false);
const error = ref('');

async function grant() {
  if (!username.value.trim()) return;
  loading.value = true;
  error.value = '';
  try {
    await api.post(`/agents/${props.agent.id}/grant`, { username: username.value.trim() });
    emit('done');
    emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || '授权失败';
  } finally {
    loading.value = false;
  }
}
</script>
```

- [ ] **Step 4: Commit**

```bash
git add web-admin/src/views/AgentListView.vue web-admin/src/components/
git commit -m "feat: AgentListView with create, grant, revoke, delete"
```

---

### Task 9: Vue — AgentDetailView + UserListView + UserDetailView

**Files:**
- Create: `web-admin/src/views/AgentDetailView.vue`
- Create: `web-admin/src/views/UserListView.vue`
- Create: `web-admin/src/views/UserDetailView.vue`

- [ ] **Step 1: Write AgentDetailView.vue**

```vue
<template>
  <div>
    <router-link to="/agents" class="back-link">← 返回列表</router-link>
    <div class="page-header">
      <h2>{{ agent.alias }} 的授权详情</h2>
      <button class="btn btn-primary" @click="showGrant = true">+ 授权给新用户</button>
    </div>
    <p style="color:#888;font-size:13px;margin-bottom:16px">
      音色: {{ agent.voice_id }} | 人设: {{ agent.system_prompt }}
    </p>
    <table>
      <thead><tr>
        <th>授权用户</th><th>自定义人设</th><th>授权时间</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="c in copies" :key="c.id">
          <td>{{ getUserName(c.owner_id) }}</td>
          <td style="color:#888;max-width:300px">{{ c.system_prompt }}</td>
          <td style="color:#888;font-size:12px">{{ c.created_at?.substring(0, 10) }}</td>
          <td>
            <button class="btn-ghost" style="color:#e74c3c" @click="revoke(c.owner_id)">回收授权</button>
          </td>
        </tr>
        <tr v-if="!copies.length">
          <td colspan="4" style="color:#888;text-align:center;padding:24px">暂无授权</td>
        </tr>
      </tbody>
    </table>

    <GrantDialog v-if="showGrant" :agent="agent" @close="showGrant = false" @done="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import api from '../api.js';
import GrantDialog from '../components/GrantDialog.vue';

const route = useRoute();
const agent = ref({});
const copies = ref([]);
const users = ref([]);
const showGrant = ref(false);

async function load() {
  const id = route.params.id;
  const [r1, r2, r3] = await Promise.all([
    api.get(`/agents/${id}`),
    api.get(`/admin/agents/${id}/copies`),
    api.get('/admin/users'),
  ]);
  agent.value = r1.data;
  copies.value = r2.data;
  users.value = r3.data;
}

function getUserName(uid) {
  return users.value.find(u => u.id === uid)?.username || uid?.substring(0, 8);
}

async function revoke(ownerId) {
  if (!confirm('Revoke?')) return;
  const username = getUserName(ownerId);
  await api.delete(`/agents/${agent.value.id}/grant/${username}`);
  await load();
}

onMounted(load);
</script>
```

- [ ] **Step 2: Write UserListView.vue**

```vue
<template>
  <div>
    <div class="page-header"><h2>用户管理</h2></div>
    <table>
      <thead><tr>
        <th>用户名</th><th>角色</th><th>拥有 Agent</th><th>注册时间</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.username }}</td>
          <td>{{ u.role === 'admin' ? '管理员' : '用户' }}</td>
          <td>
            <span v-for="a in u.agents" :key="a.id" class="tag">
              {{ a.alias }} <span class="revoke" @click="revoke(a, u.username)">✕</span>
            </span>
            <span v-if="!u.agents?.length" style="color:#888;font-size:12px">无</span>
          </td>
          <td style="color:#888;font-size:12px">{{ u.created_at?.substring(0, 10) }}</td>
          <td>
            <button class="btn-ghost" @click="$router.push(`/users/${u.username}`)">详情</button>
            <button v-if="u.role !== 'admin'" class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(u.username)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';

const users = ref([]);

async function load() {
  const [r1, r2] = await Promise.all([
    api.get('/admin/users'),
    api.get('/admin/agents'),
  ]);
  const agents = r2.data;
  users.value = r1.data.map(u => ({
    ...u,
    agents: agents.filter(a => a.owner_id === u.id),
  }));
}

async function revoke(agent, username) {
  if (!confirm(`Revoke ${agent.alias} from ${username}?`)) return;
  // Find the root agent for this copy
  await api.delete(`/agents/${agent.source_agent_id || agent.id}/grant/${username}`);
  await load();
}

async function del(username) {
  if (!confirm(`Delete user "${username}" and all their agents?`)) return;
  await api.delete(`/admin/users/${username}`);
  await load();
}

onMounted(load);
</script>
```

- [ ] **Step 3: Write UserDetailView.vue**

```vue
<template>
  <div>
    <router-link to="/users" class="back-link">← 返回列表</router-link>
    <div class="page-header"><h2>{{ username }} 的 Agent</h2></div>
    <table>
      <thead><tr>
        <th>别名</th><th>音色</th><th>自定义人设</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="a in agents" :key="a.id">
          <td>{{ a.alias }}</td>
          <td style="color:#4a90d9;font-size:12px">{{ a.voice_id?.substring(0, 25) }}...</td>
          <td style="color:#888;max-width:300px">{{ a.system_prompt }}</td>
          <td>
            <button class="btn-ghost" style="color:#e74c3c" @click="revoke(a)">回收</button>
          </td>
        </tr>
        <tr v-if="!agents.length">
          <td colspan="4" style="color:#888;text-align:center;padding:24px">暂无 Agent</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import api from '../api.js';

const route = useRoute();
const username = route.params.username;
const agents = ref([]);

async function load() {
  const r = await api.get(`/admin/users/${username}/agents`);
  agents.value = r.data;
}

async function revoke(agent) {
  if (!confirm(`Revoke ${agent.alias}?`)) return;
  await api.delete(`/agents/${agent.source_agent_id || agent.id}/grant/${username}`);
  await load();
}

onMounted(load);
</script>
```

- [ ] **Step 4: Commit**

```bash
git add web-admin/src/views/
git commit -m "feat: AgentDetailView, UserListView, UserDetailView"
```

---

### Task 10: Deployment — serve Vue from FastAPI

**Files:**
- Modify: `api/main.py`
- Modify: `api/Dockerfile`

- [ ] **Step 1: Update api/main.py to serve static files**

Add at the end of main.py:

```python
from fastapi.staticfiles import StaticFiles
import os

# Serve web admin static files if built
static_dir = os.path.join(os.path.dirname(__file__), "..", "web-admin", "dist")
if os.path.isdir(static_dir):
    app.mount("/admin", StaticFiles(directory=static_dir, html=True), name="admin")
```

- [ ] **Step 2: Update api/main.py to mount static files on /admin**

```python
from fastapi.staticfiles import StaticFiles
import os

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/admin", StaticFiles(directory=static_dir, html=True), name="admin")
```

**Step 3: Update docker-compose.yml to mount Vue dist**

```yaml
  api:
    build: ./api
    ports: ["8000:8000"]
    env_file: .env
    volumes:
      - api_data:/data
      - ./web-admin/dist:/app/static
```

**Step 4: Build Vue locally, then rebuild Docker**

```bash
cd web-admin && npm run build
cd .. && docker compose up -d --build api

- [ ] **Step 3: Build Vue and test**

```bash
cd web-admin && npm run build
cd .. && docker compose up -d --build api
curl -s http://localhost:8000/admin | head -5
```

- [ ] **Step 4: Commit**

```bash
git add api/main.py api/Dockerfile docker-compose.yml
git commit -m "feat: serve Vue admin from FastAPI static files"
```

---

### Task 11: End-to-end verification

- [ ] **Step 1: Test all API endpoints**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

echo "Root agents:"; curl -s http://localhost:8000/api/admin/root-agents -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"

echo "Users:"; curl -s http://localhost:8000/api/admin/users -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"

echo "Vue app:"; curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/admin
echo ""
```

- [ ] **Step 2: Manual browser test**

Open `http://localhost:8000/admin` → login as admin → verify agent list shows → create agent → grant to user → user list shows → revoke works.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "chore: integration fixes from web admin testing"
```

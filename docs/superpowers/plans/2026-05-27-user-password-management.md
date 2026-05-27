# User Password Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add create user, change admin password, and reset user password features to the web admin panel via modal dialogs.

**Architecture:** Three new API endpoints (one in auth.py, two in admin.py) + three Pydantic models (models.py) + frontend modals in UserListView.vue and App.vue. All password operations use bcrypt via existing `pwd_context`.

**Tech Stack:** FastAPI (Python), Vue 3 + Vue Router, SQLite, axios

---

### Task 1: Add Pydantic models for password management

**Files:**
- Modify: `api/models.py`

- [ ] **Step 1: Add three new models to models.py**

Insert after the `UserLogin` class (line 23):

```python
class AdminCreateUser(BaseModel):
    username: str
    password: str = "aB@12345"


class ChangePassword(BaseModel):
    old_password: str
    new_password: str


class AdminResetPassword(BaseModel):
    new_password: str = "aB@12345"
```

- [ ] **Step 2: Commit**

```bash
git add api/models.py
git commit -m "feat: add Pydantic models for password management"
```

---

### Task 2: Add change-password endpoint for logged-in user

**Files:**
- Modify: `api/auth.py`

- [ ] **Step 1: Add endpoint at end of auth.py**

```python
@router.put("/change-password", status_code=204)
def change_password(body: ChangePassword, user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or not pwd_context.verify(body.old_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="旧密码错误")

        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (pwd_context.hash(body.new_password), user["id"]),
        )
        db.commit()
    finally:
        db.close()
    return None
```

Requires importing `ChangePassword` at the top. Update the import line:
```
from models import UserRegister, UserLogin, AuthResponse, UserOut, ChangePassword
```

- [ ] **Step 2: Commit**

```bash
git add api/auth.py
git commit -m "feat: add PUT /api/auth/change-password endpoint"
```

---

### Task 3: Add admin create-user and reset-password endpoints

**Files:**
- Modify: `api/admin.py`

- [ ] **Step 1: Update imports in admin.py**

Replace the models import line:
```python
from models import UserOut, AgentOut, CallLogOut, CallLogListResponse, StatsOverview, StatsTrendItem, StatsTopItem, AdminCreateUser, AdminResetPassword
```

Add `uuid` and `datetime` and `pwd_context` imports at top:
```python
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import _sync_conn, pwd_context
from models import UserOut, AgentOut, CallLogOut, CallLogListResponse, StatsOverview, StatsTrendItem, StatsTopItem, AdminCreateUser, AdminResetPassword
from auth import require_admin
```

Wait — `_sync_conn` is already imported. Just add `pwd_context` to existing import and add new models.

- [ ] **Step 2: Add POST /api/admin/users endpoint**

Insert after the `list_users` function (before `list_all_agents`):

```python
@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: AdminCreateUser, admin: dict = Depends(require_admin)):
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")

    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="用户名已存在")

        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, pwd_context.hash(body.password), "user", now),
        )
        db.commit()
        return UserOut(id=user_id, username=username, role="user", created_at=now)
    finally:
        db.close()
```

- [ ] **Step 3: Add PUT /api/admin/users/{username}/reset-password endpoint**

Insert after the `delete_user` function:

```python
@router.put("/users/{username}/reset-password", status_code=204)
def reset_user_password(username: str, body: AdminResetPassword, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        user_row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="用户不存在")

        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (pwd_context.hash(body.new_password), user_row["id"]),
        )
        db.commit()
    finally:
        db.close()
    return None
```

- [ ] **Step 4: Commit**

```bash
git add api/admin.py
git commit -m "feat: add admin create user and reset password endpoints"
```

---

### Task 4: Write API tests

**Files:**
- Create: `api/tests/test_password_management.py`

- [ ] **Step 1: Write the test file**

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _register_and_login(username="alice", password="secret123"):
    client.post("/api/auth/register", json={"username": username, "password": password})
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    return resp.json()["token"]


def _admin_header():
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


class TestChangePassword:
    def test_change_password_success(self, clean_db):
        token = _register_and_login("eve", "oldpass")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.put("/api/auth/change-password", json={
            "old_password": "oldpass", "new_password": "newpass"
        }, headers=headers)
        assert resp.status_code == 204

        # Verify can login with new password
        login_resp = client.post("/api/auth/login", json={"username": "eve", "password": "newpass"})
        assert login_resp.status_code == 200

        # Verify old password no longer works
        login_resp2 = client.post("/api/auth/login", json={"username": "eve", "password": "oldpass"})
        assert login_resp2.status_code == 401

    def test_change_password_wrong_old_password(self, clean_db):
        token = _register_and_login("frank", "correct")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.put("/api/auth/change-password", json={
            "old_password": "wrong", "new_password": "newpass"
        }, headers=headers)
        assert resp.status_code == 400
        assert "旧密码错误" in resp.json()["detail"]

    def test_change_password_requires_auth(self, clean_db):
        resp = client.put("/api/auth/change-password", json={
            "old_password": "x", "new_password": "y"
        })
        assert resp.status_code == 401


class TestAdminCreateUser:
    def test_create_user_success(self, clean_db):
        resp = client.post("/api/admin/users", json={
            "username": "newuser", "password": "aB@12345"
        }, headers=_admin_header())
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "user"

    def test_create_user_default_password(self, clean_db):
        resp = client.post("/api/admin/users", json={
            "username": "defaultpwuser"
        }, headers=_admin_header())
        assert resp.status_code == 201

        # Verify can login with default password
        login_resp = client.post("/api/auth/login", json={
            "username": "defaultpwuser", "password": "aB@12345"
        })
        assert login_resp.status_code == 200

    def test_create_user_duplicate_username(self, clean_db):
        client.post("/api/admin/users", json={"username": "dup"}, headers=_admin_header())
        resp = client.post("/api/admin/users", json={"username": "dup"}, headers=_admin_header())
        assert resp.status_code == 409
        assert "用户名已存在" in resp.json()["detail"]

    def test_create_user_empty_username(self, clean_db):
        resp = client.post("/api/admin/users", json={"username": "  "}, headers=_admin_header())
        assert resp.status_code == 400

    def test_create_user_requires_admin(self, clean_db):
        token = _register_and_login("bob", "pw")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.post("/api/admin/users", json={"username": "hack"}, headers=headers)
        assert resp.status_code == 403


class TestAdminResetPassword:
    def test_reset_password_success(self, clean_db):
        token = _register_and_login("carol", "oldpw")
        resp = client.put("/api/admin/users/carol/reset-password", json={
            "new_password": "resetpw"
        }, headers=_admin_header())
        assert resp.status_code == 204

        # Verify old password fails
        old = client.post("/api/auth/login", json={"username": "carol", "password": "oldpw"})
        assert old.status_code == 401

        # Verify new password works
        new = client.post("/api/auth/login", json={"username": "carol", "password": "resetpw"})
        assert new.status_code == 200

    def test_reset_password_default_value(self, clean_db):
        _register_and_login("dave", "original")
        resp = client.put("/api/admin/users/dave/reset-password", json={}, headers=_admin_header())
        assert resp.status_code == 204

        login = client.post("/api/auth/login", json={"username": "dave", "password": "aB@12345"})
        assert login.status_code == 200

    def test_reset_password_user_not_found(self, clean_db):
        resp = client.put("/api/admin/users/ghost/reset-password", json={
            "new_password": "x"
        }, headers=_admin_header())
        assert resp.status_code == 404

    def test_reset_password_requires_admin(self, clean_db):
        token = _register_and_login("eve", "pw")
        headers = {"Authorization": f"Bearer {token}"}
        _register_and_login("target", "pw")
        resp = client.put("/api/admin/users/target/reset-password", json={
            "new_password": "x"
        }, headers=headers)
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests**

```bash
cd api && python3 -m pytest tests/test_password_management.py -v
```

Expected: All 10 tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/tests/test_password_management.py
git commit -m "test: add tests for password management endpoints"
```

---

### Task 5: Add create user and reset password modals to UserListView

**Files:**
- Modify: `web-admin/src/views/UserListView.vue`

- [ ] **Step 1: Replace the template section**

```vue
<template>
  <div>
    <div class="page-header">
      <h2>用户管理</h2>
      <button class="btn-primary" @click="openCreate">+ 创建用户</button>
    </div>

    <!-- Create User Modal -->
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal">
        <h3>创建用户</h3>
        <p class="modal-subtitle">新用户角色默认为 user，默认密码 aB@12345</p>
        <input v-model="createForm.username" placeholder="输入用户名" @keyup.enter="doCreate">
        <input v-model="createForm.password" type="text">
        <div class="modal-actions">
          <button class="btn-ghost" @click="showCreate = false" :disabled="creating">取消</button>
          <button class="btn-primary" @click="doCreate" :disabled="creating">{{ creating ? '创建中...' : '确认创建' }}</button>
        </div>
        <p v-if="createError" class="error">{{ createError }}</p>
      </div>
    </div>

    <!-- Reset Password Modal -->
    <div v-if="showReset" class="modal-overlay" @click.self="showReset = false">
      <div class="modal">
        <h3>重置用户密码</h3>
        <p class="modal-subtitle">为用户 <strong>{{ resetTarget }}</strong> 设置新密码</p>
        <input v-model="resetForm.new_password" type="text" @keyup.enter="doReset">
        <div class="modal-actions">
          <button class="btn-ghost" @click="showReset = false" :disabled="resetting">取消</button>
          <button class="btn-primary" @click="doReset" :disabled="resetting">{{ resetting ? '重置中...' : '确认重置' }}</button>
        </div>
        <p v-if="resetError" class="error">{{ resetError }}</p>
      </div>
    </div>

    <!-- Success Toast -->
    <div v-if="toast" class="toast">{{ toast }}</div>

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
          <td style="color:#888;font-size:12px">{{ (u.created_at || '').substring(0, 10) }}</td>
          <td>
            <button class="btn-ghost" @click="$router.push(`/users/${u.username}`)">详情</button>
            <button class="btn-ghost" @click="openReset(u)">重置密码</button>
            <button v-if="u.role !== 'admin'" class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(u)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
```

- [ ] **Step 2: Replace the script section**

```vue
<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';

const users = ref([]);

const showCreate = ref(false);
const creating = ref(false);
const createError = ref('');
const createForm = ref({ username: '', password: 'aB@12345' });

const showReset = ref(false);
const resetting = ref(false);
const resetError = ref('');
const resetTarget = ref('');
const resetForm = ref({ new_password: 'aB@12345' });

const toast = ref('');

function showToast(msg) {
  toast.value = msg;
  setTimeout(() => { toast.value = ''; }, 3000);
}

async function load() {
  const [r1, r2] = await Promise.all([
    api.get('/admin/users'),
    api.get('/admin/agents'),
  ]);
  const allAgents = r2.data;
  users.value = r1.data.map(u => ({
    ...u,
    agents: allAgents.filter(a => a.owner_id === u.id),
  }));
}

function openCreate() {
  createForm.value = { username: '', password: 'aB@12345' };
  createError.value = '';
  showCreate.value = true;
}

async function doCreate() {
  createError.value = '';
  if (!createForm.value.username.trim()) {
    createError.value = '用户名不能为空';
    return;
  }
  creating.value = true;
  try {
    await api.post('/admin/users', createForm.value);
    showCreate.value = false;
    showToast('用户创建成功');
    await load();
  } catch (e) {
    createError.value = e.response?.data?.detail || '创建失败';
  } finally {
    creating.value = false;
  }
}

function openReset(user) {
  resetTarget.value = user.username;
  resetForm.value = { new_password: 'aB@12345' };
  resetError.value = '';
  showReset.value = true;
}

async function doReset() {
  resetError.value = '';
  resetting.value = true;
  try {
    await api.put(`/admin/users/${encodeURIComponent(resetTarget.value)}/reset-password`, resetForm.value);
    showReset.value = false;
    showToast(`${resetTarget.value} 密码已重置`);
  } catch (e) {
    resetError.value = e.response?.data?.detail || '重置失败';
  } finally {
    resetting.value = false;
  }
}

async function revoke(agent, username) {
  if (!confirm(`Revoke ${agent.alias} from ${username}?`)) return;
  const rootId = agent.source_agent_id || agent.id;
  await api.delete(`/agents/${rootId}/grant/${username}`);
  await load();
}

async function del(user) {
  const name = user.username;
  if (!name || user.role === 'admin') return;
  if (!confirm(`Delete user "${name}" and all their agents?`)) return;
  await api.delete(`/admin/users/${encodeURIComponent(name)}`);
  await load();
}

onMounted(load);
</script>
```

- [ ] **Step 3: Verify the page builds**

```bash
cd web-admin && npm run build
```

Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web-admin/src/views/UserListView.vue
git commit -m "feat: add create user and reset password modals to user list"
```

---

### Task 6: Add change-password modal to App.vue

**Files:**
- Modify: `web-admin/src/App.vue`

- [ ] **Step 1: Replace the template section**

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
        <router-link to="/model-configs">LLM模型</router-link>
        <router-link to="/tts-configs">TTS 模型</router-link>
        <router-link to="/voices">声音库</router-link>
        <router-link to="/api-keys">API Keys</router-link>
        <router-link to="/call-logs">通话记录</router-link>
        <router-link to="/stats">数据统计</router-link>
      </nav>
      <div class="sidebar-footer">
        <span>{{ username }}</span>
        <button @click="openChangePassword">修改密码</button>
        <button @click="logout">退出</button>
      </div>
    </aside>
    <main class="content">
      <router-view />
    </main>

    <!-- Change Password Modal -->
    <div v-if="showChangePassword" class="modal-overlay" @click.self="showChangePassword = false">
      <div class="modal">
        <h3>修改管理员密码</h3>
        <input v-model="changePwForm.old_password" type="password" placeholder="输入当前密码">
        <input v-model="changePwForm.new_password" type="password" placeholder="输入新密码">
        <input v-model="confirmNewPassword" type="password" placeholder="再次输入新密码">
        <div class="modal-actions">
          <button class="btn-ghost" @click="showChangePassword = false" :disabled="changing">取消</button>
          <button class="btn-primary" @click="doChangePassword" :disabled="changing">{{ changing ? '修改中...' : '确认修改' }}</button>
        </div>
        <p v-if="changePwError" class="error">{{ changePwError }}</p>
      </div>
    </div>

    <!-- Success Toast -->
    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>
```

- [ ] **Step 2: Replace the script section**

```vue
<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import api from './api.js';

const router = useRouter();
const username = ref('');

const showChangePassword = ref(false);
const changing = ref(false);
const changePwError = ref('');
const changePwForm = ref({ old_password: '', new_password: '' });
const confirmNewPassword = ref('');
const toast = ref('');

function showToast(msg) {
  toast.value = msg;
  setTimeout(() => { toast.value = ''; }, 3000);
}

onMounted(() => {
  username.value = localStorage.getItem('admin_user') || '';
});

function openChangePassword() {
  changePwForm.value = { old_password: '', new_password: '' };
  confirmNewPassword.value = '';
  changePwError.value = '';
  showChangePassword.value = true;
}

async function doChangePassword() {
  changePwError.value = '';
  if (changePwForm.value.new_password !== confirmNewPassword.value) {
    changePwError.value = '两次输入的新密码不一致';
    return;
  }
  changing.value = true;
  try {
    await api.put('/auth/change-password', changePwForm.value);
    showChangePassword.value = false;
    showToast('密码修改成功');
  } catch (e) {
    changePwError.value = e.response?.data?.detail || '修改失败';
  } finally {
    changing.value = false;
  }
}

function logout() {
  localStorage.removeItem('admin_token');
  localStorage.removeItem('admin_user');
  router.push('/login');
}
</script>
```

- [ ] **Step 3: Verify the build**

```bash
cd web-admin && npm run build
```

Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web-admin/src/App.vue
git commit -m "feat: add change password modal to admin header"
```

---

### Task 7: Add missing CSS styles

**Files:**
- Modify: `web-admin/src/style.css`

- [ ] **Step 1: Append missing styles to style.css**

The existing CSS already has `.modal-overlay`, `.modal`, `.modal input`, `.modal-actions`, `.page-header`, `.btn-primary`, `.btn-ghost`, and `.error`. Only add what's missing:

```css
.modal-subtitle { color: #94a3b8; font-size: 13px; margin: 0 0 12px 0; }
.btn-primary:hover { background: #3a7bc8; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.toast { position: fixed; top: 20px; right: 20px; background: #10b981; color: #fff;
  padding: 10px 20px; border-radius: 6px; font-size: 14px; z-index: 2000;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
```

- [ ] **Step 2: Verify build**

```bash
cd web-admin && npm run build
```

Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add web-admin/src/style.css
git commit -m "style: add modal-subtitle, toast, and btn-primary hover/disabled CSS"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run all API tests**

```bash
cd api && python3 -m pytest tests/ -v
```

Expected: All 41 tests pass (31 existing + 10 new).

- [ ] **Step 2: Verify full build**

```bash
cd web-admin && npm run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 3: Commit any remaining changes**

Only if there are uncommitted changes from verification.

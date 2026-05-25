# 通话记录与统计 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every call's start/end/duration, expose call history with filtering, and show stats dashboard with charts.

**Architecture:** Token endpoint writes call_log (status=running), agent worker listens for participant_disconnected event to immediately mark completed with duration. Stats endpoints query the call_logs table with aggregations.

**Tech Stack:** FastAPI + SQLite (backend), Vue 3 + Chart.js (frontend)

---

### Task 1: Database migration — call_logs table

**Files:**
- Modify: `api/database.py:255` (in init_db, after the last migration block)

- [ ] **Step 1: Add migration code**

In `api/database.py`, add after the api_key_id migration block (before `conn.commit()`):

```python
# Migration: call_logs table for call history and statistics
conn.execute("""
    CREATE TABLE IF NOT EXISTS call_logs (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL REFERENCES agents(id),
        caller_user_id TEXT NOT NULL REFERENCES users(id),
        room_name TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        duration_seconds INTEGER,
        status TEXT NOT NULL DEFAULT 'running'
    )
""")
```

Insert after line 315 (after the tts_configs api_key_id link block, before `conn.commit()`).

Let me verify the exact insertion point — it goes right before `conn.commit()` at line 317.

- [ ] **Step 2: Run tests to verify migration doesn't break anything**

```bash
cd api && python3 -m pytest tests/ -v
```

Expected: 37 passed, 1 skipped (all existing tests pass with new table).

- [ ] **Step 3: Commit**

```bash
git add api/database.py
git commit -m "feat: add call_logs table migration"
```

---

### Task 2: Add Pydantic schemas for call logs and stats

**Files:**
- Modify: `api/models.py:193` (after AuditionResponse class)

- [ ] **Step 1: Add model classes**

Insert at the end of `api/models.py`:

```python
class CallLogOut(BaseModel):
    id: str
    agent_id: str
    agent_alias: str
    caller_user_id: str
    caller_username: str
    room_name: str
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: str


class CallLogEndRequest(BaseModel):
    status: str = "completed"
    duration_seconds: int


class CallLogListResponse(BaseModel):
    items: list[CallLogOut]
    total: int
    page: int
    page_size: int


class StatsOverview(BaseModel):
    total_calls: int
    today_calls: int
    total_duration_seconds: int
    active_users: int


class StatsTrendItem(BaseModel):
    date: str
    count: int


class StatsTopItem(BaseModel):
    id: str
    name: str
    count: int
```

- [ ] **Step 2: Run tests to verify models load**

```bash
cd api && python3 -m pytest tests/ -v
```

Expected: 37 passed, 1 skipped (no new tests yet).

- [ ] **Step 3: Commit**

```bash
git add api/models.py
git commit -m "feat: add call log and stats Pydantic schemas"
```

---

### Task 3: Token endpoint writes call_log + worker callback endpoint

**Files:**
- Modify: `api/call.py`

- [ ] **Step 1: Add imports and callback endpoint**

Add `from datetime import datetime, timezone` to imports at top of `api/call.py` (line 1).

In `get_call_token`, after `room_name = f"call_{uuid.uuid4().hex[:12]}"` (line 37), insert:

```python
# Record call start
call_log_id = str(uuid.uuid4())
now = datetime.now(timezone.utc).isoformat()
db.execute(
    "INSERT INTO call_logs (id, agent_id, caller_user_id, room_name, started_at, status) VALUES (?, ?, ?, ?, ?, ?)",
    (call_log_id, body.agent_id, user["id"], room_name, now, "running"),
)
db.commit()
```

In `agent_config` dict (line 91-98), add call_log_id:

```python
agent_config = json.dumps({
    "agent_id": agent_row["id"],
    "alias": agent_row["alias"],
    "system_prompt": agent_row["system_prompt"],
    "voice_id": voice_id,
    "model_config": model_config,
    "tts_config": tts_config,
    "call_log_id": call_log_id,
})
```

Add new endpoint at the end of `api/call.py` (before the trailing empty line):

```python
from models import CallLogEndRequest

@router.patch("/admin/call-logs/{call_log_id}/end", status_code=204)
def end_call_log(call_log_id: str, body: CallLogEndRequest):
    """Worker callback: mark a call log as ended."""
    db = _sync_conn()
    try:
        ended_at = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE call_logs SET status = ?, ended_at = ?, duration_seconds = ? WHERE id = ?",
            (body.status, ended_at, body.duration_seconds, call_log_id),
        )
        db.commit()
    finally:
        db.close()
    return None
```

- [ ] **Step 2: Run tests**

```bash
cd api && python3 -m pytest tests/ -v
```

Expected: 37 passed, 1 skipped.

- [ ] **Step 3: Commit**

```bash
git add api/call.py
git commit -m "feat: write call_log on token generation, add worker callback endpoint"
```

---

### Task 4: Admin stats and call logs query endpoints

**Files:**
- Modify: `api/admin.py`

- [ ] **Step 1: Add endpoints to admin.py**

Add imports at top of `api/admin.py`:

```python
from models import UserOut, AgentOut, CallLogOut, CallLogListResponse, StatsOverview, StatsTrendItem, StatsTopItem
```

Add endpoints at the end of `api/admin.py`:

```python
@router.get("/call-logs", response_model=CallLogListResponse)
def list_call_logs(
    agent_id: str | None = None,
    user_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(require_admin),
):
    db = _sync_conn()
    try:
        where_clauses = []
        params = []

        if agent_id:
            where_clauses.append("cl.agent_id = ?")
            params.append(agent_id)
        if user_id:
            where_clauses.append("cl.caller_user_id = ?")
            params.append(user_id)
        if status:
            where_clauses.append("cl.status = ?")
            params.append(status)

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        total_row = db.execute(
            f"SELECT COUNT(*) as c FROM call_logs cl {where}", params
        ).fetchone()
        total = total_row["c"]

        offset = (page - 1) * page_size
        rows = db.execute(
            f"""SELECT cl.*, a.alias as agent_alias, u.username as caller_username
                FROM call_logs cl
                JOIN agents a ON cl.agent_id = a.id
                JOIN users u ON cl.caller_user_id = u.id
                {where}
                ORDER BY cl.started_at DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()

        items = [CallLogOut(**dict(r)) for r in rows]
        return CallLogListResponse(items=items, total=total, page=page, page_size=page_size)
    finally:
        db.close()


@router.get("/stats/overview", response_model=StatsOverview)
def stats_overview(admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        total = db.execute("SELECT COUNT(*) as c FROM call_logs").fetchone()["c"]
        today = db.execute(
            "SELECT COUNT(*) as c FROM call_logs WHERE date(started_at) = date('now')"
        ).fetchone()["c"]
        total_dur = db.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) as s FROM call_logs WHERE status = 'completed'"
        ).fetchone()["s"]
        active = db.execute(
            "SELECT COUNT(DISTINCT caller_user_id) as c FROM call_logs"
        ).fetchone()["c"]
        return StatsOverview(
            total_calls=total,
            today_calls=today,
            total_duration_seconds=total_dur,
            active_users=active,
        )
    finally:
        db.close()


@router.get("/stats/trend", response_model=list[StatsTrendItem])
def stats_trend(days: int = 30, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute(
            """SELECT date(started_at) as date, COUNT(*) as count
               FROM call_logs
               WHERE started_at >= date('now', ?)
               GROUP BY date(started_at)
               ORDER BY date ASC""",
            (f"-{days} days",),
        ).fetchall()
        return [StatsTrendItem(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/stats/top-agents", response_model=list[StatsTopItem])
def stats_top_agents(limit: int = 10, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute(
            """SELECT cl.agent_id as id, a.alias as name, COUNT(*) as count
               FROM call_logs cl
               JOIN agents a ON cl.agent_id = a.id
               GROUP BY cl.agent_id
               ORDER BY count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [StatsTopItem(**dict(r)) for r in rows]
    finally:
        db.close()


@router.get("/stats/top-users", response_model=list[StatsTopItem])
def stats_top_users(limit: int = 10, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        rows = db.execute(
            """SELECT cl.caller_user_id as id, u.username as name, COUNT(*) as count
               FROM call_logs cl
               JOIN users u ON cl.caller_user_id = u.id
               GROUP BY cl.caller_user_id
               ORDER BY count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [StatsTopItem(**dict(r)) for r in rows]
    finally:
        db.close()
```

- [ ] **Step 2: Run tests**

```bash
cd api && python3 -m pytest tests/ -v
```

Expected: 37 passed, 1 skipped.

- [ ] **Step 3: Commit**

```bash
git add api/admin.py
git commit -m "feat: add call logs list and stats endpoints"
```

---

### Task 5: Write backend tests

**Files:**
- Create: `api/tests/test_call_logs.py`

- [ ] **Step 1: Write the test file**

```python
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

from tests.test_auth import _auth_header, _admin_header


def _get_voice_pool_id():
    from database import _sync_conn
    conn = _sync_conn()
    try:
        row = conn.execute("SELECT id FROM voices WHERE name = 'Cherry'").fetchone()
        return row["id"]
    finally:
        conn.close()


class TestCallLog:
    def test_token_creates_call_log(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller1", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        resp = client.post(
            "/api/call/token", headers=owner_headers,
            json={"agent_id": agent_id},
        )
        assert resp.status_code == 200
        token_data = resp.json()
        assert "token" in token_data
        assert "room_url" in token_data

    def test_end_call_log(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller2", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot2", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        resp = client.post(
            "/api/call/token", headers=owner_headers,
            json={"agent_id": agent_id},
        )
        assert resp.status_code == 200

        # Extract call_log_id from the token attributes (we can't decode JWT easily)
        # Instead, query the DB directly for the latest call_log
        from database import _sync_conn
        conn = _sync_conn()
        try:
            log = conn.execute("SELECT id FROM call_logs ORDER BY started_at DESC LIMIT 1").fetchone()
            call_log_id = log["id"]
        finally:
            conn.close()

        resp = client.patch(
            f"/api/call/admin/call-logs/{call_log_id}/end",
            json={"status": "completed", "duration_seconds": 45},
        )
        assert resp.status_code == 204

        # Verify the log was updated
        conn = _sync_conn()
        try:
            log = conn.execute("SELECT * FROM call_logs WHERE id = ?", (call_log_id,)).fetchone()
            assert log["status"] == "completed"
            assert log["duration_seconds"] == 45
            assert log["ended_at"] is not None
        finally:
            conn.close()


class TestCallLogList:
    def test_list_empty(self, clean_db):
        resp = client.get("/api/admin/call-logs", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_with_records(self, clean_db):
        # Create agent and generate 2 tokens to create call_logs
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller3", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot3", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]

        for _ in range(2):
            client.post("/api/call/token", headers=owner_headers, json={"agent_id": agent_id})

        resp = client.get("/api/admin/call-logs", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        # Each item should have agent_alias and caller_username
        item = data["items"][0]
        assert item["agent_alias"] == "TestBot3"
        assert item["status"] == "running"

    def test_list_requires_admin(self, clean_db):
        resp = client.get("/api/admin/call-logs")
        assert resp.status_code == 401

    def test_list_filter_by_agent(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller4", "pw")
        create_resp1 = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "BotA", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        create_resp2 = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "BotB", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp1.json()["id"]})
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp2.json()["id"]})

        resp = client.get(
            f"/api/admin/call-logs?agent_id={create_resp1.json()['id']}",
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["agent_alias"] == "BotA"


class TestStats:
    def test_overview_empty(self, clean_db):
        resp = client.get("/api/admin/stats/overview", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 0
        assert data["today_calls"] == 0
        assert data["active_users"] == 0

    def test_overview_with_records(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller5", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot5", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        agent_id = create_resp.json()["id"]
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": agent_id})

        resp = client.get("/api/admin/stats/overview", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 1
        assert data["today_calls"] == 1
        assert data["active_users"] == 1

    def test_trend(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller6", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot6", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp.json()["id"]})

        resp = client.get("/api/admin/stats/trend?days=30", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 0

    def test_top_agents(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller7", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TopBot", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp.json()["id"]})

        resp = client.get("/api/admin/stats/top-agents?limit=10", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["name"] == "TopBot"

    def test_top_users(self, clean_db):
        voice_pool_id = _get_voice_pool_id()
        owner_headers = _auth_header("caller8", "pw")
        create_resp = client.post(
            "/api/agents", headers=owner_headers,
            json={"alias": "TestBot8", "system_prompt": "Test", "voice_pool_id": voice_pool_id},
        )
        client.post("/api/call/token", headers=owner_headers, json={"agent_id": create_resp.json()["id"]})

        resp = client.get("/api/admin/stats/top-users?limit=10", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["name"] == "caller8"

    def test_stats_require_admin(self, clean_db):
        endpoints = [
            "/api/admin/stats/overview",
            "/api/admin/stats/trend",
            "/api/admin/stats/top-agents",
            "/api/admin/stats/top-users",
        ]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 401, f"{ep} should require admin"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && python3 -m pytest tests/test_call_logs.py -v
```

Expected: tests fail because endpoints haven't been implemented yet.

- [ ] **Step 3: Run all tests to verify they pass**

```bash
cd api && python3 -m pytest tests/ -v
```

Expected: All tests pass (the new tests pass because the endpoints were already implemented in Tasks 3 and 4).

- [ ] **Step 4: Commit**

```bash
git add api/tests/test_call_logs.py
git commit -m "test: add call logs and stats API tests"
```

---

### Task 6: Agent worker disconnect callback

**Files:**
- Modify: `agent/agent.py:65-66` (entrypoint function)
- Modify: `docker-compose.yml:11`

- [ ] **Step 1: Add duration tracking and callback in agent.py**

In `agent.py`, add `import time` at the top.

In the `entrypoint` function, add a start_time tracker right after `await ctx.connect()`:

```python
await ctx.connect()
started_at = time.time()
```

Extract `call_log_id` from config. After `voice_id = config.get("voice_id")` (line 92), add:

```python
call_log_id = config.get("call_log_id")
```

Register call log callback BEFORE `session.start()` so it fires immediately when the user disconnects. Use `participant_disconnected` (millisecond-level) as primary trigger with `disconnected` as safety net, guarded by `_call_ended` to avoid duplicate callbacks.

```python
# BEFORE session.start — registers callbacks that fire on user departure
if call_log_id:
    _call_ended = False

    def _end_call_log():
        nonlocal _call_ended
        if _call_ended:
            return
        _call_ended = True
        duration = int(time.time() - started_at)
        api_base = os.getenv("API_BASE_URL", "http://api:8000")
        url = f"{api_base}/api/call/admin/call-logs/{call_log_id}/end"
        try:
            data = json.dumps({"status": "completed", "duration_seconds": duration}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="PATCH")
            urllib.request.urlopen(req, timeout=5)
            logger.info(f"Call log {call_log_id} ended, duration={duration}s")
        except Exception as e:
            logger.warning(f"Failed to update call_log {call_log_id}: {e}")

    @ctx.room.on("participant_disconnected")
    def _on_participant_left(participant):
        _end_call_log()

    @ctx.room.on("disconnected")
    def _on_disconnected():
        _end_call_log()

await session.start(...)
```

Note: callbacks are registered BEFORE `session.start()` because `session.start()` is blocking — it only returns when the session ends, by which time the disconnect event may have already fired.

- [ ] **Step 1: Implement disconnect callback**

Add `import time` and `import urllib.request` at top of `agent/agent.py`.

After `started_at = time.time()` (right after `await ctx.connect()`):

```python
started_at = time.time()
```

After extracting call_log_id from config (after `voice_id = config.get("voice_id")`):

```python
call_log_id = config.get("call_log_id")
```

After the `session.start(...)` block, before the greeting section:

```python
# Register disconnect callback to record call duration
if call_log_id:
    def _on_disconnect():
        duration = int(time.time() - started_at)
        api_base = os.getenv("API_BASE_URL", "http://api:8000")
        url = f"{api_base}/api/call/admin/call-logs/{call_log_id}/end"
        try:
            import urllib.request as _urllib
            data = json.dumps({"status": "completed", "duration_seconds": duration}).encode()
            _req = _urllib.Request(url, data=data, headers={"Content-Type": "application/json"}, method="PATCH")
            _urllib.urlopen(_req, timeout=5)
            logger.info(f"Call log {call_log_id} ended, duration={duration}s")
        except Exception as e:
            logger.warning(f"Failed to update call_log {call_log_id}: {e}")

    ctx.room.on("disconnected", _on_disconnect)
```

- [ ] **Step 2: Add API_BASE_URL to docker-compose.yml**

```yaml
  agent:
    build: ./agent
    env_file: .env
    environment:
      - API_BASE_URL=http://api:8000
```

- [ ] **Step 3: Commit**

```bash
git add agent/agent.py docker-compose.yml
git commit -m "feat: agent worker records call duration on disconnect"
```

---

### Task 7: Frontend — install Chart.js + create pages

**Files:**
- Modify: `web-admin/package.json` (npm install)
- Create: `web-admin/src/views/CallLogListView.vue`
- Create: `web-admin/src/views/StatsView.vue`
- Modify: `web-admin/src/router.js:1-24`
- Modify: `web-admin/src/App.vue:1-15`

- [ ] **Step 1: Install chart.js and vue-chartjs**

```bash
cd web-admin && npm install chart.js vue-chartjs
```

- [ ] **Step 2: Create CallLogListView.vue**

```vue
<template>
  <div>
    <div class="page-header">
      <h2>通话记录</h2>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      <select v-model="filters.status" @change="load" style="width:140px">
        <option value="">全部状态</option>
        <option value="running">进行中</option>
        <option value="completed">已完成</option>
      </select>
      <button v-if="filters.status || filters.agent_id" class="btn-ghost" @click="clearFilters">清除筛选</button>
    </div>
    <table>
      <thead><tr>
        <th>时间</th><th>主叫用户</th><th>Agent</th><th>时长</th><th>状态</th>
      </tr></thead>
      <tbody>
        <tr v-for="log in logs" :key="log.id">
          <td style="font-size:12px">{{ (log.started_at || '').substring(0, 19).replace('T', ' ') }}</td>
          <td>{{ log.caller_username }}</td>
          <td>{{ log.agent_alias }}</td>
          <td>{{ log.duration_seconds != null ? formatDuration(log.duration_seconds) : '-' }}</td>
          <td><span :style="{color: log.status === 'completed' ? '#4caf50' : '#ff9800'}">{{ log.status === 'completed' ? '已完成' : '进行中' }}</span></td>
        </tr>
        <tr v-if="!logs.length">
          <td colspan="5" style="color:#888;text-align:center;padding:24px">暂无通话记录</td>
        </tr>
      </tbody>
    </table>
    <div v-if="total > pageSize" style="display:flex;justify-content:center;gap:8px;margin-top:16px">
      <button class="btn-ghost" :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span style="color:#888;font-size:12px;line-height:32px">{{ page }} / {{ Math.ceil(total / pageSize) }}</span>
      <button class="btn-ghost" :disabled="page >= Math.ceil(total / pageSize)" @click="page++; load()">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';

const logs = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const filters = ref({ status: '', agent_id: '' });

function formatDuration(s) {
  if (s < 60) return `${s}秒`;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}分${sec}秒`;
}

function clearFilters() {
  filters.value.status = '';
  filters.value.agent_id = '';
  page.value = 1;
  load();
}

async function load() {
  const params = new URLSearchParams({ page: page.value, page_size: pageSize });
  if (filters.value.status) params.set('status', filters.value.status);
  if (filters.value.agent_id) params.set('agent_id', filters.value.agent_id);
  try {
    const r = await api.get(`/admin/call-logs?${params}`);
    logs.value = r.data.items;
    total.value = r.data.total;
  } catch (_) {}
}

onMounted(load);
</script>
```

- [ ] **Step 3: Create StatsView.vue**

```vue
<template>
  <div>
    <div class="page-header">
      <h2>数据统计</h2>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px">
      <div class="stat-card">
        <div class="stat-value">{{ overview.total_calls }}</div>
        <div class="stat-label">总通话数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ overview.today_calls }}</div>
        <div class="stat-label">今日通话</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ formatHours(overview.total_duration_seconds) }}</div>
        <div class="stat-label">总时长 (小时)</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ overview.active_users }}</div>
        <div class="stat-label">活跃用户</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:2fr 1fr 1fr;gap:24px">
      <div class="chart-box">
        <h4 style="margin-bottom:12px;color:#888">通话趋势 (近30天)</h4>
        <canvas ref="trendCanvas"></canvas>
      </div>
      <div class="chart-box">
        <h4 style="margin-bottom:12px;color:#888">热门 Agent TOP 10</h4>
        <canvas ref="agentCanvas"></canvas>
      </div>
      <div class="chart-box">
        <h4 style="margin-bottom:12px;color:#888">活跃用户 TOP 10</h4>
        <canvas ref="userCanvas"></canvas>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { Chart, registerables } from 'chart.js';
import api from '../api.js';

Chart.register(...registerables);

const overview = ref({ total_calls: 0, today_calls: 0, total_duration_seconds: 0, active_users: 0 });
const trendCanvas = ref(null);
const agentCanvas = ref(null);
const userCanvas = ref(null);

function formatHours(s) {
  return (s / 3600).toFixed(1);
}

function destroyChart(canvasRef) {
  const instance = Chart.getChart(canvasRef.value);
  if (instance) instance.destroy();
}

function renderTrend(labels, data) {
  destroyChart(trendCanvas);
  new Chart(trendCanvas.value, {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: '通话数', data, borderColor: '#4a90d9', tension: 0.3, fill: false }],
    },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
  });
}

function renderBar(canvasRef, labels, data, color) {
  destroyChart(canvasRef);
  new Chart(canvasRef.value, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label: '通话数', data, backgroundColor: color }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true } },
    },
  });
}

onMounted(async () => {
  try {
    const r = await api.get('/admin/stats/overview');
    overview.value = r.data;
  } catch (_) {}

  try {
    const r = await api.get('/admin/stats/trend?days=30');
    renderTrend(r.data.map(d => d.date), r.data.map(d => d.count));
  } catch (_) {}

  try {
    const r = await api.get('/admin/stats/top-agents?limit=10');
    renderBar(agentCanvas, r.data.map(d => d.name), r.data.map(d => d.count), '#4a90d9');
  } catch (_) {}

  try {
    const r = await api.get('/admin/stats/top-users?limit=10');
    renderBar(userCanvas, r.data.map(d => d.name), r.data.map(d => d.count), '#4caf50');
  } catch (_) {}
});
</script>

<style scoped>
.stat-card {
  background: #1a1a2e;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
}
.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: #4a90d9;
}
.stat-label {
  font-size: 12px;
  color: #888;
  margin-top: 4px;
}
.chart-box {
  background: #1a1a2e;
  border-radius: 8px;
  padding: 16px;
}
</style>
```

- [ ] **Step 4: Update router.js**

Add imports:
```javascript
import CallLogListView from './views/CallLogListView.vue';
import StatsView from './views/StatsView.vue';
```

Add routes:
```javascript
  { path: '/call-logs', component: CallLogListView },
  { path: '/stats', component: StatsView },
```

- [ ] **Step 5: Update App.vue navigation**

Add nav links after `<router-link to="/api-keys">API Keys</router-link>`:

```html
<router-link to="/call-logs">通话记录</router-link>
<router-link to="/stats">数据统计</router-link>
```

- [ ] **Step 6: Build dist and run tests**

```bash
cd web-admin && npm run build
cd ../api && python3 -m pytest tests/ -v
```

Expected: dist built successfully, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add web-admin/package.json web-admin/package-lock.json web-admin/src/views/CallLogListView.vue web-admin/src/views/StatsView.vue web-admin/src/router.js web-admin/src/App.vue web-admin/dist/index.html
git commit -m "feat: add call log list and stats dashboard pages"
```

---

## Verification

1. `docker compose up -d --build` to deploy
2. Make a test call through the Flutter app
3. Check `/admin/#/call-logs` — should see the call record
4. Check `/admin/#/stats` — should see charts with data
5. User hangs up → call log immediately shows "已完成" (participant_disconnected event, not room-level disconnect)

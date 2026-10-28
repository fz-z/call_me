# Realtime 固定开场白 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为端到端实时 Agent 增加独立的固定开场白设置，并在连接后约束模型优先朗读它。

**Architecture:** `greeting_text` 存在 `agents` 表中，经 Agent API 与现有 Worker 私有运行时负载传递。Qwen Realtime Adapter 将非空文本合并进会话 instructions；空值保留人设生成首句的行为。所有后台编辑入口维护该字段，但仅实时模式显示。

**Tech Stack:** FastAPI/Pydantic、SQLite、Python unittest/pytest、Vue 3、Node test、Qwen Realtime WebSocket。

---

## File structure

- `api/database.py`：新增列的建表定义与重复安全迁移。
- `api/models.py`、`api/agents.py`、`api/permissions.py`、`api/config_utils.py`：API、持久化、授权复制和 Worker 私有下发。
- `agent/realtime/base.py`、`agent/agent.py`、`agent/realtime/qwen.py`：运行时字段与 Qwen instructions。
- `web-admin/src/utils/agentRuntimeForm.js`、Agent 表单与编辑视图：后台输入与提交。
- 对应的 API、Worker 和 Web Admin 现有测试：回归覆盖。

### Task 1: Persist and expose the Agent greeting

**Files:**
- Modify: `api/database.py:45-60,420-455`
- Modify: `api/models.py:42-80`
- Modify: `api/agents.py:45-170`
- Modify: `api/permissions.py:35-52`
- Modify: `api/config_utils.py:178-205`
- Test: `api/tests/test_agents.py`, `api/tests/test_database.py`, `api/tests/test_secrets.py`

- [ ] **Step 1: Write failing persistence tests**

Add a realtime Agent create/update/copy test:

~~~python
created = client.post("/api/agents", headers=admin_headers, json={
    "alias": "Greeting Agent",
    "system_prompt": "保持自然对话",
    "greeting_text": "您好，欢迎来电。",
    "voice_pool_id": voice_pool_id,
    "runtime_mode": "realtime",
    "realtime_config_id": realtime_config_id,
})
assert created.status_code == 200
assert created.json()["greeting_text"] == "您好，欢迎来电。"
updated = client.patch(
    f"/api/agents/{created.json()['id']}",
    headers=admin_headers,
    json={"greeting_text": "  您好，我是小助手。  "},
)
assert updated.json()["greeting_text"] == "您好，我是小助手。"
~~~

Extend the authorization-copy test to assert the copied value. Add a 301-character payload that returns 422. In the migration test, remove `greeting_text`, call `init_db()`, and assert old rows receive `""`. In the secrets test, assert the private worker runtime has the field but the public token payload does not.

- [ ] **Step 2: Run tests to verify RED**

Run: `cd api && python3 -m pytest tests/test_agents.py tests/test_database.py tests/test_secrets.py -q`

Expected: the new field or column is missing.

- [ ] **Step 3: Implement schema and API**

Add `greeting_text TEXT NOT NULL DEFAULT ''` to the initial `agents` SQL and repeat-safe migration:

~~~python
try:
    conn.execute("ALTER TABLE agents ADD COLUMN greeting_text TEXT NOT NULL DEFAULT ''")
except sqlite3.OperationalError:
    pass
~~~

Add a trimming validator with a 300-character limit, `greeting_text: str = ""` to `AgentCreate`, `Optional[str] = None` to `AgentUpdate`, and `greeting_text: str` to `AgentOut`. Include the field in Agent create/update/grant-copy SQL. Add only `"greeting_text": agent_row["greeting_text"] or ""` to `resolve_agent_runtime_config`, not `public_agent_config_payload`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `cd api && python3 -m pytest tests/test_agents.py tests/test_database.py tests/test_secrets.py -q`

Expected: migration, validation, trimming, copy behavior and private runtime tests pass.

- [ ] **Step 5: Commit**

~~~bash
git add api/database.py api/models.py api/agents.py api/permissions.py api/config_utils.py api/tests/test_agents.py api/tests/test_database.py api/tests/test_secrets.py
git commit -m "feat: persist realtime fixed greetings"
~~~

### Task 2: Apply the first-response constraint in Qwen Realtime

**Files:**
- Modify: `agent/realtime/base.py:17-45`
- Modify: `agent/agent.py:665-690`
- Modify: `agent/realtime/qwen.py:20-145`
- Test: `agent/tests/test_qwen_realtime.py`, `agent/tests/test_runtime_dispatch.py`

- [ ] **Step 1: Write failing Worker tests**

Use the existing fake WebSocket to assert instructions include both persona and fixed opening:

~~~python
config = runtime_config(
    system_prompt="友好回答",
    greeting_text="您好，欢迎来电。",
)
adapter = QwenRealtimeAdapter(config, session_factory=lambda: FakeSession(websocket))
with self.assertRaises(RealtimeRuntimeError):
    await adapter.run(config, FakeBridge())
instructions = websocket.sent[0]["session"]["instructions"]
self.assertIn("友好回答", instructions)
self.assertIn("您好，欢迎来电。", instructions)
self.assertIn("首个响应", instructions)
~~~

Also assert blank `greeting_text` preserves the previous instructions, and extend the realtime dispatch fake adapter to inspect the `RealtimeRuntimeConfig.greeting_text` it receives.

- [ ] **Step 2: Run tests to verify RED**

Run: `cd agent && .venv/bin/python -m unittest tests/test_qwen_realtime.py tests/test_runtime_dispatch.py`

Expected: `RealtimeRuntimeConfig` rejects the unknown greeting argument.

- [ ] **Step 3: Implement runtime propagation**

Add `greeting_text: str = ""` after `system_prompt` in `RealtimeRuntimeConfig`, include it in `redacted()`, and pass `runtime.get("greeting_text") or ""` from `run_realtime_call`.

In `agent/realtime/qwen.py`, use this helper for `session.update.session.instructions`:

~~~python
def _session_instructions(system_prompt: str, greeting_text: str) -> str:
    greeting_text = greeting_text.strip()
    if not greeting_text:
        return system_prompt
    return (
        f"{system_prompt}\n\n"
        "当前是通话的第一轮。首个响应必须且只能逐字朗读以下固定开场白，"
        "不可添加、删减、改写或解释；朗读后等待用户输入。\n"
        f"固定开场白：{greeting_text}"
    )
~~~

Keep the synthetic user message and `response.create` sequence unchanged.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `cd agent && .venv/bin/python -m unittest tests/test_qwen_realtime.py tests/test_runtime_dispatch.py tests/test_realtime_factory.py`

Expected: configured text is constrained; blank text retains exactly the original instructions.

- [ ] **Step 5: Commit**

~~~bash
git add agent/realtime/base.py agent/agent.py agent/realtime/qwen.py agent/tests/test_qwen_realtime.py agent/tests/test_runtime_dispatch.py
git commit -m "feat: constrain realtime greeting text"
~~~

### Task 3: Add a realtime-only admin setting

**Files:**
- Modify: `web-admin/src/utils/agentRuntimeForm.js:15-45`
- Modify: `web-admin/src/components/AgentForm.vue:35-115`
- Modify: `web-admin/src/views/AgentListView.vue:35-140`
- Modify: `web-admin/src/views/AgentDetailView.vue:30-105`
- Modify: `web-admin/src/views/UserDetailView.vue:25-145`
- Test: `web-admin/test/agentRuntimeForm.test.js`

- [ ] **Step 1: Write a failing UI payload test**

~~~javascript
assert.equal(buildAgentRuntimePayload({
  alias: '实时助手',
  systemPrompt: '保持自然对话',
  greetingText: '您好，欢迎来电。',
  voicePoolId: 'voice-a',
  runtimeMode: 'realtime',
  realtimeConfigId: 'realtime-a',
}).greeting_text, '您好，欢迎来电。');
~~~

Add source assertions that `AgentForm.vue` contains `v-if="runtimeMode === 'realtime'"`, `固定开场白`, and `greetingText`.

- [ ] **Step 2: Run test to verify RED**

Run: `cd web-admin && node --test test/agentRuntimeForm.test.js`

Expected: `greeting_text` is absent.

- [ ] **Step 3: Implement all edit paths**

Add `greetingText` to `buildAgentRuntimePayload` and return `greeting_text: greetingText || ''`. In `AgentForm.vue`, add an `editGreetingText` prop, initialize the local value, pass it to the payload builder, and render this field after the persona text only in realtime mode:

~~~vue
<template v-if="runtimeMode === 'realtime'">
  <label>固定开场白（仅端到端实时）</label>
  <textarea v-model="greetingText" rows="3" maxlength="300"
    placeholder="留空则由人设生成开场白"></textarea>
  <p class="hint">模型会被要求首句朗读此文本，但其输出不是确定性 TTS。</p>
</template>
~~~

Pass `:edit-greeting-text="agent.greeting_text"` from `AgentDetailView`. Add `greeting_text` to initialization and PATCH bodies in `AgentListView`, the authorization-copy editor in `AgentDetailView`, and `UserDetailView`. In direct edit modals, conditionally show it only when the edited Agent has `runtime_mode === 'realtime'`; switching to Pipeline must not erase an existing value.

- [ ] **Step 4: Run frontend tests and build to verify GREEN**

Run: `cd web-admin && node --test test/*.test.js && npm run build`

Expected: all tests pass and Vite reports a successful build.

- [ ] **Step 5: Commit**

~~~bash
git add web-admin/src/utils/agentRuntimeForm.js web-admin/src/components/AgentForm.vue web-admin/src/views/AgentListView.vue web-admin/src/views/AgentDetailView.vue web-admin/src/views/UserDetailView.vue web-admin/test/agentRuntimeForm.test.js
git commit -m "feat: configure realtime fixed greetings in admin"
~~~

### Task 4: Document and verify

**Files:**
- Modify: `README.md:47-65,80-115`
- Modify: `agent/README.md:40-50`

- [ ] **Step 1: Document the behavior**

Document that `greeting_text` is optional and Realtime-only; empty input preserves persona-generated opening. State that the model is constrained by instructions, not deterministic text-to-speech.

- [ ] **Step 2: Run final verification**

~~~bash
cd api && python3 -m pytest tests/test_agents.py tests/test_database.py tests/test_secrets.py -q
cd ../agent && .venv/bin/python -m unittest tests/test_qwen_realtime.py tests/test_runtime_dispatch.py tests/test_realtime_factory.py
cd ../web-admin && node --test test/*.test.js && npm run build
cd .. && git diff --check
~~~

Expected: every selected suite exits 0, Vite builds, and `git diff --check` has no output.

- [ ] **Step 3: Commit**

~~~bash
git add README.md agent/README.md
git commit -m "docs: describe realtime fixed greetings"
~~~


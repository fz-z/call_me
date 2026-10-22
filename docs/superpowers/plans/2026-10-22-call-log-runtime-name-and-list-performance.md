# Call Log Runtime Name and List Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the realtime configuration's name from call start and keep call-log pages lightweight as records grow.

**Architecture:** Persist a nullable configuration-name snapshot in `call_logs`. Split the admin list into scalar summaries and an authenticated detail fetch for transcripts. Add SQLite indexes for the retained page-based filters and ordering, and lazy-load details in the Vue page.

**Tech Stack:** FastAPI, SQLite, pytest, Vue 3, Vite.

---

### Task 1: Persist the runtime name snapshot

**Files:** `api/database.py`, `api/config_utils.py`, `api/call.py`, `api/tests/test_call_logs.py`

- [ ] **Step 1: Write a failing test** in `TestCallLog` that creates a realtime config named `Qwen 3.0 实时测试`, binds an agent, creates a token, and asserts `call_logs.runtime_config_name` equals that name. Rename the config and assert the call-log value remains unchanged. Reuse the existing realtime setup pattern in `test_incomplete_realtime_configuration_creates_no_call_log` and set all required runtime fields.
- [ ] **Step 2: Confirm red:** run `PHOTOS_DIR=/private/tmp/call-me-test-photos pytest tests/test_call_logs.py -q -k runtime_config_name`; expect assertion failure because the column is missing.
- [ ] **Step 3: Add `runtime_config_name TEXT`** to the existing call-log migration loop in `api/database.py`. Extend `_resolve_realtime_config` in `api/config_utils.py` with `"name": config["name"]`; extend `_runtime_call_log_fields` to return the name for realtime and `None` for pipeline; include it in the token endpoint `INSERT` column/value lists.
- [ ] **Step 4: Confirm green:** rerun the focused test; expect 1 passed.
- [ ] **Step 5: Commit** these files with `feat: snapshot realtime runtime name in call logs`.

### Task 2: Return compact pages and fetch transcript details on demand

**Files:** `api/admin.py`, `api/models.py`, `api/database.py`, `api/tests/test_call_logs.py`

- [ ] **Step 1: Write failing API tests** that create a call log with a long transcript, assert list item has `has_transcript=True` and `transcript is None`, assert `GET /api/admin/call-logs/{id}` returns the original transcript, and assert missing detail returns 404 while a non-admin cannot access it. Add a deterministic same-timestamp pagination case.
- [ ] **Step 2: Confirm red:** run `PHOTOS_DIR=/private/tmp/call-me-test-photos pytest tests/test_call_logs.py -q -k 'compact or detail or stable_order'`; expect missing field/endpoint or wrong transcript.
- [ ] **Step 3: Add `has_transcript: bool = False` and `runtime_config_name: Optional[str]`** to `CallLogOut`. In the list query, explicitly select scalar fields and `CASE WHEN cl.transcript IS NOT NULL AND cl.transcript != '' THEN 1 ELSE 0 END AS has_transcript`; do not select `cl.transcript`. Add `ORDER BY cl.started_at DESC, cl.id DESC`. Add `GET /api/admin/call-logs/{call_log_id}` with `require_admin` and a single-row `SELECT cl.*, ...` returning `CallLogOut`, 404 on missing row.
- [ ] **Step 4: Add SQLite indexes** via `CREATE INDEX IF NOT EXISTS` for `(started_at DESC, id DESC)` and `(status|agent_id|caller_user_id, started_at DESC, id DESC)`. Constrain `page >= 1` and `1 <= page_size <= 100` with FastAPI `Query`.
- [ ] **Step 5: Confirm green:** rerun focused API tests and check `EXPLAIN QUERY PLAN` for unfiltered and status-filtered list ordering; expect index scan rather than temp sorting.
- [ ] **Step 6: Commit** with `perf: page call log summaries and index history queries`.

### Task 3: Lazy-load transcript and display the saved name

**Files:** `web-admin/src/views/CallLogListView.vue`, `web-admin/src/utils/callLogRuntime.js`, `web-admin/src/utils/callLogRuntime.test.js`

- [ ] **Step 1: Write failing Node tests** for `runtimeLabel` covering saved name, old realtime model fallback, provider fallback and pipeline. Run `node --test src/utils/callLogRuntime.test.js` from `web-admin`; expect failure because the helper does not exist.
- [ ] **Step 2: Implement** `runtimeLabel(log)` to return `端到端实时 · ${log.runtime_config_name || log.model || log.provider}` for realtime; use model/provider fallbacks for pipeline. Import it in the Vue page.
- [ ] **Step 3: Update the Vue page:** use `has_transcript` for the expand affordance, fetch `/admin/call-logs/${log.id}` on first expansion, cache detail by ID, show loading/error/retry states, and pass the loaded transcript to `TranscriptView`. Reset cache/expanded row when the page or filter loads.
- [ ] **Step 4: Verify:** run Node tests and `npm run build`; manually inspect loaded, empty and error states in the browser when available.
- [ ] **Step 5: Commit** with `feat: show runtime names and lazy-load call transcripts`.

### Task 4: Regression and evidence

**Files:** none unless tests reveal a defect.

- [ ] **Step 1:** Run `PHOTOS_DIR=/private/tmp/call-me-test-photos pytest tests/test_call_logs.py -q`; compare to the baseline 12 passing / 2 pre-existing 401-vs-403 failures.
- [ ] **Step 2:** Run all backend tests, frontend tests and build. Record exact exit codes; investigate new failures only.
- [ ] **Step 3:** Inspect `git diff --check`, `git status --short`, and confirm no unrelated or secret files entered commits.

**Baseline caveat:** In this host environment, two existing tests in `test_call_logs.py` expect unauthenticated HTTP 401 but currently get 403, before any feature edits. Keep that discrepancy separate unless the user asks to fix it.

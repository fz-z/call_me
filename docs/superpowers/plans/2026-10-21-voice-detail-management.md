# Voice Detail Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the combined voice-binding modal with a dedicated voice detail page, correctly separate classic TTS from realtime bindings, and make reuse/re-cloning explicit.

**Architecture:** Keep the existing FastAPI endpoints and database. Extract pure binding classification into a small utility, simplify the voice list to an overview/creation page, and add a routed Vue detail page with independent actions and local errors. The realtime provider voice ID stays server-only.

**Tech Stack:** Vue 3, Vue Router, Axios, Vite, Node `node:test`.

---

## File map

- Create `web-admin/src/utils/voiceManagement.js`: pure filtering and option selection, independent of Vue and API.
- Create `web-admin/test/voiceManagement.test.js`: regression tests for mixed TTS/realtime bindings, unsupported configs, existing bindings.
- Create `web-admin/src/views/VoiceDetailView.vue`: routed detail page, independent action forms, classic audition.
- Modify `web-admin/src/views/VoicePoolView.vue`: overview only, correctly classified realtime column, route to detail. Keep existing two creation dialogs.
- Modify `web-admin/src/router.js`: `/voices/:id` route.
- Modify `api/models.py` and `api/tests/test_voices.py`: expose persisted `audition_text` to the detail page without exposing provider voice IDs.

### Task 1: Classify binding data at the UI boundary

**Files:** Create `web-admin/test/voiceManagement.test.js`; create `web-admin/src/utils/voiceManagement.js`.

- [ ] **Step 1: Write failing tests** for a mixed binding list and for the unbound/cloneable configuration set:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { realtimeBindings, availableRealtimeConfigs } from '../src/utils/voiceManagement.js';

const rows = [
  { runtime_kind: 'tts', runtime_config_id: 'tts-a' },
  { runtime_kind: 'realtime', runtime_config_id: 'rt-a' },
];
test('realtime list excludes TTS runtime bindings', () => {
  assert.deepEqual(realtimeBindings(rows), [rows[1]]);
});
test('new clone choices exclude existing and non-cloneable configs', () => {
  const configs = [
    { id: 'rt-a', capabilities_json: '{"voice_clone":true}' },
    { id: 'rt-b', capabilities_json: '{"voice_clone":true}' },
    { id: 'rt-c', capabilities_json: '{}' },
  ];
  assert.deepEqual(availableRealtimeConfigs(configs, rows).map((item) => item.id), ['rt-b']);
});
```

- [ ] **Step 2: Verify red:** `node --test web-admin/test/voiceManagement.test.js` fails because the module is absent.
- [ ] **Step 3: Add minimal pure implementation:**

```js
export function realtimeBindings(bindings = []) {
  return bindings.filter((binding) => binding.runtime_kind === 'realtime');
}

export function availableRealtimeConfigs(configs = [], bindings = []) {
  const used = new Set(realtimeBindings(bindings).map((binding) => binding.runtime_config_id));
  return configs.filter((config) => {
    try {
      return JSON.parse(config.capabilities_json || '{}').voice_clone === true && !used.has(config.id);
    } catch (_) {
      return false;
    }
  });
}
```

- [ ] **Step 4: Verify green:** run targeted test and `node --test web-admin/test/*.test.js`; expect all tests pass.
- [ ] **Step 5: Commit** the utility and its test.

### Task 2: Make the voice list an overview

**Files:** Modify `web-admin/src/views/VoicePoolView.vue`.

- [ ] **Step 1: In `load()`, map `_runtimeBindings` through `realtimeBindings(runtime.value.data)`**, not the full mixed response. Existing TTS links continue to populate `_ttsConfigs`.
- [ ] **Step 2: Replace list-row “管理绑定” with a router link to `/voices/${voice.id}`** and remove the combined edit modal and its save/add/remove/clone state and methods. Keep creation dialogs; move classic audition to the detail page so the list has one clear path per voice.
- [ ] **Step 3: Run `node --test web-admin/test/*.test.js` and `npm run build` from `web-admin`; expect pass.**
- [ ] **Step 4: Commit** the list change.

### Task 3: Build the detail page with independent actions

**Files:** Create `web-admin/src/views/VoiceDetailView.vue`; modify `web-admin/src/router.js`.

- [ ] **Step 1: Load voice and related data.** Read `/admin/voices`, find `route.params.id`, then load TTS links, runtime bindings, agents, TTS configs and realtime configs. Use separate loading/error state for the page and each action. A missing ID yields “找不到这个音色” with a return link; a failed request yields “加载失败” with retry, never an empty-binding state.
- [ ] **Step 2: Render four clearly labeled sections** (overview, realtime, classic TTS, basic info) with cards. Only `realtimeBindings()` may populate realtime cards. Show explicit reuse guidance and a link to the Agent list. Use a responsive grid that collapses to one column at narrow widths.
- [ ] **Step 3: Add realtime clone form** with `mode='new'|'replace'`, available choices from `availableRealtimeConfigs`, and a fixed target for replacement. Keep form hidden until the relevant action is clicked. Validate extension (`wav/mp3/m4a`), ≤10 MB and duration ≤60 seconds before enabling submit; require authorization checkbox. The replacement submit path calls `confirm('重新复刻会替换此实时模型当前绑定…')` immediately before the POST; cancel performs no request. POST `FormData` to the existing endpoint and reload bindings on success.
- [ ] **Step 4: Add classic TTS actions** using existing `/tts-configs` GET/POST/DELETE endpoints. List current links, add only an unlinked config, remove one link, and open a dedicated audition dialog. Audition POST uses `{ text, tts_config_id }`; play returned audio and revoke the object URL when playback ends or closes.
- [ ] **Step 5: Add basic-info editing** with `PATCH /admin/voices/{id}` for name/audition text only. Keep errors scoped to their form; after success reload voice data without discarding other section state.
- [ ] **Step 6: Add the route after `/voices`, then run all Node tests and `npm run build`; inspect the resulting route in a browser at wide and narrow widths.** Verify mixed rows do not show TTS Flash as realtime, both new and replacement clone flows, error display, refresh and invalid ID states.

```js
import VoiceDetailView from './views/VoiceDetailView.vue';
// routes:
{ path: '/voices/:id', component: VoiceDetailView, props: true },
```
- [ ] **Step 7: Commit** the finished detail page and any necessary route/list changes.

### Task 4: Final verification and review

**Files:** All changed files from Tasks 1–3, `api/models.py`, `api/tests/test_voices.py`.

- [ ] **Step 0: Lock the default audition text contract.** Extend `TestVoiceAuditionText.test_update_audition_text` to assert the PATCH response and subsequent GET `/api/admin/voices` response contain the saved text; verify red with `PHOTOS_DIR=/private/tmp/call_me_voice_detail_photos python -m pytest tests/test_voices.py::TestVoiceAuditionText::test_update_audition_text -q`. Add `audition_text: Optional[str] = None` to `VoiceOut`, then verify green with the same command.

- [ ] **Step 1: Run `node --test web-admin/test/*.test.js` and `npm run build` freshly.** Read full output; do not claim success based on previous runs.
- [ ] **Step 2: Run `git diff --check`, inspect the diff against the spec, and ensure no provider voice IDs or keys are rendered or logged.**
- [ ] **Step 3: Request code review, address concrete findings, rerun the affected checks, then commit any corrections.**
- [ ] **Step 4: Report what changed, what was verified, and whether deployment was or was not performed.** Do not deploy automatically; production rollout is separate from this UI implementation.

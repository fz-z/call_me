# Realtime Transcript Turns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each realtime Agent response as one call-history record instead of a card per streamed subtitle fragment.

**Architecture:** The Worker accumulates provider subtitle events into mutable in-memory call-log turns, keyed by response identity, and replaces accumulated text when an authoritative final subtitle arrives. The admin page applies a conservative, display-only grouping utility to old records that lack response IDs.

**Tech Stack:** Python 3.13 `unittest`, Vue 3, Node `node:test`, Vite.

---

### Task 1: New realtime call records

**Files:**
- Create: `agent/realtime/transcript.py` (event-to-turn aggregation)
- Modify: `agent/agent.py:676-692` (delegate event handling)
- Modify: `agent/tests/test_runtime_dispatch.py` (end-to-end Worker regression)
- Create: `agent/tests/test_realtime_transcript.py` (aggregation unit tests)

- [x] Write failing tests using a sequence equivalent to:

```python
collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "你"}, 0.2)
collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "好"}, 0.3)
collector.add("response.audio_transcript.done", {"response_id": "r1", "transcript": "你好"}, 0.4)
assert collector.turns == [{"role": "assistant", "text": "你好", "time": 0.2}]
```

  Also assert: separate response IDs create separate turns; a delta-only interrupted response keeps its partial text; repeated final events do not duplicate; a completed user transcript creates one user turn; blank or unrelated events create none.
- [x] Run the collector test with the existing Python environment and confirm it fails because the collector does not exist.
- [x] Implement `RealtimeTranscriptCollector.add(event_type: str, data: dict, elapsed: float)` and `turns: list[dict]`. For Agent deltas, append to the response's existing turn; for Agent done, replace the text with `transcript`; for user completed, add one turn. Keep all changes in the collector so `agent.py` needs only `collector.add(event.type, event.data, elapsed)`.
- [x] Run the collector tests, then the Worker dispatch tests. Both pass.

### Task 2: Historical call-log display

**Files:**
- Create: `web-admin/src/utils/callTranscript.js` (legacy display normalization)
- Create: `web-admin/test/callTranscript.test.js` (normalization tests)
- Modify: `web-admin/src/views/CallLogListView.vue:108-115` (use normalizer before rendering)

- [x] Write failing Node tests using examples equivalent to:

```js
assert.deepEqual(groupTranscriptTurns([
  { role: 'assistant', text: '你', time: 0.2 },
  { role: 'assistant', text: '好', time: 0.3 },
  { role: 'assistant', text: '你好', time: 0.4 },
]), [{ role: 'assistant', text: '你好', time: 0.2 }]);
```

  Also assert that different speakers, distant timestamps, and pre-grouped records remain separate. Check that the Vue view imports and applies the function.
- [x] Run `node --test web-admin/test/callTranscript.test.js` and confirm failure for the missing utility.
- [x] Implement `groupTranscriptTurns(turns, runtimeMode)` with a small time-gap threshold for short fragments, duplicate-final replacement, and no mutation of the source array. Use it in `TranscriptView` after parsing stored JSON.
- [x] Run `node --test web-admin/test/callTranscript.test.js` and `node --test web-admin/test/*.test.js` and confirm pass.

### Task 3: Final verification

**Files:** no additional source files.

- [x] Run the complete Agent test set with the existing Python environment (66 passed; local test sockets required sandbox approval).
- [x] Run `npm run build` in `web-admin` using offline-installed dependencies.
- [x] Inspect `git diff --check`, `git status --short`, and the final diff. Confirm the audio/interruption code is unchanged and no secrets or generated artifacts are tracked.
- [ ] Report the implementation and verification result. Do not deploy unless the user asks.

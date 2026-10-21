# Long Realtime Voice Audition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support up to 3000 characters in realtime voice audition by generating bounded segments and playing them in order.

**Architecture:** Keep the existing 120-character server endpoint and its 35-second/2-MiB safeguards. Split text in the admin UI, then maintain a two-slot browser audio queue: one playing segment and at most one prefetched segment. A small controller owns request generations, cancellation, URL cleanup and retry; the Vue component renders its state and invokes its controls.

**Tech Stack:** Vue 3, browser Audio/Blob APIs, Node built-in test runner, Vite.

---

### Task 1: Text boundaries and segmentation

**Files:**
- Modify: `web-admin/src/utils/realtimeVoiceAudition.js`
- Modify: `web-admin/test/realtimeVoiceAudition.test.js`

- [ ] Add failing tests for empty text, 3000/3001 Unicode characters, exact reconstruction of trimmed input, sentence/newline preference, and a hard split for a 121-character sentence. Example: `assert.deepEqual(splitRealtimeAuditionText('你好。世界。', 3), ['你好。', '世界。'])` and `assert.equal(splitRealtimeAuditionText('字'.repeat(121)).join(''), '字'.repeat(121))`.
- [ ] Run `node --test test/realtimeVoiceAudition.test.js` from `web-admin`; confirm the new tests fail on missing behavior.
- [ ] Export `MAX_REALTIME_AUDITION_TEXT_LENGTH = 3000` and `MAX_REALTIME_AUDITION_SEGMENT_LENGTH = 120`; update `getRealtimeAuditionTextError` and add `splitRealtimeAuditionText(text, maxLength=120)` that retains each Unicode code point exactly, finds the last sentence terminator/newline inside the window, and falls back to a hard boundary.
- [ ] Run the focused test; confirm all tests pass. Commit the utility and tests.

### Task 2: Bounded sequential playback controller

**Files:**
- Create: `web-admin/src/utils/realtimeAuditionQueue.js`
- Create: `web-admin/test/realtimeAuditionQueue.test.js`

- [ ] Add failing tests with injected fake `request`, `play`, `pause`, `makeUrl`, and `revokeUrl`. Cover first-segment playback before later generation, one in-flight request, next-segment prefetch, ordered continuation, waiting state, pause/resume, stop/close cleanup, stale completion rejection, per-segment failure and retry without replaying completed segments.
- [ ] Run `node --test test/realtimeAuditionQueue.test.js`; confirm feature tests fail for the missing controller.
- [ ] Implement `createRealtimeAuditionQueue(dependencies)` with `start(segments)`, `ended()`, `pause()`, `resume()`, `retry()`, `stop()`, and `dispose()`. Expose `state` snapshots via an `onState` callback. Keep no more than current/next object URLs, one AbortController, and a monotonically increasing generation to ignore stale responses.
- [ ] Run focused tests; confirm all pass. Commit the controller and tests.

### Task 3: Admin audition UI

**Files:**
- Modify: `web-admin/src/components/RealtimeVoiceAudition.vue`
- Modify: `web-admin/test/realtimeVoiceAudition.test.js`

- [ ] Add a failing source-level component wiring test in `web-admin/test/realtimeVoiceAudition.test.js`: read `RealtimeVoiceAudition.vue` and assert it imports `createRealtimeAuditionQueue`, renders `MAX_REALTIME_AUDITION_TEXT_LENGTH`, and exposes pause/stop/retry actions. The test guards the wiring while Task 2 covers queue behavior.
- [ ] Run `node --test test/realtimeVoiceAudition.test.js`; confirm the wiring test fails for the old single-audio component.
- [ ] Replace single-audio submission with queue startup using the existing POST endpoint for each segment. Show length counter, segment progress, buffering/waiting, pause/resume, stop, retry-current, and billing caveat. Call `dispose()` on close/unmount and when switching bindings. Keep text local to the modal.
- [ ] Run focused tests and `npm run build`; confirm all pass. Commit UI changes.

### Task 4: Regression and review

**Files:**
- Review: `web-admin/src/components/RealtimeVoiceAudition.vue`
- Review: `web-admin/src/utils/realtimeAuditionQueue.js`
- Review: `web-admin/src/utils/realtimeVoiceAudition.js`

- [ ] Run `node --test test/*.test.js` and `npm run build` from `web-admin`; confirm zero failures.
- [ ] Run `git diff --check` and review changes against `docs/superpowers/specs/2026-10-21-long-realtime-voice-audition-design.md`, including cancellation, memory bounds, pricing notice, exact character preservation, and no server API changes.
- [ ] Manually inspect the admin modal locally where available. Do not trigger a paid model request automatically. Report any unverified live-provider behavior explicitly.

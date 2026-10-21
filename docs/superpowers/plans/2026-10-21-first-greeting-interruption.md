# First Greeting Interruption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop buffered Qwen realtime greeting audio immediately when the caller begins speaking, and keep Pipeline fallback greeting interruptible when configured.

**Architecture:** The Qwen adapter owns response lifecycle state and handles `input_audio_buffer.speech_started`; it asks the LiveKit bridge to clear queued output and suppresses old response deltas until `response.done`. The bridge exposes one serialized `clear_output()` operation. The Pipeline fallback passes through the existing `allow_interruptions` value.

**Tech Stack:** Python 3.11 `unittest`, Qwen WebSocket adapter, LiveKit Python RTC AudioSource, existing Agent Worker.

---

## File map

- `agent/realtime/bridge.py`: add serialized output-queue clearing; no provider knowledge.
- `agent/realtime/qwen.py`: interpret VAD and response events, suppress stale audio, emit metadata-only diagnostics.
- `agent/agent.py`: fix the Pipeline fallback greeting's interruption flag.
- `agent/tests/test_realtime_bridge.py`: queue clearing and no-source/unsupported-source behavior.
- `agent/tests/test_qwen_realtime.py`: event-order and interruption tests using the existing fake WebSocket/bridge.
- `agent/tests/test_pipeline_greeting.py`: dependency-free AST regression for the fallback path.

### Task 1: Clear LiveKit queued output safely

**Files:** Modify `agent/realtime/bridge.py`, `agent/tests/test_realtime_bridge.py`.

- [ ] Add `FakeSource.clear_queue()` to empty `frames` and count calls. Add async tests: after `publish_pcm`, `clear_output()` empties frames and returns `True`; before source creation it returns `False`; a source lacking `clear_queue` returns `False` without closing the bridge; a subsequent `publish_pcm` succeeds.
- [ ] Run `/Users/zhangfuzhen/.local/bin/python3.11 -m unittest tests.test_realtime_bridge -v` from `agent/` and confirm the new tests fail because `clear_output` does not exist.
- [ ] Add `async def clear_output(self) -> bool` inside `LiveKitAudioBridge`: acquire `_output_lock`; if `_source` is absent return `False`; get `clear_queue`; if absent log a warning and return `False`; invoke via `_maybe_await`; on exception log a warning and return `False`; otherwise return `True`. Do not unpublish or close the source.
- [ ] Re-run the focused bridge test, then `git add` those two files and commit `fix: clear realtime output queue on interruption`.

### Task 2: Handle Qwen speech-start and stale response audio

**Files:** Modify `agent/realtime/qwen.py`, `agent/tests/test_qwen_realtime.py`.

- [ ] Extend `FakeBridge` with `clear_calls`, `clear_output()` that increments it and clears `published`, and a boolean return. Add an event-sequence test sending `response.created`, audio A, `input_audio_buffer.speech_started`, audio B, `response.done` with `status=cancelled`, `response.created`, audio C. Assert clear called once and only C remains. Add tests for disabled interruptions (A and B both pass, no clear), speech-start outside an active response (no clear), and a post-cancellation new response (audio resumes). Also assert the adapter sends microphone PCM while an interruptible response is active.
- [ ] Run `/Users/zhangfuzhen/.local/bin/python3.11 -m unittest tests.test_qwen_realtime -v` from `agent/`; confirm the new sequence test fails because no clear/suppression occurs. The existing suite may take roughly 80 seconds; use a specific test name for the first red run if needed.
- [ ] Add `_suppress_response_audio = False` state. On `input_audio_buffer.speech_started`, log only event type and response state; if `allow_interruptions` and `_response_active`, call `await self._bridge.clear_output()`, set suppression true, and log whether clearing succeeded. On `response.audio.delta`, validate data as today but skip `publish_pcm` while suppression is true. On `response.done`, log only status and cancellation reason, set active and suppression false. On `response.created`, set active true and preserve suppression only if an old response has not completed; provider ordering guarantees `response.done` before the next response. Reset state in `close()`.
- [ ] Run focused Qwen tests; commit the two files as `fix: stop stale Qwen audio after caller speech starts`.

### Task 3: Respect Pipeline fallback interruption setting

**Files:** Modify `agent/agent.py`; create `agent/tests/test_pipeline_greeting.py`.

- [ ] Write a dependency-free AST test that locates `_speak_greeting` inside `run_pipeline_call`, finds the fallback `session.say("你好，请问有什么可以帮助你的？", ...)`, and asserts its `allow_interruptions` keyword is the local name `allow_interruptions`, not a constant. Use `ast.parse(Path(__file__).resolve().parents[1].joinpath("agent.py").read_text())`.
- [ ] Run `/Users/zhangfuzhen/.local/bin/python3.11 -m unittest tests.test_pipeline_greeting -v` from `agent/`; confirm it fails on the current `False` constant.
- [ ] Change only the fallback call to `allow_interruptions=allow_interruptions`; rerun test and commit as `fix: keep pipeline fallback greeting interruptible`.

### Task 4: Full verification, review, and rollout readiness

**Files:** No source changes unless review finds a defect.

- [ ] Run all dependency-light tests: `/Users/zhangfuzhen/.local/bin/python3.11 -m unittest tests.test_realtime_bridge tests.test_qwen_realtime tests.test_pipeline_greeting -v`; inspect failures and rerun until clean.
- [ ] Run `python3.11 -m compileall -q agent.py realtime tests` from `agent/` and `git diff --check` from repo root.
- [ ] The local Python 3.11 environment lacks LiveKit. Copy `agent/` to `/tmp/call-me-interruption-tests/agent/` on the ECS, then run `docker run --rm --network none --memory 512m -v /tmp/call-me-interruption-tests/agent:/app:ro -w /app call_me-agent python -m unittest discover -s tests -v` over SSH. This uses the already-built Agent image and does not replace the running container or call the paid provider.
- [ ] Request independent code review of the branch against `db87e44`; resolve all critical and important issues; rerun verification.
- [ ] Confirm production rollout scope: GitHub push + server fast-forward + `docker compose up -d --build agent` only, then inspect health/logs and perform one real-call interruption check. Record the previous Git SHA and image ID for rollback. Do not claim real-call success without actual observation.

### Task 5: Address review-discovered playback tail and backpressure

**Files:** Modify `agent/realtime/qwen.py`, `agent/tests/test_qwen_realtime.py` and the approved design spec.

- [ ] Write and run failing event-sequence test `response.created → audio.delta → response.done → speech_started → response.created → audio.delta`; assert the old queued tail is cleared and only new audio remains.
- [ ] Write and run a failing blocked-output test: make `publish_pcm` wait, feed `speech_started` through the same WebSocket consumer, and require the clear event before releasing the fake publisher.
- [ ] Make Qwen's WebSocket consumer queue PCM to an independent output task. Bound pending output to 5 seconds of 24 kHz mono PCM16 and split each provider delta into 20 ms frames. On speech start, cancel the output task, drain pending PCM, then call bridge `clear_output()` even when `response.done` already arrived. Suppress late old deltas only while the old response remains active.
- [ ] Add a failing log test for `response.done` status/reason; log only allowlisted status and reason values, never provider text. Rerun the focused tests and full suite in the isolated Agent image.
- [ ] Re-request independent review; amend the design spec to document why `response.done` is not playout completion and why receive/playback are decoupled.

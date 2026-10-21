# Realtime Backlog Incident Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent fast Qwen audio generation from disconnecting a live call while preserving immediate interruption and bounded memory.

**Architecture:** Keep the independent 20 ms LiveKit output pump and raise the per-call PCM queue limit to 60 seconds. When a response exceeds that limit, suppress only the rest of that response, preserving the session and allowing the next response. Give controlled runtime failures stable, secret-free diagnostic codes.

**Tech Stack:** Python 3.11 `unittest`, Qwen WebSocket adapter, LiveKit Agent worker, Docker Compose.

---

### Task 1: Accept normal fast-generated audio without disconnecting

**Files:** `agent/realtime/qwen.py`, `agent/tests/test_qwen_realtime.py`.

- [ ] Add a test that blocks the output bridge, sends a 6-second PCM `response.audio.delta`, and asserts `_handle_message()` does not raise, the output task remains alive, and pending bytes equal the delta length. This must fail against the current 5-second cap.

```python
bridge = BlockingOutputBridge()
adapter = QwenRealtimeAdapter(runtime_config())
adapter._bridge = bridge
pcm = b"\x01\x00" * (24_000 * 6)
await adapter._handle_message(json.dumps({
    "type": "response.audio.delta", "delta": base64.b64encode(pcm).decode("ascii"),
}))
assert adapter._pending_output_bytes == len(pcm)
await adapter.close()
```
- [ ] Run `python3.11 -m unittest tests.test_qwen_realtime.QwenRealtimeAdapterTests.test_six_second_output_burst_does_not_close_call -v` from `agent/`; verify failure is `Qwen realtime audio output backlog exceeded`.
- [ ] Change `MAX_PENDING_OUTPUT_BYTES` to `24_000 * 2 * 60`, keeping 20 ms chunks and current cancellation path.

```python
MAX_PENDING_OUTPUT_BYTES = 24_000 * 2 * 60
```
- [ ] Rerun the focused test, then commit `fix: allow bounded Qwen audio bursts`.

### Task 2: Preserve the call on extreme backlog and classify failures

**Files:** `agent/realtime/qwen.py`, `agent/realtime/base.py`, `agent/agent.py`, `agent/tests/test_qwen_realtime.py`, `agent/tests/test_runtime_dispatch.py`.

- [ ] Add a test feeding 60 seconds of PCM plus one extra 20 ms delta with a blocked bridge. Assert no exception, a fixed `audio_backlog_overflow` warning, subsequent deltas of the same response are skipped, and `response.done` followed by a new response allows new audio. Verify `close()` leaves `_pending_output_bytes == 0`.

```python
await adapter._handle_message(json.dumps({"type": "response.created"}))
await adapter._handle_message(audio_delta(b"\x01\x00" * (24_000 * 60)))
with self.assertLogs("realtime.qwen", level="WARNING") as logs:
    await adapter._handle_message(audio_delta(b"\x02\x00" * 480))
self.assertIn("audio_backlog_overflow", logs.output[0])
await adapter._handle_message(json.dumps({"type": "response.done"}))
bridge.release_publish.set()
await adapter._output_queue.join()
await adapter._handle_message(json.dumps({"type": "response.created"}))
await adapter._handle_message(audio_delta(b"\x03\x00"))
```
- [ ] Run that focused test and observe the existing overflow exception.
- [ ] In `_handle_message()`, on overflow set `_suppress_response_audio=True`, log only `audio_backlog_overflow`, and return; on `response.done`, keep the existing reset. Leave queued audio intact until normal playout or `speech_started`.

```python
if self._pending_output_bytes + len(pcm) > MAX_PENDING_OUTPUT_BYTES:
    self._suppress_response_audio = True
    logger.warning("Qwen realtime event=audio_backlog_overflow")
else:
    self._queue_output(pcm)
```
- [ ] Add `RealtimeRuntimeError.code` with default `realtime_provider_error` and a fixed allowlist. Construct Qwen provider, connection-closed and output-publish errors with `provider_error`, `connection_closed`, and `audio_publish_failure`; `_safe_failure_reason()` returns only the allowlisted code. Add a test for these mappings and that supplied secret-like exception text cannot enter the diagnostic code.

```python
class RealtimeRuntimeError(RuntimeError):
    CODES = {"realtime_provider_error", "provider_error", "connection_closed", "audio_publish_failure"}

    def __init__(self, message: str, *, code: str = "realtime_provider_error"):
        super().__init__(message)
        self.code = code if code in self.CODES else "realtime_provider_error"
```
- [ ] Run focused tests, full Agent tests, `compileall` and `git diff --check`; commit `fix: keep realtime call alive on backlog overflow`.

### Task 3: Review and deploy safely

**Files:** No additional source files unless review or testing finds a defect.

- [ ] Independently review branch diff against `3689e6a`, resolving all Critical/Important findings with tests.
- [ ] Run all Agent tests in a no-network, 512 MB throwaway container on the ECS using the exact commit to be deployed; verify no failures.
- [ ] Confirm server still runs rollback image `sha256:a4e279a85bbf821834412c9309d70ad01f9f00cb5e69cb243fc6dd7490131cd7`, save that tag, fast-forward main, push GitHub, transfer a verified bundle if direct server pull again fails TLS, and rebuild only Agent.
- [ ] Verify Worker registration, restart count, API health, and absence of `audio_backlog_overflow` or `audio_publish_failure` during a real call. Test first greeting, later response and interruption. If real call cannot be performed, report this explicitly rather than claiming it passed.

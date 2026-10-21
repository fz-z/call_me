# Realtime Voice Audition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin enter one-off audition text and hear a short WAV sample from an existing Qwen realtime voice binding.

**Architecture:** A dedicated API service owns the short-lived Qwen WebSocket and bounded PCM-to-WAV conversion. A voice-admin endpoint resolves the exact existing realtime binding and returns base64 WAV without exposing provider IDs. A separate Vue modal owns the one-off text, request cancellation and audio URL lifecycle; the detail page only opens it for a selected binding.

**Tech Stack:** FastAPI, Pydantic, aiohttp, SQLite, pytest, Vue 3, Axios, Node test runner, Vite.

**Spec:** `docs/superpowers/specs/2026-10-21-realtime-voice-audition-design.md`

---

## File map

- Create `api/realtime_audition.py`: WebSocket event protocol, 35-second deadline, 2 MiB PCM cap, 24 kHz mono WAV output and safe exception classes.
- Create `api/tests/test_realtime_audition.py`: injected fake WebSocket/session behavior tests without paid model calls.
- Modify `api/models.py`: one-off audition request with stripped, 1–120-code-point text.
- Modify `api/voices.py`: admin-only exact-binding route and safe error mapping.
- Modify `api/tests/test_voices.py`: route, authorization, validation and non-persistence tests.
- Create `web-admin/src/utils/realtimeVoiceAudition.js` and `web-admin/test/realtimeVoiceAudition.test.js`: text validation and stale-response guard.
- Create `web-admin/src/components/RealtimeVoiceAudition.vue`: modal form, Axios cancellation, player and URL cleanup.
- Modify `web-admin/src/views/VoiceDetailView.vue`: per-binding audition button and modal placement; reset on route change.

## Task 1: Bounded realtime audio service

**Files:** Create `api/realtime_audition.py`; create `api/tests/test_realtime_audition.py`.

- [ ] **Step 1: Write a failing protocol test.** Create the test file with this first case (the fake is reused by later cases):

```python
import base64
import io
import json
import wave
from types import SimpleNamespace

import aiohttp
import pytest

from realtime_audition import synthesize_realtime_preview


class FakeSocket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send_json(self, event):
        self.sent.append(event)

    async def receive(self):
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(next(self.events)))


class FakeSession:
    def __init__(self, socket):
        self.socket = socket
        self.closed = False
        self.url = None
        self.headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    def ws_connect(self, url, *, headers):
        self.url, self.headers = url, headers
        return self.socket


@pytest.mark.asyncio
async def test_preview_uses_bound_voice_and_returns_wav():
    pcm = b"\x01\x00\x02\x00"
    socket = FakeSocket([
        {"type": "response.audio.delta", "delta": base64.b64encode(pcm).decode()},
        {"type": "response.done", "response": {"status": "completed"}},
    ])
    session = FakeSession(socket)
    result = await synthesize_realtime_preview(
        api_key="test-key", endpoint="wss://example.test/api-ws/v1/realtime?model=old",
        model="qwen-audio-3.1-realtime-plus", voice_id="cloned-voice", text="你好",
        session_factory=lambda: session,
    )
    assert session.url.count("model=") == 1
    assert "model=qwen-audio-3.1-realtime-plus" in session.url
    assert session.headers == {"Authorization": "Bearer test-key"}
    assert socket.sent[0]["session"]["voice"] == "cloned-voice"
    assert socket.sent[1]["item"]["content"][0]["type"] == "input_text"
    assert "你好" in socket.sent[1]["item"]["content"][0]["text"]
    assert socket.sent[2]["type"] == "response.create"
    with wave.open(io.BytesIO(result), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert wav.readframes(2) == pcm
    assert socket.closed and session.closed
```
- [ ] **Step 2: Run `cd api && python -m pytest tests/test_realtime_audition.py -q`.** Expected RED: module/function missing.
- [ ] **Step 3: Implement the service.** Start with this complete success-path implementation in `api/realtime_audition.py`:

```python
import asyncio
import base64
import io
import json
import wave
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp

MAX_PCM_BYTES = 2 * 1024 * 1024
TOTAL_TIMEOUT_SECONDS = 35

class RealtimeAuditionError(Exception):
    pass

class RealtimeAuditionTooLarge(RealtimeAuditionError):
    pass


def _model_endpoint(endpoint: str, model: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise RealtimeAuditionError("Invalid realtime endpoint")
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "model"]
    query.append(("model", model))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _wav(pcm: bytes) -> bytes:
    result = io.BytesIO()
    with wave.open(result, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(pcm)
    return result.getvalue()


async def synthesize_realtime_preview(
    *, api_key: str, endpoint: str, model: str, voice_id: str, text: str,
    session_factory=None,
) -> bytes:
    async def generate():
        pcm = bytearray()
        async with (session_factory or aiohttp.ClientSession)() as session:
            async with session.ws_connect(
                _model_endpoint(endpoint, model),
                headers={"Authorization": f"Bearer {api_key}"},
            ) as socket:
                await socket.send_json({"type": "session.update", "session": {
                    "voice": voice_id, "modalities": ["audio", "text"],
                    "input_audio_format": "pcm", "output_audio_format": "pcm",
                }})
                await socket.send_json({"type": "conversation.item.create", "item": {
                    "type": "message", "role": "user", "content": [{"type": "input_text",
                        "text": f"请只逐字朗读以下文案，不要回答或添加内容：{text}"}],
                }})
                await socket.send_json({"type": "response.create"})
                while True:
                    message = await socket.receive()
                    if message.type != aiohttp.WSMsgType.TEXT:
                        raise RealtimeAuditionError("Realtime connection closed before completion")
                    try:
                        event = json.loads(message.data)
                    except (TypeError, json.JSONDecodeError) as error:
                        raise RealtimeAuditionError("Invalid realtime response") from error
                    if not isinstance(event, dict):
                        raise RealtimeAuditionError("Invalid realtime response")
                    if event.get("type") == "response.audio.delta":
                        try:
                            chunk = base64.b64decode(event["delta"], validate=True)
                        except (KeyError, ValueError, TypeError) as error:
                            raise RealtimeAuditionError("Invalid realtime audio") from error
                        if len(chunk) % 2:
                            raise RealtimeAuditionError("Invalid realtime audio")
                        if len(pcm) + len(chunk) > MAX_PCM_BYTES:
                            raise RealtimeAuditionTooLarge("Realtime preview exceeds audio limit")
                        pcm.extend(chunk)
                    elif event.get("type") == "response.done":
                        if event.get("response", {}).get("status") != "completed":
                            raise RealtimeAuditionError("Realtime preview did not complete")
                        if not pcm:
                            raise RealtimeAuditionError("Realtime preview returned no audio")
                        return _wav(bytes(pcm))
                    elif event.get("type") == "error":
                        raise RealtimeAuditionError("Realtime provider rejected preview")

    return await asyncio.wait_for(generate(), TOTAL_TIMEOUT_SECONDS)
```

  Do not include the API key, voice ID or raw provider payload in exception messages.
- [ ] **Step 4: Run the same test.** Expected GREEN.
- [ ] **Step 5: Add error-path cases.** Parameterize events with `response.done` and `status="failed"`, an `error` event, malformed base64 `delta="!"`, odd PCM `delta="AQ=="`, an audio delta larger than `MAX_PCM_BYTES`, and completed response without audio; assert `RealtimeAuditionError`/`RealtimeAuditionTooLarge` and both fake resources closed. For timeout, monkeypatch `TOTAL_TIMEOUT_SECONDS=0.01` and make `receive()` wait on an unset `asyncio.Event`; assert `asyncio.TimeoutError` and closure. Run the file RED if an assertion exposes a gap, then add only the missing guard.
- [ ] **Step 6: Rerun `python -m pytest tests/test_realtime_audition.py -q` to GREEN.** Commit with `git add api/realtime_audition.py api/tests/test_realtime_audition.py && git commit -m 'feat(api): generate bounded realtime voice preview'`.

## Task 2: Admin endpoint for one exact binding

**Files:** Modify `api/models.py`, `api/voices.py`; modify `api/tests/test_voices.py`.

- [ ] **Step 1: Write a failing API test.** Append this case to `api/tests/test_voices.py` (the fixture initializes the DB). It uses an inline config with a legacy key solely in the test DB:

```python
class TestRealtimeAudition:
    def _binding(self):
        from database import _sync_conn
        voice_id, config_id = str(uuid.uuid4()), str(uuid.uuid4())
        now = "2026-10-21T00:00:00+00:00"
        db = _sync_conn()
        try:
            db.execute("INSERT INTO voices (id,name,voice_id,type,created_at) VALUES (?,?,?,?,?)",
                       (voice_id, "试听音色", "", "cloned", now))
            db.execute("INSERT INTO realtime_configs "
                       "(id,name,provider,model,api_key,endpoint,capabilities_json,created_at) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (config_id, "试听模型", "qwen", "qwen-audio-3.1-realtime-plus",
                        "test-key", "wss://example.test/api-ws/v1/realtime", '{"voice_clone":true}', now))
            db.execute("INSERT INTO voice_runtime_bindings "
                       "(id,voice_pool_id,runtime_kind,runtime_config_id,provider_voice_id,created_at) "
                       "VALUES (?,?,'realtime',?,?,?)",
                       (str(uuid.uuid4()), voice_id, config_id, "provider-preview-voice", now))
            db.commit()
        finally:
            db.close()
        return voice_id, config_id

    def test_exact_binding_and_one_off_text(self, clean_db, monkeypatch):
        import base64
        import voices
        voice_id, config_id = self._binding()
        captured = {}

        async def fake_preview(**kwargs):
            captured.update(kwargs)
            return b"RIFF-preview"

        monkeypatch.setattr(voices, "synthesize_realtime_preview", fake_preview)
        response = client.post(
            f"/api/admin/voices/{voice_id}/realtime-bindings/{config_id}/audition",
            headers=_admin_header(), json={"text": " 你好 "},
        )
        assert response.status_code == 200, response.text
        assert base64.b64decode(response.json()["audio_base64"]) == b"RIFF-preview"
        assert response.json()["mime_type"] == "audio/wav"
        assert captured["voice_id"] == "provider-preview-voice"
        assert captured["text"] == "你好"
        assert "provider-preview-voice" not in response.text
        assert "test-key" not in response.text
        from database import _sync_conn
        db = _sync_conn()
        try:
            assert db.execute("SELECT COUNT(*) FROM voice_runtime_bindings WHERE voice_pool_id=?", (voice_id,)).fetchone()[0] == 1
            assert db.execute("SELECT audition_text FROM voices WHERE id=?", (voice_id,)).fetchone()[0] is None
        finally:
            db.close()
```
- [ ] **Step 2: Run `cd api && python -m pytest tests/test_voices.py -q`.** Expected RED: route 404.
- [ ] **Step 3: Add request type and route.** Add the model below to `api/models.py` and import it in `api/voices.py`:

```python
class RealtimeAuditionRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 120:
            raise ValueError("Audition text must be 1–120 characters")
        return value
```

  Add `import asyncio`, `import base64`, `from runtime_bindings import resolve_voice_binding`, and `from realtime_audition import synthesize_realtime_preview, RealtimeAuditionError, RealtimeAuditionTooLarge` to `api/voices.py`, then add:

```python
@router.post("/{voice_id}/realtime-bindings/{realtime_config_id}/audition", response_model=AuditionResponse)
async def audition_realtime_binding(
    voice_id: str, realtime_config_id: str, body: RealtimeAuditionRequest,
    admin: dict = Depends(require_admin),
):
    db = _sync_conn()
    try:
        binding = resolve_voice_binding(db, voice_id, "realtime", realtime_config_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Realtime voice binding not found")
        config = _get_realtime_config(db, realtime_config_id)
        preview_args = {
            "api_key": config["resolved_api_key"], "endpoint": config["endpoint"],
            "model": config["model"], "voice_id": binding["provider_voice_id"],
            "text": body.text,
        }
    finally:
        db.close()
    try:
        wav = await synthesize_realtime_preview(**preview_args)
    except asyncio.TimeoutError as error:
        raise HTTPException(status_code=504, detail="实时音色试听超时，请稍后重试。") from error
    except RealtimeAuditionTooLarge as error:
        raise HTTPException(status_code=413, detail="试听音频过长，请缩短文案。") from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="实时音色试听生成失败，请检查模型配置后重试。") from error
    return AuditionResponse(audio_base64=base64.b64encode(wav).decode(), mime_type="audio/wav")
```
- [ ] **Step 4: Rerun the API test; expect GREEN.**
- [ ] **Step 5: Add API boundary cases.** Reuse `self._binding()` and the route: unauthenticated `client.post(...)` must not be 200; `text=" "` and `text="a" * 121` must return 422; random config ID must return 404. Monkeypatch `voices.synthesize_realtime_preview` with async functions raising `asyncio.TimeoutError`, `RealtimeAuditionTooLarge("limit")`, and `RuntimeError("test-key provider-preview-voice")`; expect 504, 413 and 502 respectively, and ensure the 502 JSON omits both sensitive strings. Change the inserted binding kind to `tts` and assert 404. Run these cases RED for any missing guard, implement the minimum fix and rerun `python -m pytest tests/test_voices.py tests/test_realtime_audition.py -q` to GREEN. Commit with `git add api/models.py api/voices.py api/tests/test_voices.py && git commit -m 'feat(api): expose realtime voice audition endpoint'`.

## Task 3: One-off audition modal

**Files:** Create `web-admin/src/utils/realtimeVoiceAudition.js`, `web-admin/test/realtimeVoiceAudition.test.js`, `web-admin/src/components/RealtimeVoiceAudition.vue`; modify `web-admin/src/views/VoiceDetailView.vue`.

- [ ] **Step 1: Write failing utility tests** in `web-admin/test/realtimeVoiceAudition.test.js`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { createGenerationGuard } from '../src/utils/voiceManagement.js';
import { getRealtimeAuditionTextError, runCurrentPreview } from '../src/utils/realtimeVoiceAudition.js';

test('one-off audition text is required and limited to 120 code points', () => {
  assert.match(getRealtimeAuditionTextError('  '), /请输入/);
  assert.match(getRealtimeAuditionTextError('字'.repeat(121)), /120/);
  assert.equal(getRealtimeAuditionTextError('字'.repeat(120)), '');
});

test('a response from a closed preview is discarded', async () => {
  const guard = createGenerationGuard();
  let resolve;
  const pending = new Promise((done) => { resolve = done; });
  const result = runCurrentPreview(() => pending, guard);
  guard.invalidate();
  resolve({ audio_base64: 'old' });
  assert.equal(await result, null);
  assert.deepEqual(await runCurrentPreview(async () => ({ audio_base64: 'new' }), guard),
    { audio_base64: 'new' });
});

test('a rejected request from a closed preview is discarded', async () => {
  const guard = createGenerationGuard();
  let reject;
  const pending = new Promise((_, fail) => { reject = fail; });
  const result = runCurrentPreview(() => pending, guard);
  guard.invalidate();
  reject(new Error('aborted'));
  assert.equal(await result, null);
});
```
- [ ] **Step 2: Run `cd web-admin && node --test test/realtimeVoiceAudition.test.js`.** Expected RED: utility missing.
- [ ] **Step 3: Implement the utility:**

```js
export const DEFAULT_REALTIME_AUDITION_TEXT = '你好，这是实时音色试听。';

export function getRealtimeAuditionTextError(text) {
  const trimmed = text.trim();
  if (!trimmed) return '请输入试听文案。';
  if (Array.from(trimmed).length > 120) return '试听文案不能超过 120 个字。';
  return '';
}

export async function runCurrentPreview(send, guard) {
  const generation = guard.next();
  try {
    const result = await send();
    return guard.isCurrent(generation) ? result : null;
  } catch (error) {
    if (!guard.isCurrent(generation)) return null;
    throw error;
  }
}
```

  Rerun the utility test to GREEN.
- [ ] **Step 4: Implement `RealtimeVoiceAudition.vue`** with this complete component; keep the modal independent from the classic TTS audition state:

```vue
<template>
  <div class="modal-overlay" @click.self="close">
    <form class="modal preview-modal" @submit.prevent="submit">
      <h3>实时音色试听 · {{ binding.runtime_config_name }}</h3>
      <p class="hint">使用此实时模型绑定的克隆音色生成短音频；每次生成可能产生模型费用。模型可能略微改写文案。</p>
      <label for="realtime-preview-text">本次试听文案</label>
      <textarea id="realtime-preview-text" v-model="text" rows="4"></textarea>
      <p class="hint">最多 120 个字；关闭后不会保存。</p>
      <p v-if="getRealtimeAuditionTextError(text)" class="error" role="alert">{{ getRealtimeAuditionTextError(text) }}</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <audio v-if="audioUrl" ref="player" :src="audioUrl" controls @error="error = '音频播放失败。'"></audio>
      <div class="actions">
        <button type="button" class="btn-ghost" @click="close">关闭</button>
        <button type="submit" class="btn btn-primary" :disabled="loading || !!getRealtimeAuditionTextError(text)">
          {{ loading ? '生成中…' : '生成试听' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue';
import api from '../api.js';
import { createGenerationGuard } from '../utils/voiceManagement.js';
import {
  DEFAULT_REALTIME_AUDITION_TEXT, getRealtimeAuditionTextError, runCurrentPreview,
} from '../utils/realtimeVoiceAudition.js';

const props = defineProps({ voiceId: { type: String, required: true }, binding: { type: Object, required: true } });
const emit = defineEmits(['close']);
const text = ref(DEFAULT_REALTIME_AUDITION_TEXT);
const loading = ref(false);
const error = ref('');
const audioUrl = ref('');
const player = ref(null);
const guard = createGenerationGuard();
let controller = null;

function releaseAudio() {
  player.value?.pause();
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value);
  audioUrl.value = '';
}
function cleanup() {
  guard.invalidate();
  controller?.abort();
  controller = null;
  loading.value = false;
  releaseAudio();
}
function close() { cleanup(); emit('close'); }
onBeforeUnmount(cleanup);

async function submit() {
  const message = getRealtimeAuditionTextError(text.value);
  if (message || loading.value) { error.value = message; return; }
  releaseAudio();
  error.value = '';
  loading.value = true;
  const requestController = new AbortController();
  controller = requestController;
  try {
    const response = await runCurrentPreview(() => api.post(
      `/admin/voices/${props.voiceId}/realtime-bindings/${props.binding.runtime_config_id}/audition`,
      { text: text.value.trim() }, { signal: requestController.signal },
    ), guard);
    if (!response) return;
    const bytes = Uint8Array.from(atob(response.data.audio_base64), (char) => char.charCodeAt(0));
    audioUrl.value = URL.createObjectURL(new Blob([bytes], { type: response.data.mime_type }));
  } catch (requestError) {
    if (!requestController.signal.aborted) {
      error.value = requestError.response?.data?.detail || '实时音色试听失败，请重试。';
    }
  } finally {
    if (controller === requestController) {
      controller = null;
      loading.value = false;
    }
  }
}
</script>

<style scoped>
.preview-modal { width: min(520px, calc(100vw - 32px)); min-width: 0; box-sizing: border-box; }
.preview-modal h3 { margin-bottom: 12px; }
.hint { color: #94a3b8; font-size: 12px; line-height: 1.6; margin: 8px 0; }
label { display: block; margin: 14px 0 6px; color: #cbd5e1; }
textarea { width: 100%; box-sizing: border-box; padding: 9px; background: #0f0f1a; color: #e0e0e0; border: 1px solid #475569; border-radius: 5px; }
audio { display: block; width: 100%; margin-top: 12px; }
.error { color: #f87171; font-size: 13px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
```
- [ ] **Step 5: Wire the parent.** In `VoiceDetailView.vue`, import `RealtimeVoiceAudition` and add `const activeRealtimeAudition = ref(null)` beside the other refs. Replace the second realtime help paragraph and binding action with:

```vue
<p class="section-help">点击绑定卡片上的“试听”可生成短音频；完整对话效果仍可在 <router-link to="/agents">Agent 管理</router-link> 中发起通话测试。</p>
<!-- inside each realtime binding card -->
<div class="binding-actions">
  <button class="btn-ghost subtle-action" @click="activeRealtimeAudition = binding">试听</button>
  <button class="btn-ghost subtle-action" @click="openReplaceClone(binding)">重新复刻</button>
</div>
<!-- after the detail cards, within the root voice-detail div -->
<RealtimeVoiceAudition v-if="activeRealtimeAudition && voice"
  :key="activeRealtimeAudition.id" :voice-id="voice.id" :binding="activeRealtimeAudition"
  @close="activeRealtimeAudition = null" />
```

  Add `.binding-actions { display:flex; gap:8px; flex-wrap:wrap; }` to the scoped style. Set `activeRealtimeAudition.value = null` in the existing `watch(() => route.params.id, ...)` route-change block and in its `onBeforeUnmount` callback. A new `v-if` component instance restores the example text whenever a binding is reopened.
- [ ] **Step 6: Run `node --test test/*.test.js && npm run build` in `web-admin`; expect all tests and build to pass.** Manually inspect narrow and desktop layouts using a local test API, including close while pending, retry, binding switch, player cleanup and validation; do not trigger a paid supplier call unless explicitly testing with an approved account. Commit with `git add web-admin/src/utils/realtimeVoiceAudition.js web-admin/test/realtimeVoiceAudition.test.js web-admin/src/components/RealtimeVoiceAudition.vue web-admin/src/views/VoiceDetailView.vue && git commit -m 'feat(admin): audition cloned realtime voices'`.

## Final verification and handoff

- [ ] Run `PHOTOS_DIR=/private/tmp/call_me_realtime_audition_photos python -m pytest tests/test_realtime_audition.py tests/test_voices.py tests/test_agents.py -q` from `api`; report counts and skips.
- [ ] Run `node --test test/*.test.js && npm run build` from `web-admin`; report counts and build result.
- [ ] Run `git diff <base>..HEAD --check` and inspect changed files against every spec bullet; verify no secret, provider voice ID, paid test call or persisted audition text was introduced.
- [ ] Request read-only code review, address findings, rerun relevant tests, then offer merge/PR/keep/discard options. Do not push or deploy without a separate user request.

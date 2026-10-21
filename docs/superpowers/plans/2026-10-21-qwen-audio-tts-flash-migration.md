# Qwen Audio 3.1 TTS Flash Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `qwen-audio-3.1-tts-flash` work for admin audition and pipeline Agent speech, then migrate confirmed source recordings to model-compatible cloned voice IDs without risking the existing bindings.

**Architecture:** Add one focused HTTP protocol adapter in the API and mirror the same request contract in the Agent's existing Qwen TTS class. Both paths use the workspace-scoped `SpeechSynthesizer` endpoint, accept inline audio or a temporary audio URL, and surface provider errors. Deployment config supplies the exact workspace endpoint; voice bindings change only after cloning and a successful synthesis probe.

**Tech Stack:** Python 3.11, FastAPI, aiohttp, DashScope/Model Studio HTTP APIs, LiveKit Agents, pytest/unittest, SQLite, Docker Compose.

---

## File Structure

- `api/tts_strategy.py`: add the Qwen Audio HTTP strategy, endpoint validation, provider response parsing, and strategy routing.
- `api/tests/test_tts_strategy.py`: API audition protocol and error regression tests.
- `agent/qwen_tts.py`: select the Qwen Audio request shape in the pipeline worker and retain legacy/realtime behavior.
- `agent/tests/test_qwen_tts.py`: worker request-shape and audio URL tests.
- `agent/agent.py`: use the dedicated Qwen Audio endpoint when constructing configured TTS.
- `.env.example`: document workspace-scoped Qwen Audio endpoint variables without secrets.
- `OPS.md`: document safe production configuration, verification, and rollback.

### Task 1: Preserve realtime diagnostics as an isolated change

**Files:**
- Modify: `api/tts_strategy.py:114`
- Test: `api/tests/test_tts_strategy.py`

- [ ] **Step 1: Run the existing focused regression tests**

Run:

```bash
PHOTOS_DIR=/private/tmp/call_me_photos_test python3 -m pytest api/tests/test_tts_strategy.py -q
```

Expected: both realtime error tests pass, including close code `1007` and `Model not exist.`.

- [ ] **Step 2: Commit only the already-tested realtime diagnostic change**

```bash
git add api/tts_strategy.py api/tests/test_tts_strategy.py
git commit -m "fix: expose Qwen realtime close errors"
```

Expected: commit succeeds and the worktree contains no uncommitted API strategy changes.

### Task 2: Add Qwen Audio API audition support

**Files:**
- Modify: `api/tts_strategy.py`
- Test: `api/tests/test_tts_strategy.py`

- [ ] **Step 1: Write failing strategy-selection and endpoint tests**

Add tests that express the required public behavior:

```python
from tts_strategy import QwenAudioHttpStrategy, get_tts_strategy


def test_qwen_audio_model_selects_dedicated_http_strategy():
    assert isinstance(get_tts_strategy("qwen-audio-3.1-tts-flash"), QwenAudioHttpStrategy)


def test_qwen_audio_endpoint_requires_workspace(monkeypatch):
    monkeypatch.delenv("QWEN_AUDIO_TTS_API_URL", raising=False)
    monkeypatch.delenv("DASHSCOPE_WORKSPACE", raising=False)
    with pytest.raises(RuntimeError, match="DASHSCOPE_WORKSPACE"):
        QwenAudioHttpStrategy()._api_url()


def test_qwen_audio_endpoint_uses_workspace(monkeypatch):
    monkeypatch.delenv("QWEN_AUDIO_TTS_API_URL", raising=False)
    monkeypatch.setenv("DASHSCOPE_WORKSPACE", "llm-example")
    assert QwenAudioHttpStrategy()._api_url() == (
        "https://llm-example.cn-beijing.maas.aliyuncs.com/"
        "api/v1/services/audio/tts/SpeechSynthesizer"
    )
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
PHOTOS_DIR=/private/tmp/call_me_photos_test python3 -m pytest \
  api/tests/test_tts_strategy.py::test_qwen_audio_model_selects_dedicated_http_strategy \
  api/tests/test_tts_strategy.py::test_qwen_audio_endpoint_requires_workspace \
  api/tests/test_tts_strategy.py::test_qwen_audio_endpoint_uses_workspace -q
```

Expected: FAIL because `QwenAudioHttpStrategy` does not exist.

- [ ] **Step 3: Implement endpoint resolution and routing**

Add the dedicated strategy shell and route Qwen Audio TTS model IDs to it:

```python
class QwenAudioHttpStrategy(TtsStrategy):
    def _api_url(self) -> str:
        override = os.environ.get("QWEN_AUDIO_TTS_API_URL", "").strip()
        if override:
            return override.rstrip("/")
        workspace = os.environ.get("DASHSCOPE_WORKSPACE", "").strip()
        if not workspace:
            raise RuntimeError(
                "DASHSCOPE_WORKSPACE is required for Qwen Audio TTS"
            )
        return (
            f"https://{workspace}.cn-beijing.maas.aliyuncs.com/"
            "api/v1/services/audio/tts/SpeechSynthesizer"
        )


def get_tts_strategy(model: str) -> TtsStrategy:
    m = (model or "").lower()
    if m.startswith("qwen-audio-") and "-tts-" in m:
        return QwenAudioHttpStrategy()
    # retain existing branches unchanged
```

- [ ] **Step 4: Run the endpoint tests and verify GREEN**

Run the command from Step 2.

Expected: 3 passed.

- [ ] **Step 5: Write the failing synthesis/download test**

Use an in-process aiohttp test server so the test exercises real JSON parsing and the follow-up download:

```python
@pytest.mark.asyncio
async def test_qwen_audio_synthesizes_from_provider_audio_url(monkeypatch):
    seen = {}

    async def synthesize(request):
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = await request.json()
        return web.json_response({
            "request_id": "req-1",
            "output": {"audio": {"url": str(request.url.with_path("/audio.wav"))}},
        })

    async def audio(_request):
        return web.Response(body=b"RIFFtest", content_type="audio/wav")

    app = web.Application()
    app.router.add_post("/synthesize", synthesize)
    app.router.add_get("/audio.wav", audio)
    server = TestServer(app)
    await server.start_server()
    try:
        monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", str(server.make_url("/synthesize")))
        encoded, mime = await QwenAudioHttpStrategy().synthesize(
            {"model": "qwen-audio-3.1-tts-flash", "resolved_key": "secret", "api_key": ""},
            "qwen-audio-3.1-tts-flash-ls-1234",
            "你好",
        )
    finally:
        await server.close()

    assert base64.b64decode(encoded) == b"RIFFtest"
    assert mime == "audio/wav"
    assert seen["authorization"] == "Bearer secret"
    assert seen["body"] == {
        "model": "qwen-audio-3.1-tts-flash",
        "input": {
            "text": "你好",
            "voice": "qwen-audio-3.1-tts-flash-ls-1234",
            "format": "wav",
            "sample_rate": 24000,
        },
    }
```

- [ ] **Step 6: Run the synthesis test and verify RED**

Run:

```bash
PHOTOS_DIR=/private/tmp/call_me_photos_test python3 -m pytest \
  api/tests/test_tts_strategy.py::test_qwen_audio_synthesizes_from_provider_audio_url -q
```

Expected: FAIL because `QwenAudioHttpStrategy.synthesize` has not been implemented.

- [ ] **Step 7: Implement the minimal synthesis behavior**

Implement the official request body, parse `output.audio.data` or `output.audio.url`, download the URL with a 60-second timeout and a 20 MiB response limit, and reject non-audio downloads:

```python
async def synthesize(self, tts_row, voice_id: str, text: str) -> tuple[str, str]:
    api_key = tts_row["resolved_key"] or tts_row["api_key"]
    body = {
        "model": tts_row["model"],
        "input": {
            "text": text,
            "voice": voice_id,
            "format": "wav",
            "sample_rate": 24000,
        },
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(self._api_url(), json=body, headers=headers) as response:
            payload = await _read_qwen_json(response)
        audio = payload.get("output", {}).get("audio", {})
        if audio.get("data"):
            return audio["data"], "audio/wav"
        if not audio.get("url"):
            raise RuntimeError(_qwen_error_detail(payload, "missing audio URL"))
        async with session.get(audio["url"]) as download:
            raw = await _read_bounded_audio(download, 20 * 1024 * 1024)
    return base64.b64encode(raw).decode("utf-8"), "audio/wav"
```

Helper functions must include provider `code`, `message`, and `request_id` in raised errors and must never include the API key.

- [ ] **Step 8: Add and run error-path tests**

Add a parameterized provider-error test and explicit response validation tests:

```python
@pytest.mark.asyncio
async def test_qwen_audio_surfaces_provider_error(monkeypatch):
    async def synthesize(_request):
        return web.json_response(
            {"request_id": "req-bad", "code": "InvalidParameter", "message": "bad voice"},
            status=400,
        )

    app = web.Application()
    app.router.add_post("/synthesize", synthesize)
    server = TestServer(app)
    await server.start_server()
    try:
        monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", str(server.make_url("/synthesize")))
        with pytest.raises(RuntimeError, match="InvalidParameter.*bad voice.*req-bad"):
            await QwenAudioHttpStrategy().synthesize(
                {"model": "qwen-audio-3.1-tts-flash", "resolved_key": "secret", "api_key": ""},
                "bad-voice",
                "你好",
            )
    finally:
        await server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("download_body", "content_type", "expected"),
    [
        (b"not audio", "text/plain", "non-audio"),
        (b"x" * (20 * 1024 * 1024 + 1), "audio/wav", "too large"),
    ],
)
async def test_qwen_audio_rejects_invalid_download(
    monkeypatch, download_body, content_type, expected
):
    async def synthesize(request):
        return web.json_response({
            "output": {"audio": {"url": str(request.url.with_path("/audio"))}}
        })

    async def audio(_request):
        return web.Response(body=download_body, content_type=content_type)

    app = web.Application()
    app.router.add_post("/synthesize", synthesize)
    app.router.add_get("/audio", audio)
    server = TestServer(app)
    await server.start_server()
    try:
        monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", str(server.make_url("/synthesize")))
        with pytest.raises(RuntimeError, match=expected):
            await QwenAudioHttpStrategy().synthesize(
                {"model": "qwen-audio-3.1-tts-flash", "resolved_key": "secret", "api_key": ""},
                "voice",
                "你好",
            )
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_qwen_audio_rejects_missing_audio_url(monkeypatch):
    async def synthesize(_request):
        return web.json_response({"request_id": "req-empty", "output": {"audio": {}}})

    app = web.Application()
    app.router.add_post("/synthesize", synthesize)
    server = TestServer(app)
    await server.start_server()
    try:
        monkeypatch.setenv("QWEN_AUDIO_TTS_API_URL", str(server.make_url("/synthesize")))
        with pytest.raises(RuntimeError, match="missing audio URL.*req-empty"):
            await QwenAudioHttpStrategy().synthesize(
                {"model": "qwen-audio-3.1-tts-flash", "resolved_key": "secret", "api_key": ""},
                "voice",
                "你好",
            )
    finally:
        await server.close()
```

Add `from aiohttp import web` and `from aiohttp.test_utils import TestServer` to the test imports. Run:

```bash
PHOTOS_DIR=/private/tmp/call_me_photos_test python3 -m pytest api/tests/test_tts_strategy.py -q
```

Expected: all API strategy tests pass.

- [ ] **Step 9: Commit the API adapter**

```bash
git add api/tts_strategy.py api/tests/test_tts_strategy.py
git commit -m "feat: support Qwen Audio TTS audition"
```

### Task 3: Adapt pipeline Agent synthesis

**Files:**
- Modify: `agent/qwen_tts.py`
- Modify: `agent/agent.py`
- Test: `agent/tests/test_qwen_tts.py`

- [ ] **Step 1: Write failing request-shape tests**

Add tests that instantiate `QwenTTS` and assert the new model uses the official body while a legacy model retains its old body:

```python
def test_qwen_audio_build_body_uses_speech_synthesizer_contract(self):
    tts = QwenTTS(
        api_url="https://workspace.example/synthesize",
        api_key="secret",
        model="qwen-audio-3.1-tts-flash",
        voice_id="qwen-audio-3.1-tts-flash-ls-1234",
    )
    self.assertEqual(tts._build_body(text="你好"), {
        "model": "qwen-audio-3.1-tts-flash",
        "input": {
            "text": "你好",
            "voice": "qwen-audio-3.1-tts-flash-ls-1234",
            "format": "wav",
            "sample_rate": 24000,
        },
    })


def test_legacy_qwen_body_keeps_response_format(self):
    tts = QwenTTS(
        api_url="https://legacy.example/generation",
        api_key="secret",
        model="qwen-tts",
        voice="Cherry",
    )
    self.assertIn("parameters", tts._build_body(text="你好"))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=agent python3 -m unittest agent.tests.test_qwen_tts -v
```

Expected: the Qwen Audio body test fails because the legacy response format is still present.

- [ ] **Step 3: Implement model-family-specific body construction**

Add `_is_qwen_audio_tts_model` and branch in `_build_body`:

```python
def _is_qwen_audio_tts_model(self) -> bool:
    model = (self._model or "").lower()
    return model.startswith("qwen-audio-") and "-tts-" in model


if self._is_qwen_audio_tts_model():
    return _deep_merge({
        "model": self._model,
        "input": {
            "text": text,
            "voice": self._voice_id or self._voice,
            "format": self._audio_format,
            "sample_rate": self.sample_rate,
        },
    }, self._extra_body)
```

Retain the existing legacy body after this branch.

- [ ] **Step 4: Configure the Agent endpoint without affecting realtime TTS**

Add a small resolver in `agent/agent.py`:

```python
def _qwen_tts_api_url(model: str) -> str:
    if model.lower().startswith("qwen-audio-") and "-tts-" in model.lower():
        url = os.getenv("QWEN_AUDIO_TTS_API_URL", "").strip()
        if not url:
            raise RuntimeError("QWEN_AUDIO_TTS_API_URL is required for Qwen Audio TTS")
        return url
    return os.getenv(
        "QWEN_TTS_API_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation",
    )
```

Use it for both configured and fallback Qwen TTS construction. Do not change the separate realtime adapter.

- [ ] **Step 5: Add async download validation tests**

Create an isolated async test class that exercises `_call_qwen_tts` against a local server:

```python
class QwenTTSHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if hasattr(self, "tts"):
            await self.tts.aclose()

    async def test_qwen_audio_downloads_audio_url(self):
        seen = {}

        async def synthesize(request):
            seen["body"] = await request.json()
            return web.json_response({
                "output": {"audio": {"url": str(request.url.with_path("/audio.wav"))}}
            })

        async def audio(_request):
            return web.Response(body=b"RIFFagent", content_type="audio/wav")

        app = web.Application()
        app.router.add_post("/synthesize", synthesize)
        app.router.add_get("/audio.wav", audio)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        self.tts = QwenTTS(
            api_url=str(server.make_url("/synthesize")),
            api_key="secret",
            model="qwen-audio-3.1-tts-flash",
            voice_id="qwen-audio-3.1-tts-flash-ls-1234",
        )

        self.assertEqual(await _call_qwen_tts(tts=self.tts, text="你好"), b"RIFFagent")
        self.assertEqual(seen["body"], self.tts._build_body(text="你好"))

    async def test_qwen_audio_surfaces_provider_error(self):
        async def synthesize(_request):
            return web.json_response(
                {"request_id": "req-agent", "code": "InvalidParameter", "message": "bad voice"},
                status=400,
            )

        app = web.Application()
        app.router.add_post("/synthesize", synthesize)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        self.tts = QwenTTS(
            api_url=str(server.make_url("/synthesize")),
            api_key="secret",
            model="qwen-audio-3.1-tts-flash",
            voice_id="bad-voice",
        )

        with self.assertRaisesRegex(RuntimeError, "InvalidParameter.*bad voice.*req-agent"):
            await _call_qwen_tts(tts=self.tts, text="你好")

    async def test_download_rejects_non_audio_content(self):
        session = aiohttp.ClientSession()
        self.addAsyncCleanup(session.close)

        async def not_audio(_request):
            return web.Response(text="provider error", content_type="text/plain")

        app = web.Application()
        app.router.add_get("/audio", not_audio)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        with self.assertRaisesRegex(RuntimeError, "non-audio"):
            await _download_audio(session=session, url=str(server.make_url("/audio")))
```

Import `aiohttp`, `web`, `TestServer`, `QwenTTS`, `_call_qwen_tts`, and `_download_audio` in the test module.

- [ ] **Step 6: Run Agent tests and verify GREEN**

Run:

```bash
PYTHONPATH=agent python3 -m unittest discover -s agent/tests -p 'test_*.py' -v
```

Expected: all Agent unit tests pass.

- [ ] **Step 7: Commit the Agent adapter**

```bash
git add agent/qwen_tts.py agent/agent.py agent/tests/test_qwen_tts.py
git commit -m "feat: use Qwen Audio TTS in pipeline agents"
```

### Task 4: Document and verify workspace configuration

**Files:**
- Modify: `.env.example`
- Modify: `OPS.md`

- [ ] **Step 1: Add non-secret configuration examples**

Add:

```dotenv
# Qwen Audio TTS requires the workspace-specific Beijing endpoint.
# DASHSCOPE_WORKSPACE=llm-xxxxxxxxxxxxxxxx
# QWEN_AUDIO_TTS_API_URL=https://llm-xxxxxxxxxxxxxxxx.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer
```

Document that the API key, workspace, cloned voice, and endpoint must belong to the same region and workspace.

- [ ] **Step 2: Run repository verification**

Run:

```bash
PHOTOS_DIR=/private/tmp/call_me_photos_test python3 -m pytest \
  api/tests/test_tts_strategy.py api/tests/test_voice_enrollment.py api/tests/test_voices.py -q
PYTHONPATH=agent python3 -m unittest discover -s agent/tests -p 'test_*.py' -v
git diff --check
```

Expected: all tests pass and `git diff --check` emits no output.

- [ ] **Step 3: Commit documentation**

```bash
git add .env.example OPS.md
git commit -m "docs: configure workspace Qwen Audio TTS"
```

### Task 5: Deploy API and Agent safely

**Files:**
- Production `/opt/call_me/.env`
- Production `/opt/call_me` checkout

- [ ] **Step 1: Push committed code**

```bash
git push origin main
```

Expected: `origin/main` advances to the verified local revision.

- [ ] **Step 2: Back up production state**

Create a timestamped copy of `/data/call_me.db` from the API container and record the current Git revision. Verify that the backup file is non-empty before continuing.

- [ ] **Step 3: Configure the exact workspace endpoint**

Derive the workspace ID from the existing production realtime endpoint, then set these in `/opt/call_me/.env` without printing the API key:

```dotenv
DASHSCOPE_WORKSPACE=llm-w0jopd6ymx2yvtr1
QWEN_AUDIO_TTS_API_URL=https://llm-w0jopd6ymx2yvtr1.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer
```

- [ ] **Step 4: Pull and rebuild one service at a time**

```bash
cd /opt/call_me
git pull --ff-only origin main
docker compose up -d --build api
docker compose up -d --build agent
```

Expected: both containers become healthy/running without exceeding the server memory limit.

- [ ] **Step 5: Verify the old voice fails safely**

Use admin audition once. Expected before voice migration: a precise incompatible-voice error, not `url error`, `Model not exist`, or a generic no-audio message. Confirm the database voice IDs are unchanged.

### Task 6: Recreate and migrate confirmed voices

**Files:**
- Source recording: `/Users/zhangfuzhen/Desktop/Audio 2026-01-30 16.56.54.m4a`
- Production SQLite database through the API service

- [ ] **Step 1: Confirm which pool voice owns the recording**

Obtain an explicit LS or NN mapping from the user. Do not infer identity from the filename.

- [ ] **Step 2: Create the new provider voice through the admin upload endpoint**

Upload the confirmed recording with target model `qwen-audio-3.1-tts-flash`. Expected voice ID prefix:

```text
qwen-audio-3.1-tts-flash-
```

- [ ] **Step 3: Validate synthesis before replacing the binding**

Synthesize `你好，这是一段新音色测试。` with the new provider voice ID through the production adapter. Expected: non-empty WAV audio.

- [ ] **Step 4: Update the binding transactionally**

Back up the existing provider voice ID, then update only the confirmed classic TTS binding in one SQLite transaction. Do not change realtime bindings and do not delete the old provider voice.

- [ ] **Step 5: Repeat only for another voice with a confirmed source recording**

If no recording is available for the other voice, leave it unchanged and report that it still requires a source recording.

- [ ] **Step 6: Rename the TTS configuration display name**

After at least one migrated voice passes audition, update the TTS configuration name from `qwen3-tts-vc-realtime` to `qwen-audio-3.1-tts-flash`.

- [ ] **Step 7: Complete production verification**

Verify:

```text
/api/health returns success
API and Agent containers are running
migrated voice admin audition plays audio
pipeline Agent produces speech with the migrated voice
API/Agent logs contain no credential values
old provider voice IDs remain recorded for rollback
```

If any verification fails, restore the database backup or the saved binding, then redeploy the previous Git revision.

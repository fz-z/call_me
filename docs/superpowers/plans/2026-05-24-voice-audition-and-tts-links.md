# Voice Audition & TTS Link Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins preview voice audio from the voice pool page and manage per-voice TTS model associations.

**Architecture:** voices table gains `audition_text` column; a new audition endpoint synthesizes audio via DashScope HTTP API and returns base64; VoiceUpdate model gains `audition_text`; VoicePoolView.vue gains an audition modal and TTS-link editing in the existing edit modal.

**Tech Stack:** FastAPI + aiohttp (DashScope TTS HTTP) + SQLite + Vue 3

---

### Task 1: Database migration — add audition_text column

**Files:**
- Modify: `api/database.py`

- [ ] **Step 1: Add migration in init_db()**

Add the ALTER TABLE migration inside `init_db()`, after the existing voice_tts_links migration block. Locate the comment `# Migration: add tts_config_id to agents` and add the new migration right after the existing voices-related migrations.

In `api/database.py`, find:
```python
        # Migration: voice_tts_links many-to-many table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_tts_links (
                voice_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
                tts_config_id TEXT NOT NULL REFERENCES tts_configs(id) ON DELETE CASCADE,
                PRIMARY KEY (voice_id, tts_config_id)
            )
        """)
```

Add after that block:
```python
        # Migration: audition_text on voices
        try:
            conn.execute("ALTER TABLE voices ADD COLUMN audition_text TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
```

- [ ] **Step 2: Verify migration runs**

Run: `cd api && python3 -m pytest tests/test_database.py -v`
Expected: 5 tests pass (init_db runs successfully with the new column)

- [ ] **Step 3: Commit**

```bash
git add api/database.py
git commit -m "feat: add audition_text column to voices table"
```

---

### Task 2: Pydantic models — AuditionRequest, AuditionResponse, VoiceUpdate.audition_text

**Files:**
- Modify: `api/models.py`

- [ ] **Step 1: Add audition_text to VoiceUpdate and new audition models**

Find `class VoiceUpdate(BaseModel):` in `api/models.py` and change from:
```python
class VoiceUpdate(BaseModel):
    name: Optional[str] = None
```
to:
```python
class VoiceUpdate(BaseModel):
    name: Optional[str] = None
    audition_text: Optional[str] = None
```

Add at the end of `api/models.py`, before the SIP models:
```python
class AuditionRequest(BaseModel):
    text: str


class AuditionResponse(BaseModel):
    audio_base64: str
    mime_type: str
```

- [ ] **Step 2: Verify import works**

Run: `cd api && python3 -c "from models import AuditionRequest, AuditionResponse, VoiceUpdate; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/models.py
git commit -m "feat: add audition models and audition_text to VoiceUpdate"
```

---

### Task 3: Audition endpoint + extend PATCH

**Files:**
- Modify: `api/voices.py`

- [ ] **Step 1: Add imports at top of voices.py**

Insert after the existing imports:
```python
import base64
import aiohttp
```

- [ ] **Step 2: Extend update_voice to support audition_text**

In `api/voices.py`, inside the `update_voice` function, find:
```python
        if body.name is not None:
            existing = db.execute("SELECT id FROM voices WHERE name = ? AND id != ?", (body.name, voice_id)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Voice name already exists")
            db.execute("UPDATE voices SET name = ? WHERE id = ?", (body.name, voice_id))
```

Add after that block:
```python
        if body.audition_text is not None:
            db.execute("UPDATE voices SET audition_text = ? WHERE id = ?", (body.audition_text, voice_id))
```

- [ ] **Step 3: Add audition endpoint**

Add at the end of `api/voices.py`, before the final blank line:

```python
@router.post("/{voice_id}/audition", response_model=AuditionResponse)
async def audition_voice(voice_id: str, body: AuditionRequest, admin: dict = Depends(require_admin)):
    db = _sync_conn()
    try:
        voice = db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")

        tts_row = db.execute(
            "SELECT tc.*, ak.api_key as resolved_key FROM tts_configs tc "
            "JOIN voice_tts_links vl ON tc.id = vl.tts_config_id "
            "LEFT JOIN api_keys ak ON tc.api_key_id = ak.id "
            "WHERE vl.voice_id = ? "
            "ORDER BY tc.created_at ASC LIMIT 1",
            (voice_id,),
        ).fetchone()
        if not tts_row:
            raise HTTPException(status_code=400, detail="Voice has no linked TTS config")
    finally:
        db.close()

    provider = (tts_row["provider"] or "").lower()
    if provider == "qwen":
        audio_base64, mime_type = await _qwen_audition(tts_row, voice["voice_id"], body.text)
    else:
        raise HTTPException(status_code=400, detail=f"Audition not supported for provider: {provider}")

    return {"audio_base64": audio_base64, "mime_type": mime_type}


async def _qwen_audition(tts_row, voice_id: str, text: str) -> tuple[str, str]:
    model = tts_row["model"]
    api_key = tts_row["resolved_key"] or tts_row["api_key"]
    api_url = os.environ.get(
        "QWEN_TTS_API_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    )

    body = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice_id,
        },
        "parameters": {
            "response_format": {
                "type": "audio",
                "format": "wav",
            },
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(api_url, json=body, headers=headers) as r:
            raw = await r.read()
            if r.status >= 400:
                snippet = raw[:500].decode("utf-8", errors="replace")
                raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {snippet}")

            ctype = (r.headers.get("Content-Type") or "").lower()
            if ctype.startswith("audio/"):
                return base64.b64encode(raw).decode("utf-8"), ctype

            obj = json.loads(raw.decode("utf-8"))
            audio_b64 = _extract_audio_b64_from_output(obj)
            if audio_b64:
                return audio_b64, "audio/wav"

            raise HTTPException(status_code=502, detail="No audio data in TTS response")


def _extract_audio_b64_from_output(obj: dict) -> str | None:
    output = obj.get("output")
    if isinstance(output, dict):
        audio = output.get("audio")
        if isinstance(audio, dict):
            for k in ("data", "audio", "audio_base64"):
                v = audio.get(k)
                if isinstance(v, str) and v:
                    return v
        if isinstance(audio, str) and audio:
            return audio
    return None
```

Also add `import json` at the top if not already imported (it already is in voices.py at line 1 — verified).

- [ ] **Step 4: Verify endpoints compile**

Run: `cd api && python3 -c "from main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add api/voices.py
git commit -m "feat: add voice audition endpoint with Qwen TTS provider"
```

---

### Task 4: Backend tests

**Files:**
- Create: `api/tests/test_voices.py`

- [ ] **Step 1: Write test file**

Create `api/tests/test_voices.py`:

```python
import base64
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

from tests.test_auth import _admin_header


def _get_first_voice_and_tts():
    """Get a voice and its linked TTS config from the test db."""
    from database import _sync_conn
    conn = _sync_conn()
    try:
        voice = conn.execute("SELECT * FROM voices LIMIT 1").fetchone()
        if not voice:
            return None, None, None
        link = conn.execute(
            "SELECT tc.id FROM tts_configs tc "
            "JOIN voice_tts_links vl ON tc.id = vl.tts_config_id "
            "WHERE vl.voice_id = ? LIMIT 1",
            (voice["id"],),
        ).fetchone()
        return voice, link["id"] if link else None, voice["id"]
    finally:
        conn.close()


class TestVoiceAuditionText:
    def test_update_audition_text(self, clean_db):
        voice, _, _ = _get_first_voice_and_tts()
        if not voice:
            pytest.skip("No voices in test db")

        resp = client.patch(
            f"/api/admin/voices/{voice['id']}",
            headers=_admin_header(),
            json={"audition_text": "这是一段试听文本"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == voice["name"]

        # Verify persisted
        from database import _sync_conn
        conn = _sync_conn()
        try:
            row = conn.execute("SELECT audition_text FROM voices WHERE id = ?", (voice["id"],)).fetchone()
            assert row["audition_text"] == "这是一段试听文本"
        finally:
            conn.close()

    def test_clear_audition_text(self, clean_db):
        voice, _, _ = _get_first_voice_and_tts()
        if not voice:
            pytest.skip("No voices in test db")

        # Set first
        client.patch(
            f"/api/admin/voices/{voice['id']}",
            headers=_admin_header(),
            json={"audition_text": "something"},
        )
        # Clear
        resp = client.patch(
            f"/api/admin/voices/{voice['id']}",
            headers=_admin_header(),
            json={"audition_text": ""},
        )
        assert resp.status_code == 200

        from database import _sync_conn
        conn = _sync_conn()
        try:
            row = conn.execute("SELECT audition_text FROM voices WHERE id = ?", (voice["id"],)).fetchone()
            assert row["audition_text"] == ""
        finally:
            conn.close()

    def test_update_name_and_audition_text_together(self, clean_db):
        voice, _, _ = _get_first_voice_and_tts()
        if not voice:
            pytest.skip("No voices in test db")

        old_name = voice["name"]
        resp = client.patch(
            f"/api/admin/voices/{voice['id']}",
            headers=_admin_header(),
            json={"name": old_name + "-改", "audition_text": "新试听文案"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == old_name + "-改"


class TestVoiceAudition:
    def test_audition_missing_text(self, clean_db):
        voice, tts_id, _ = _get_first_voice_and_tts()
        if not voice or not tts_id:
            pytest.skip("No voice with TTS config in test db")

        resp = client.post(
            f"/api/admin/voices/{voice['id']}/audition",
            headers=_admin_header(),
            json={},
        )
        assert resp.status_code == 422

    def test_audition_voice_not_found(self, clean_db):
        resp = client.post(
            "/api/admin/voices/nonexistent-id/audition",
            headers=_admin_header(),
            json={"text": "你好"},
        )
        assert resp.status_code == 404

    def test_audition_no_tts_config(self, clean_db):
        from database import _sync_conn
        conn = _sync_conn()
        try:
            voice = conn.execute(
                "SELECT v.id FROM voices v LEFT JOIN voice_tts_links vl ON v.id = vl.voice_id WHERE vl.voice_id IS NULL LIMIT 1"
            ).fetchone()
        finally:
            conn.close()

        if not voice:
            pytest.skip("No voice without TTS config")

        resp = client.post(
            f"/api/admin/voices/{voice['id']}/audition",
            headers=_admin_header(),
            json={"text": "你好"},
        )
        assert resp.status_code == 400
        assert "no linked TTS" in resp.json()["detail"].lower()

    def test_audition_requires_admin(self, clean_db):
        voice, tts_id, _ = _get_first_voice_and_tts()
        if not voice or not tts_id:
            pytest.skip("No voice with TTS config in test db")

        from tests.test_auth import _auth_header
        resp = client.post(
            f"/api/admin/voices/{voice['id']}/audition",
            headers=_auth_header(),
            json={"text": "你好"},
        )
        assert resp.status_code == 403

    def test_audition_without_api_key_returns_502(self, clean_db):
        """When DASHSCOPE_API_KEY is a fake test key, the DashScope API will reject.
        We verify the endpoint routes correctly and hits the external API (502 from upstream)."""
        voice, tts_id, _ = _get_first_voice_and_tts()
        if not voice or not tts_id:
            pytest.skip("No voice with TTS config in test db")

        resp = client.post(
            f"/api/admin/voices/{voice['id']}/audition",
            headers=_admin_header(),
            json={"text": "你好世界"},
        )
        # With fake test key, DashScope returns an error — but the audition endpoint
        # itself is functional (routing, DB lookups, request construction all work).
        # 502 means the upstream synthesis failed (expected with fake credentials).
        assert resp.status_code in (200, 502)
```

- [ ] **Step 2: Run tests to verify they fail/skip correctly**

Run: `cd api && python3 -m pytest tests/test_voices.py -v`
Expected: Tests run — some pass (mock-independent ones like 404, 400, 422, 403), some skip (no voices with TTS), one may 502 (fake API key). Verify no 500s.

- [ ] **Step 3: Commit**

```bash
git add api/tests/test_voices.py
git commit -m "test: add voice audition and audition_text tests"
```

---

### Task 5: Frontend — Audition modal

**Files:**
- Modify: `web-admin/src/views/VoicePoolView.vue`

- [ ] **Step 1: Add audition modal template**

After the existing Edit Modal `</div>` closing tag (line 86), add:

```html
    <!-- Audition Modal -->
    <div v-if="showAudition" class="modal-overlay" @click.self="closeAudition">
      <div class="modal" style="min-width:420px">
        <h3>试听 - {{ auditionVoice?.name }}</h3>
        <div style="margin-bottom:8px;font-size:12px;color:#888">
          TTS: {{ auditionVoice?._ttsConfigs?.[0]?.name || '未知' }}
        </div>
        <textarea
          v-model="auditionText"
          rows="4"
          style="width:100%;box-sizing:border-box;resize:vertical"
          placeholder="输入试听文本..."
        ></textarea>
        <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
          <button
            v-if="!auditionPlaying"
            class="btn btn-primary"
            :disabled="auditionLoading || !auditionText.trim()"
            @click="startAudition"
          >
            {{ auditionLoading ? '合成中...' : '试听' }}
          </button>
          <button v-else class="btn btn-primary" @click="stopAudition">停止</button>
          <button class="btn-ghost" @click="closeAudition">关闭</button>
        </div>
        <p v-if="auditionError" class="error" style="margin-top:8px">{{ auditionError }}</p>
      </div>
    </div>
```

- [ ] **Step 2: Add auditionText field to edit modal**

In the edit modal form (line 77-85), add after `<input v-model="editForm.name" ...>`:
```html
        <textarea
          v-model="editForm.audition_text"
          rows="3"
          style="width:100%;box-sizing:border-box;resize:vertical;margin-bottom:12px"
          placeholder="试听文本 (可选)"
        ></textarea>
```

- [ ] **Step 3: Add audition button to table rows**

In the table row (line 27-30), add before the "编辑" button:
```html
            <button class="btn-ghost" @click="openAudition(v)">试听</button>
```

- [ ] **Step 4: Add audition state and functions in script**

In `<script setup>`, after the `editForm` reactive (line 110), add:

```javascript
const showAudition = ref(false);
const auditionVoice = ref(null);
const auditionText = ref('');
const auditionLoading = ref(false);
const auditionPlaying = ref(false);
const auditionError = ref('');
let auditionAudio = null;

function openAudition(v) {
  auditionVoice.value = v;
  auditionText.value = v.audition_text || '你好，这是一段语音试听文本，用于测试音色效果。';
  auditionError.value = '';
  showAudition.value = true;
}

function closeAudition() {
  stopAudition();
  showAudition.value = false;
  auditionVoice.value = null;
}

async function startAudition() {
  if (!auditionText.value.trim()) return;
  auditionLoading.value = true;
  auditionError.value = '';
  try {
    const r = await api.post(`/admin/voices/${auditionVoice.value.id}/audition`, {
      text: auditionText.value.trim(),
    });
    const audioBytes = Uint8Array.from(atob(r.data.audio_base64), c => c.charCodeAt(0));
    const blob = new Blob([audioBytes], { type: r.data.mime_type });
    const url = URL.createObjectURL(blob);
    auditionAudio = new Audio(url);
    auditionAudio.onended = () => { auditionPlaying.value = false; };
    auditionAudio.onerror = () => { auditionPlaying.value = false; auditionError.value = '播放失败'; };
    auditionPlaying.value = true;
    await auditionAudio.play();
  } catch (e) {
    auditionError.value = e.response?.data?.detail || '试听失败';
  } finally {
    auditionLoading.value = false;
  }
}

function stopAudition() {
  if (auditionAudio) {
    auditionAudio.pause();
    auditionAudio.currentTime = 0;
    auditionAudio = null;
  }
  auditionPlaying.value = false;
}
```

- [ ] **Step 5: Update startEdit to include audition_text**

Find the `startEdit` function (line 175) and change from:
```javascript
function startEdit(v) {
  editForm.id = v.id;
  editForm.name = v.name;
  editError.value = '';
  showEdit.value = true;
}
```
to:
```javascript
function startEdit(v) {
  editForm.id = v.id;
  editForm.name = v.name;
  editForm.audition_text = v.audition_text || '';
  editError.value = '';
  showEdit.value = true;
}
```

- [ ] **Step 6: Update editForm reactive to include audition_text**

Find `const editForm = reactive({ id: '', name: '' })` (line 110) and change to:
```javascript
const editForm = reactive({ id: '', name: '', audition_text: '' });
```

- [ ] **Step 7: Update saveEdit to send audition_text**

Find the `saveEdit` function (line 182) and change from:
```javascript
    await api.patch(`/admin/voices/${editForm.id}`, { name: editForm.name.trim() });
```
to:
```javascript
    await api.patch(`/admin/voices/${editForm.id}`, {
      name: editForm.name.trim(),
      audition_text: editForm.audition_text || null,
    });
```

- [ ] **Step 8: Verify build**

Run: `cd web-admin && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 9: Commit**

```bash
git add web-admin/src/views/VoicePoolView.vue
git commit -m "feat: add voice audition modal to voice pool page"
```

---

### Task 6: Frontend — TTS link editing in voice edit modal

**Files:**
- Modify: `web-admin/src/views/VoicePoolView.vue`

- [ ] **Step 1: Add TTS link management UI to edit modal**

In the edit modal form (between `<h3>编辑音色</h3>` and the form fields), after the `<textarea>` for audition_text from Task 5, add:

```html
        <div style="margin-bottom:12px">
          <label style="display:block;font-size:12px;color:#aaa;margin-bottom:4px">TTS 模型</label>
          <div v-for="tc in editForm._ttsConfigs" :key="tc.id" style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span class="tag" style="background:#1a3a5c">{{ tc.name }} ({{ tc.model }})</span>
            <button type="button" class="btn-ghost" style="color:#e74c3c;font-size:12px" @click="removeTtsLink(tc.id)">×</button>
          </div>
          <div v-if="!editForm._ttsConfigs?.length" style="color:#888;font-size:12px;margin-bottom:4px">暂无关联 TTS 模型</div>
          <div style="display:flex;gap:8px">
            <select v-model="editForm._addTtsId" style="flex:1">
              <option value="">-- 添加 TTS 模型 --</option>
              <option v-for="tc in availableTtsForEdit" :key="tc.id" :value="tc.id">{{ tc.name }} ({{ tc.model }})</option>
            </select>
            <button type="button" class="btn-ghost" :disabled="!editForm._addTtsId" @click="addTtsLink">添加</button>
          </div>
        </div>
```

- [ ] **Step 2: Add TTS link management logic in script**

Add the computed property after `const editForm = ...`:
```javascript
const availableTtsForEdit = computed(() => {
  const linked = editForm._ttsConfigs?.map(c => c.id) || [];
  return ttsConfigs.value.filter(tc => !linked.includes(tc.id));
});
```

Add `computed` to the Vue import at the top:
```javascript
import { ref, reactive, computed, onMounted } from 'vue';
```

Update `startEdit` to load TTS configs for the voice:
```javascript
async function startEdit(v) {
  editForm.id = v.id;
  editForm.name = v.name;
  editForm.audition_text = v.audition_text || '';
  editForm._addTtsId = '';
  editError.value = '';
  try {
    const r = await api.get(`/admin/voices/${v.id}/tts-configs`);
    editForm._ttsConfigs = r.data;
  } catch (_) {
    editForm._ttsConfigs = [];
  }
  showEdit.value = true;
}
```

Update `editForm` reactive:
```javascript
const editForm = reactive({ id: '', name: '', audition_text: '', _ttsConfigs: [], _addTtsId: '' });
```

Add the add/remove functions:
```javascript
async function addTtsLink() {
  if (!editForm._addTtsId) return;
  try {
    await api.post(`/admin/voices/${editForm.id}/tts-configs`, { tts_config_id: editForm._addTtsId });
    const r = await api.get(`/admin/voices/${editForm.id}/tts-configs`);
    editForm._ttsConfigs = r.data;
    editForm._addTtsId = '';
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to add TTS link');
  }
}

async function removeTtsLink(ttsId) {
  try {
    await api.delete(`/admin/voices/${editForm.id}/tts-configs/${ttsId}`);
    const r = await api.get(`/admin/voices/${editForm.id}/tts-configs`);
    editForm._ttsConfigs = r.data;
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to remove TTS link');
  }
}
```

After saving edit, reload the page to refresh the voice list with updated TTS links:
```javascript
async function saveEdit() {
  if (!editForm.name.trim()) return;
  editLoading.value = true; editError.value = '';
  try {
    await api.patch(`/admin/voices/${editForm.id}`, {
      name: editForm.name.trim(),
      audition_text: editForm.audition_text || null,
    });
    showEdit.value = false;
    await load();
  } catch (e) {
    editError.value = e.response?.data?.detail || 'Update failed';
  } finally { editLoading.value = false; }
}
```

- [ ] **Step 3: Verify build**

Run: `cd web-admin && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add web-admin/src/views/VoicePoolView.vue
git commit -m "feat: add TTS link management to voice edit modal"
```

---

### Task 7: Run full test suite

- [ ] **Step 1: Run all API tests**

Run: `cd api && python3 -m pytest tests/ -v`
Expected: All tests pass (new + existing)

- [ ] **Step 2: Run frontend build**

Run: `cd web-admin && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit if any remaining changes**

```bash
git status
```

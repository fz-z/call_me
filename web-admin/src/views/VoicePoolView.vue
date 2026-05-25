<template>
  <div>
    <div class="page-header">
      <h2>声音库</h2>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" @click="showUpload = true">+ 上传音频生成音色</button>
        <button class="btn btn-primary" @click="showManual = true">+ 手动添加</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>名称</th><th>voice_id</th><th>类型</th><th>TTS 模型</th><th>使用此音色的 Agent</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="v in voices" :key="v.id">
          <td>{{ v.name }}</td>
          <td style="color:#4a90d9;font-size:11px;max-width:240px;word-break:break-all" :title="v.voice_id">{{ v.voice_id }}</td>
          <td><span class="tag" :style="v.type==='builtin'?'':'background:#3d2d00'">{{ v.type === 'builtin' ? '内置' : '克隆' }}</span></td>
          <td>
            <span v-for="tc in v._ttsConfigs" :key="tc.id" class="tag" style="background:#1a3a5c">{{ tc.name }}</span>
            <span v-if="!v._ttsConfigs?.length" style="color:#888;font-size:12px">-</span>
          </td>
          <td>
            <span v-for="a in v._agents" :key="a.id" class="tag">{{ a.alias }}</span>
            <span v-if="!v._agents?.length" style="color:#888;font-size:12px">暂无</span>
          </td>
          <td>
            <button class="btn-ghost" @click="openAudition(v)">试听</button>
            <button class="btn-ghost" @click="startEdit(v)">编辑</button>
            <button class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(v)">删除</button>
          </td>
        </tr>
        <tr v-if="!voices.length">
          <td colspan="6" style="color:#888;text-align:center;padding:24px">暂无声音</td>
        </tr>
      </tbody>
    </table>

    <!-- Upload Modal -->
    <div v-if="showUpload" class="modal-overlay" @click.self="showUpload = false">
      <form class="modal" @submit.prevent="upload" style="min-width:380px">
        <h3>上传音频生成音色</h3>
        <input v-model="voiceName" placeholder="音色名称" required />
        <select v-model="selectedTtsConfigId" style="margin-bottom:8px">
          <option value="">-- 选择 TTS 模型 --</option>
          <option v-for="tc in cloneableTtsConfigs" :key="tc.id" :value="tc.id">{{ tc.name }} ({{ tc.model }})</option>
        </select>
        <input type="file" accept="audio/*" @change="onFile" required style="margin-bottom:12px" />
        <p style="font-size:11px;color:#888;margin-bottom:12px">上传 30s~5min 的 wav/mp3/m4a 音频</p>
        <p v-if="uploadError" class="error">{{ uploadError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="showUpload = false">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="uploading">上传</button>
        </div>
      </form>
    </div>

    <!-- Manual Add Modal -->
    <div v-if="showManual" class="modal-overlay" @click.self="showManual = false">
      <form class="modal" @submit.prevent="manualAdd" style="min-width:400px">
        <h3>手动添加音色</h3>
        <input v-model="manualForm.name" placeholder="音色名称" required />
        <input v-model="manualForm.voice_id" placeholder="Voice ID (DashScope voice_id)" required />
        <select v-model="manualForm.type" required>
          <option value="cloned">克隆 (cloned)</option>
          <option value="builtin">内置 (builtin)</option>
        </select>
        <select v-model="manualForm.tts_config_id">
          <option value="">-- 选择 TTS 模型 (可选) --</option>
          <option v-for="tc in ttsConfigs" :key="tc.id" :value="tc.id">{{ tc.name }} ({{ tc.model }})</option>
        </select>
        <p v-if="manualError" class="error">{{ manualError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="showManual = false">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="manualLoading">添加</button>
        </div>
      </form>
    </div>

    <!-- Edit Modal -->
    <div v-if="showEdit" class="modal-overlay" @click.self="showEdit = false">
      <form class="modal" @submit.prevent="saveEdit" style="min-width:380px">
        <h3>编辑音色</h3>
        <input v-model="editForm.name" placeholder="音色名称" required />
        <textarea
          v-model="editForm.audition_text"
          rows="3"
          style="width:100%;box-sizing:border-box;resize:vertical;margin-bottom:12px"
          placeholder="试听文本 (可选)"
        ></textarea>
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
        <p v-if="editError" class="error">{{ editError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="showEdit = false">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="editLoading">保存</button>
        </div>
      </form>
    </div>

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
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue';
import api from '../api.js';

const voices = ref([]);
const ttsConfigs = ref([]);

const cloneableTtsConfigs = computed(() =>
  ttsConfigs.value.filter(tc => tc.supports_voice_clone !== false)
);
const showUpload = ref(false);
const voiceName = ref('');
const selectedTtsConfigId = ref('');
const audioFile = ref(null);
const uploading = ref(false);
const uploadError = ref('');

const showManual = ref(false);
const manualLoading = ref(false);
const manualError = ref('');
const manualForm = reactive({ name: '', voice_id: '', type: 'cloned', tts_config_id: '' });

const showEdit = ref(false);
const editLoading = ref(false);
const editError = ref('');
const editForm = reactive({ id: '', name: '', audition_text: '', _ttsConfigs: [], _addTtsId: '' });

const availableTtsForEdit = computed(() => {
  const linked = editForm._ttsConfigs?.map(c => c.id) || [];
  return ttsConfigs.value.filter(tc => !linked.includes(tc.id));
});

const showAudition = ref(false);
const auditionVoice = ref(null);
const auditionText = ref('');
const auditionLoading = ref(false);
const auditionPlaying = ref(false);
const auditionError = ref('');
let auditionAudio = null;

async function load() {
  const [r1, r2, r3] = await Promise.all([
    api.get('/admin/voices'),
    api.get('/admin/agents'),
    api.get('/admin/tts-configs'),
  ]);
  const allAgents = r2.data;
  const allTtsConfigs = r3.data;
  ttsConfigs.value = allTtsConfigs;

  // Enrich voices with agents and TTS configs
  const enriched = [];
  for (const v of r1.data) {
    try {
      const ttsRes = await api.get(`/admin/voices/${v.id}/tts-configs`);
      enriched.push({ ...v, _agents: allAgents.filter(a => a.voice_pool_id === v.id && !a.source_agent_id), _ttsConfigs: ttsRes.data });
    } catch (_) {
      enriched.push({ ...v, _agents: allAgents.filter(a => a.voice_pool_id === v.id && !a.source_agent_id), _ttsConfigs: [] });
    }
  }
  voices.value = enriched;
}

function onFile(e) { audioFile.value = e.target.files[0]; }

async function upload() {
  if (!voiceName.value.trim()) { uploadError.value = '请输入音色名称'; return; }
  if (!selectedTtsConfigId.value) { uploadError.value = '请选择 TTS 模型'; return; }
  if (!audioFile.value) { uploadError.value = '请选择音频文件'; return; }
  uploading.value = true; uploadError.value = '';
  try {
    const fd = new FormData();
    fd.append('name', voiceName.value.trim());
    fd.append('audio_file', audioFile.value);
    if (selectedTtsConfigId.value) fd.append('tts_config_id', selectedTtsConfigId.value);
    await api.post('/admin/voices', fd);
    showUpload.value = false;
    voiceName.value = '';
    audioFile.value = null;
    selectedTtsConfigId.value = '';
    await load();
  } catch (e) {
    uploadError.value = e.response?.data?.detail || 'Upload failed';
  } finally { uploading.value = false; }
}

async function manualAdd() {
  if (!manualForm.name.trim() || !manualForm.voice_id.trim()) return;
  manualLoading.value = true; manualError.value = '';
  try {
    await api.post('/admin/voices/manual', {
      name: manualForm.name.trim(),
      voice_id: manualForm.voice_id.trim(),
      type: manualForm.type,
      tts_config_id: manualForm.tts_config_id || null,
    });
    showManual.value = false;
    manualForm.name = '';
    manualForm.voice_id = '';
    manualForm.type = 'cloned';
    manualForm.tts_config_id = '';
    await load();
  } catch (e) {
    manualError.value = e.response?.data?.detail || 'Add failed';
  } finally { manualLoading.value = false; }
}

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

async function saveEdit() {
  if (!editForm.name.trim()) return;
  editLoading.value = true; editError.value = '';
  try {
    // Auto-add pending TTS config if selected
    if (editForm._addTtsId) {
      await api.post(`/admin/voices/${editForm.id}/tts-configs`, { tts_config_id: editForm._addTtsId });
      editForm._addTtsId = '';
    }
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

async function del(v) {
  if (!confirm(`Delete "${v.name}"?`)) return;
  try {
    await api.delete(`/admin/voices/${v.id}`);
    await load();
  } catch (e) {
    alert(e.response?.data?.detail || 'Delete failed');
  }
}

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

onMounted(load);
</script>

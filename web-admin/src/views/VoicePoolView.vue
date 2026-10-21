<template>
  <div>
    <div class="page-header">
      <h2>声音库</h2>
      <div class="header-actions">
        <button class="btn-ghost" @click="openRealtimeUpload">+ 上传音频创建端到端音色</button>
        <button class="btn btn-primary" @click="showUpload = true">+ 上传音频生成经典音色</button>
      </div>
    </div>
    <p class="hint">声音库只展示内部音色池名称；提供商音色 ID 仅由服务端运行时使用。</p>
    <p v-if="pageError" class="error">{{ pageError }} <button class="btn-ghost" @click="load">重试</button></p>
    <table>
      <thead><tr>
        <th>名称</th><th>类型</th><th>经典 TTS 绑定</th><th>端到端实时绑定</th><th>使用此音色的 Agent</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="voice in voices" :key="voice.id">
          <td><router-link class="voice-link" :to="`/voices/${voice.id}`">{{ voice.name }}</router-link></td>
          <td><span class="tag" :style="voice.type === 'builtin' ? '' : 'background:#3d2d00'">{{ voice.type === 'builtin' ? '内置' : '克隆' }}</span></td>
          <td>
            <span v-for="config in voice._ttsConfigs" :key="config.id" class="tag tag-classic">{{ config.name }}</span>
            <span v-if="!voice._ttsConfigs.length" class="muted">未绑定</span>
          </td>
          <td>
            <span v-for="binding in voice._runtimeBindings" :key="binding.id" class="tag tag-realtime">{{ binding.runtime_config_name }}</span>
            <span v-if="!voice._runtimeBindings.length" class="muted">未克隆</span>
          </td>
          <td>
            <span v-for="agent in voice._agents" :key="agent.id" class="tag">{{ agent.alias }}</span>
            <span v-if="!voice._agents.length" class="muted">暂无</span>
          </td>
          <td>
            <router-link class="btn-ghost detail-link" :to="`/voices/${voice.id}`">查看详情</router-link>
            <button class="btn-ghost danger" @click="del(voice)">删除</button>
          </td>
        </tr>
        <tr v-if="!voices.length"><td colspan="6" class="empty">暂无声音</td></tr>
      </tbody>
    </table>

    <div v-if="showUpload" class="modal-overlay" @click.self="showUpload = false">
      <form class="modal" @submit.prevent="upload" style="min-width:390px">
        <h3>生成经典 Pipeline 音色</h3>
        <input v-model="voiceName" placeholder="音色名称" required />
        <select v-model="selectedTtsConfigId" required>
          <option value="">-- 选择 TTS 模型 --</option>
          <option v-for="config in cloneableTtsConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option>
        </select>
        <input type="file" accept="audio/*" @change="(event) => uploadAudioFile = event.target.files[0]" required />
        <p class="hint">上传 30 秒至 5 分钟的 wav、mp3 或 m4a 音频。端到端实时模型需要在创建后单独克隆绑定。</p>
        <p v-if="uploadError" class="error">{{ uploadError }}</p>
        <div class="modal-actions"><button type="button" class="btn-ghost" @click="showUpload = false">取消</button><button class="btn btn-primary" :disabled="uploading">{{ uploading ? '上传中…' : '上传' }}</button></div>
      </form>
    </div>

    <div v-if="showRealtimeUpload" class="modal-overlay" @click.self="showRealtimeUpload = false">
      <form class="modal" @submit.prevent="createRealtimeVoice" style="min-width:440px">
        <h3>创建端到端实时音色</h3>
        <input v-model="realtimeVoiceForm.name" placeholder="音色名称" required />
        <select v-model="realtimeVoiceForm.configId" required>
          <option value="">-- 选择实时模型 --</option>
          <option v-for="config in cloneableRealtimeConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option>
        </select>
        <input type="file" accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4" @change="(event) => onRealtimeAudioSelected(event, realtimeVoiceForm, realtimeVoiceError)" required />
        <label class="consent"><input v-model="realtimeVoiceForm.authorizationConfirmed" type="checkbox" /> 我确认有权使用这段参考音频进行音色复刻。</label>
        <p class="hint">支持 WAV、MP3、M4A，最大 10 MB；建议 10～20 秒、最长 60 秒，并包含至少 5 秒清晰人声。创建后只绑定所选实时模型，不会创建或绑定 TTS。</p>
        <p v-if="!cloneableRealtimeConfigs.length" class="error">请先在“实时模型”中创建并启用支持音色复刻的配置。</p>
        <p v-if="realtimeVoiceError" class="error">{{ realtimeVoiceError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="showRealtimeUpload = false">取消</button>
          <button class="btn btn-primary" :disabled="realtimeVoiceSaving || realtimeAudioValidating || !cloneableRealtimeConfigs.length || !realtimeVoiceForm.audioFile || !realtimeVoiceForm.authorizationConfirmed">{{ realtimeVoiceSaving ? '创建中…' : realtimeAudioValidating ? '检查音频时长…' : '创建音色' }}</button>
        </div>
      </form>
    </div>

  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import api from '../api.js';
import { getRealtimeAudioDurationError } from '../utils/audioDuration.js';
import { realtimeBindings } from '../utils/voiceManagement.js';

const voices = ref([]); const ttsConfigs = ref([]); const realtimeConfigs = ref([]);
const pageError = ref('');
const showUpload = ref(false); const voiceName = ref(''); const selectedTtsConfigId = ref(''); const uploadAudioFile = ref(null); const uploading = ref(false); const uploadError = ref('');
const showRealtimeUpload = ref(false); const realtimeVoiceSaving = ref(false); const realtimeVoiceError = ref('');
const realtimeAudioValidating = ref(false);
const realtimeVoiceForm = reactive({ name: '', configId: '', audioFile: null, authorizationConfirmed: false });

const cloneableTtsConfigs = computed(() => ttsConfigs.value.filter((config) => config.supports_voice_clone !== false));
const cloneableRealtimeConfigs = computed(() => realtimeConfigs.value.filter((config) => supportsVoiceClone(config)));

function supportsVoiceClone(config) { try { return JSON.parse(config.capabilities_json || '{}').voice_clone === true; } catch (_) { return false; } }

async function onRealtimeAudioSelected(event, form, errorRef, fileField = 'audioFile') {
  const file = event.target.files?.[0] || null;
  form[fileField] = null;
  errorRef.value = '';
  if (!file) return;

  const audioUrl = URL.createObjectURL(file);
  const audio = new Audio();
  audio.preload = 'metadata';
  realtimeAudioValidating.value = true;
  try {
    const duration = await new Promise((resolve, reject) => {
      audio.onloadedmetadata = () => resolve(audio.duration);
      audio.onerror = () => reject(new Error('无法读取音频时长'));
      audio.src = audioUrl;
    });
    const durationError = getRealtimeAudioDurationError(duration);
    if (durationError) {
      errorRef.value = durationError;
      event.target.value = '';
      return;
    }
    form[fileField] = file;
  } catch (_) {
    errorRef.value = getRealtimeAudioDurationError(Number.NaN);
    event.target.value = '';
  } finally {
    audio.removeAttribute('src');
    audio.load();
    URL.revokeObjectURL(audioUrl);
    realtimeAudioValidating.value = false;
  }
}

async function load() {
  pageError.value = '';
  try {
    const [voiceResult, agentResult, ttsResult, realtimeResult] = await Promise.all([api.get('/admin/voices'), api.get('/admin/agents'), api.get('/admin/tts-configs'), api.get('/admin/realtime-configs')]);
    ttsConfigs.value = ttsResult.data; realtimeConfigs.value = realtimeResult.data;
    voices.value = await Promise.all(voiceResult.data.map(async (voice) => {
      const [tts, runtime] = await Promise.all([api.get(`/admin/voices/${voice.id}/tts-configs`), api.get(`/admin/voices/${voice.id}/runtime-bindings`)]);
      return { ...voice, _agents: agentResult.data.filter((agent) => agent.voice_pool_id === voice.id && !agent.source_agent_id), _ttsConfigs: tts.data, _runtimeBindings: realtimeBindings(runtime.data) };
    }));
  } catch (error) {
    pageError.value = error.response?.data?.detail || '声音库加载失败，请重试。';
  }
}

async function upload() { if (!voiceName.value.trim() || !selectedTtsConfigId.value || !uploadAudioFile.value) return; uploading.value = true; uploadError.value = ''; try { const data = new FormData(); data.append('name', voiceName.value.trim()); data.append('tts_config_id', selectedTtsConfigId.value); data.append('audio_file', uploadAudioFile.value); await api.post('/admin/voices', data); showUpload.value = false; voiceName.value = ''; selectedTtsConfigId.value = ''; uploadAudioFile.value = null; await load(); } catch (error) { uploadError.value = error.response?.data?.detail || '上传失败'; } finally { uploading.value = false; } }

function openRealtimeUpload() { realtimeVoiceForm.name = ''; realtimeVoiceForm.configId = cloneableRealtimeConfigs.value[0]?.id || ''; realtimeVoiceForm.audioFile = null; realtimeVoiceForm.authorizationConfirmed = false; realtimeVoiceError.value = ''; showRealtimeUpload.value = true; }
async function createRealtimeVoice() {
  if (!realtimeVoiceForm.name.trim() || !realtimeVoiceForm.configId || !realtimeVoiceForm.audioFile || !realtimeVoiceForm.authorizationConfirmed) return;
  realtimeVoiceSaving.value = true; realtimeVoiceError.value = '';
  try {
    const data = new FormData(); data.append('name', realtimeVoiceForm.name.trim()); data.append('realtime_config_id', realtimeVoiceForm.configId); data.append('audio_file', realtimeVoiceForm.audioFile); data.append('authorization_confirmed', String(realtimeVoiceForm.authorizationConfirmed));
    await api.post('/admin/voices/realtime', data);
    showRealtimeUpload.value = false; await load();
  } catch (error) {
    realtimeVoiceError.value = error.response?.data?.detail || '端到端音色创建失败';
  } finally { realtimeVoiceSaving.value = false; }
}

async function del(voice) { if (!confirm(`删除“${voice.name}”吗？`)) return; try { await api.delete(`/admin/voices/${voice.id}`); await load(); } catch (error) { alert(error.response?.data?.detail || '删除失败'); } }
onMounted(load);
</script>

<style scoped>
.hint,.muted { color:#888; font-size:12px; }.hint { margin:0 0 12px; line-height:1.5; }.empty { color:#888; text-align:center; padding:24px; }.danger { color:#e74c3c; margin-left:4px; }.tag-classic { background:#1a3a5c; }.tag-realtime { background:#3d2d00; }.consent { display:block; color:#bbb; font-size:12px; margin:10px 0; }.consent input { width:auto; margin:0 6px 0 0; } select,input[type=file] { width:100%; box-sizing:border-box; margin-bottom:10px; }.header-actions { display:flex; gap:8px; flex-wrap:wrap; }.voice-link { color:#8bbcff; text-decoration:none; }.voice-link:hover { text-decoration:underline; }.detail-link { display:inline-block; text-decoration:none; margin-right:4px; }
</style>

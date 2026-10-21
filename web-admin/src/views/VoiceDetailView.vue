<template>
  <div class="voice-detail">
    <router-link to="/voices" class="back-link">← 返回声音库</router-link>

    <div v-if="loading" class="state-card">正在加载音色…</div>
    <div v-else-if="notFound" class="state-card">
      <h2>找不到这个音色</h2>
      <p class="muted">它可能已被删除。请返回声音库选择其他音色。</p>
    </div>
    <div v-else-if="pageError" class="state-card">
      <h2>加载失败</h2>
      <p class="error">{{ pageError }}</p>
      <button class="btn btn-primary" @click="load">重试</button>
    </div>

    <template v-else-if="voice">
      <header class="detail-header">
        <div>
          <p class="eyebrow">音色详情</p>
          <h2>{{ voice.name }} <span class="tag">{{ voice.type === 'builtin' ? '内置' : '克隆' }}</span></h2>
          <p class="muted">{{ voiceAgents.length ? `正在被 ${voiceAgents.length} 个 Agent 使用` : '暂无 Agent 使用此音色' }}</p>
        </div>
        <router-link to="/agents" class="btn-ghost action-link">查看 Agent</router-link>
      </header>

      <div class="section-grid">
        <section class="detail-card" aria-labelledby="realtime-title">
          <div class="section-heading">
            <div>
              <p class="eyebrow">端到端</p>
              <h3 id="realtime-title">实时模型音色</h3>
            </div>
            <button v-if="unusedRealtimeConfigs.length && !cloneForm.open && !realtimeRefreshFailed" class="btn btn-primary" @click="openNewClone">+ 复刻到其他模型</button>
          </div>
          <p class="section-help">每个实时模型配置单独复刻一次。已复刻的音色可在该配置的多个 Agent 和后续通话中重复使用，无需再次上传。</p>
          <p class="section-help">想听端到端效果，请在 <router-link to="/agents">Agent 管理</router-link> 选择使用此音色的实时 Agent 发起通话。</p>

          <div v-if="realtimeRefreshFailed" class="empty-state">复刻请求已成功，但绑定列表暂时无法刷新。请先刷新列表确认结果，不要重复上传。</div>
          <div v-else-if="realtimeRows.length" class="binding-list">
            <div v-for="binding in realtimeRows" :key="binding.id" class="binding-card">
              <div>
                <strong>{{ binding.runtime_config_name }}</strong>
                <div class="muted">{{ binding.runtime_config_model }}</div>
                <div class="reuse-note">✓ 已复刻，可重复使用</div>
              </div>
              <button class="btn-ghost subtle-action" @click="openReplaceClone(binding)">重新复刻</button>
            </div>
          </div>
          <div v-else class="empty-state">尚未绑定实时模型。选择一个支持音色复刻的实时配置并上传参考音频即可创建。</div>

          <p v-if="!unusedRealtimeConfigs.length && !cloneForm.open && !realtimeRefreshFailed" class="section-help">
            {{ realtimeConfigs.length ? '当前没有其他可新增的实时模型配置。' : '尚无实时模型配置。' }}
            <router-link to="/realtime-configs">管理实时模型 →</router-link>
          </p>
          <p v-if="realtimeNotice" class="success-note">{{ realtimeNotice }}</p>
          <p v-if="realtimeError && !cloneForm.open" class="error">{{ realtimeError }} <button v-if="realtimeRefreshFailed" class="btn-ghost" @click="refreshRealtimeBindings">仅刷新列表</button></p>

          <form v-if="cloneForm.open" class="action-panel" @submit.prevent="submitClone">
            <h4>{{ cloneForm.mode === 'replace' ? '重新复刻此模型音色' : '复刻到其他实时模型' }}</h4>
            <p v-if="cloneForm.mode === 'replace'" class="warning">目标模型：{{ cloneTargetName }}。提交后将替换当前绑定，使用该绑定的 Agent 后续通话会使用新音色。</p>
            <label v-else for="clone-config">1. 选择实时模型</label>
            <select v-if="cloneForm.mode === 'new'" id="clone-config" v-model="cloneForm.configId" required>
              <option value="">请选择实时模型</option>
              <option v-for="config in unusedRealtimeConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option>
            </select>
            <label for="clone-file">{{ cloneForm.mode === 'new' ? '2.' : '1.' }} 上传参考音频</label>
            <input :key="cloneInputKey" id="clone-file" type="file" accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4" @change="onCloneAudioSelected" />
            <p class="field-hint">WAV、MP3 或 M4A；不超过 10 MB、60 秒。建议 10～20 秒清晰人声。</p>
            <label class="consent"><input v-model="cloneForm.authorized" type="checkbox" /> {{ cloneForm.mode === 'new' ? '3.' : '2.' }} 我确认有权使用这段参考音频进行音色复刻。</label>
            <p v-if="realtimeError" class="error">{{ realtimeError }}</p>
            <div class="form-actions">
              <button type="button" class="btn-ghost" :disabled="cloneSaving" @click="closeClone">取消</button>
              <button class="btn btn-primary" :disabled="cloneSaving || audioValidating || !cloneForm.configId || !cloneForm.audioFile || !cloneForm.authorized">{{ cloneSaving ? '复刻中…' : audioValidating ? '检查音频时长…' : cloneForm.mode === 'replace' ? '确认重新复刻' : '开始复刻' }}</button>
            </div>
          </form>
        </section>

        <section class="detail-card" aria-labelledby="tts-title">
          <div class="section-heading">
            <div>
              <p class="eyebrow">经典 Pipeline</p>
              <h3 id="tts-title">TTS 模型绑定</h3>
            </div>
            <button class="btn-ghost" :disabled="voice.has_classic_voice === false || !ttsLinks.length" @click="openAudition">试听</button>
          </div>
          <p class="section-help">这里管理经典 TTS 关联，与端到端实时音色分别生效。</p>
          <p v-if="voice.has_classic_voice === false" class="warning classic-warning">此档案只有端到端音色。仅添加 TTS 模型不会生成经典音色，因此不能试听或用于经典 Agent。请返回声音库上传音频创建经典音色。</p>
          <div v-if="ttsLinks.length" class="binding-list">
            <div v-for="config in ttsLinks" :key="config.id" class="binding-card">
              <div><strong>{{ config.name }}</strong><div class="muted">{{ config.model }}</div></div>
              <button class="btn-ghost danger" :disabled="ttsBusy" @click="removeTtsLink(config)">移除</button>
            </div>
          </div>
          <div v-else class="empty-state">尚未关联经典 TTS 模型。端到端音色仍可独立使用。</div>
          <div v-if="availableTtsConfigs.length" class="add-row">
            <select v-model="addTtsId" aria-label="要添加的 TTS 模型">
              <option value="">选择要添加的 TTS 模型</option>
              <option v-for="config in availableTtsConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option>
            </select>
            <button class="btn-ghost" :disabled="ttsBusy || !addTtsId" @click="addTtsLink">添加</button>
          </div>
          <p v-if="ttsError" class="error">{{ ttsError }}</p>
        </section>
      </div>

      <section class="detail-card info-card" aria-labelledby="info-title">
        <div class="section-heading">
          <div><p class="eyebrow">音色档案</p><h3 id="info-title">基本信息</h3></div>
          <button v-if="!editingInfo" class="btn-ghost" @click="startInfoEdit">编辑</button>
        </div>
        <div v-if="!editingInfo" class="info-summary">
          <div><span class="muted">名称</span><strong>{{ voice.name }}</strong></div>
          <div><span class="muted">经典 TTS 默认试听文本</span><strong>{{ voice.audition_text || '未设置' }}</strong></div>
        </div>
        <form v-else class="action-panel" @submit.prevent="saveInfo">
          <label for="voice-name">音色名称</label>
          <input id="voice-name" v-model="infoForm.name" required />
          <label for="audition-default">经典 TTS 默认试听文本（可选）</label>
          <textarea id="audition-default" v-model="infoForm.auditionText" rows="3"></textarea>
          <p v-if="infoError" class="error">{{ infoError }}</p>
          <div class="form-actions"><button type="button" class="btn-ghost" :disabled="infoSaving" @click="editingInfo = false">取消</button><button class="btn btn-primary" :disabled="infoSaving || !infoForm.name.trim()">{{ infoSaving ? '保存中…' : '保存基本信息' }}</button></div>
        </form>
      </section>
    </template>

    <div v-if="auditionOpen" class="modal-overlay" @click.self="closeAudition">
      <form class="modal audition-modal" @submit.prevent="startAudition">
        <h3>经典 TTS 试听 · {{ voice?.name }}</h3>
        <label for="audition-config">TTS 模型</label>
        <select id="audition-config" v-model="auditionConfigId" required>
          <option v-for="config in ttsLinks" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option>
        </select>
        <label for="audition-text">试听文本</label>
        <textarea id="audition-text" v-model="auditionText" rows="4" required></textarea>
        <p class="field-hint">端到端音色请通过使用它的 Agent 发起实时通话试听。</p>
        <p v-if="auditionError" class="error">{{ auditionError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="closeAudition">关闭</button>
          <button v-if="auditionPlaying" type="button" class="btn-ghost" @click="stopAudition">停止</button>
          <button class="btn btn-primary" :disabled="auditionLoading || !auditionConfigId || !auditionText.trim()">{{ auditionLoading ? '合成中…' : '试听' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import api from '../api.js';
import { getRealtimeAudioDurationError } from '../utils/audioDuration.js';
import { availableRealtimeConfigs, createGenerationGuard, getRealtimeAudioFileError, realtimeBindings, submitAndRefreshRealtimeBinding } from '../utils/voiceManagement.js';

const route = useRoute();
const loading = ref(true); const notFound = ref(false); const pageError = ref('');
const voice = ref(null); const agents = ref([]); const ttsLinks = ref([]); const runtimeRows = ref([]);
const ttsConfigs = ref([]); const realtimeConfigs = ref([]);
const realtimeRows = computed(() => realtimeBindings(runtimeRows.value));
const unusedRealtimeConfigs = computed(() => availableRealtimeConfigs(realtimeConfigs.value, runtimeRows.value));
const availableTtsConfigs = computed(() => voice.value?.has_classic_voice !== false ? ttsConfigs.value.filter((config) => !ttsLinks.value.some((linked) => linked.id === config.id)) : []);
const voiceAgents = computed(() => agents.value.filter((agent) => agent.voice_pool_id === voice.value?.id && !agent.source_agent_id));

const cloneForm = reactive({ open: false, mode: 'new', configId: '', audioFile: null, authorized: false });
const cloneSaving = ref(false); const audioValidating = ref(false); const cloneInputKey = ref(0);
const audioSelectionGuard = createGenerationGuard();
const loadGuard = createGenerationGuard();
const auditionGuard = createGenerationGuard();
const realtimeError = ref(''); const realtimeNotice = ref(''); const realtimeRefreshFailed = ref(false);
const cloneTargetName = computed(() => realtimeConfigs.value.find((config) => config.id === cloneForm.configId)?.name || realtimeRows.value.find((row) => row.runtime_config_id === cloneForm.configId)?.runtime_config_name || '未知模型');

const addTtsId = ref(''); const ttsBusy = ref(false); const ttsError = ref('');
const editingInfo = ref(false); const infoForm = reactive({ name: '', auditionText: '' });
const infoSaving = ref(false); const infoError = ref('');
const auditionOpen = ref(false); const auditionConfigId = ref(''); const auditionText = ref('');
const auditionLoading = ref(false); const auditionPlaying = ref(false); const auditionError = ref('');
let auditionAudio = null; let auditionUrl = null;

async function load() {
  const requestedId = route.params.id;
  const generation = loadGuard.next();
  loading.value = true; notFound.value = false; pageError.value = '';
  try {
    const voiceResult = await api.get('/admin/voices');
    if (!loadGuard.isCurrent(generation)) return;
    const selected = voiceResult.data.find((item) => item.id === requestedId);
    if (!selected) { voice.value = null; notFound.value = true; return; }
    const [tts, runtime, agentResult, ttsConfigResult, realtimeConfigResult] = await Promise.all([
      api.get(`/admin/voices/${selected.id}/tts-configs`),
      api.get(`/admin/voices/${selected.id}/runtime-bindings`),
      api.get('/admin/agents'), api.get('/admin/tts-configs'), api.get('/admin/realtime-configs'),
    ]);
    if (!loadGuard.isCurrent(generation)) return;
    voice.value = selected; ttsLinks.value = tts.data; runtimeRows.value = runtime.data;
    realtimeRefreshFailed.value = false; realtimeError.value = '';
    agents.value = agentResult.data; ttsConfigs.value = ttsConfigResult.data; realtimeConfigs.value = realtimeConfigResult.data;
  } catch (error) {
    if (!loadGuard.isCurrent(generation)) return;
    voice.value = null;
    pageError.value = error.response?.data?.detail || '音色数据加载失败，请重试。';
  } finally { if (loadGuard.isCurrent(generation)) loading.value = false; }
}

function activeVoice(id, generation) {
  return route.params.id === id && loadGuard.isCurrent(generation);
}

function openNewClone() {
  audioSelectionGuard.invalidate(); audioValidating.value = false;
  cloneForm.mode = 'new'; cloneForm.configId = ''; cloneForm.audioFile = null; cloneForm.authorized = false;
  realtimeError.value = ''; realtimeNotice.value = ''; cloneInputKey.value += 1; cloneForm.open = true;
}
function openReplaceClone(binding) {
  audioSelectionGuard.invalidate(); audioValidating.value = false;
  cloneForm.mode = 'replace'; cloneForm.configId = binding.runtime_config_id; cloneForm.audioFile = null; cloneForm.authorized = false;
  realtimeError.value = ''; realtimeNotice.value = ''; cloneInputKey.value += 1; cloneForm.open = true;
}
function closeClone() { audioSelectionGuard.invalidate(); audioValidating.value = false; cloneForm.open = false; cloneForm.audioFile = null; cloneForm.authorized = false; realtimeError.value = ''; }

async function onCloneAudioSelected(event) {
  const selectionId = audioSelectionGuard.next();
  const file = event.target.files?.[0] || null;
  cloneForm.audioFile = null; realtimeError.value = '';
  if (!file) return;
  const fileError = getRealtimeAudioFileError(file);
  if (fileError) { realtimeError.value = fileError; event.target.value = ''; return; }
  const audioUrl = URL.createObjectURL(file);
  const audio = new Audio(); audio.preload = 'metadata'; audioValidating.value = true;
  try {
    const duration = await new Promise((resolve, reject) => {
      audio.onloadedmetadata = () => resolve(audio.duration);
      audio.onerror = () => reject(new Error('无法读取音频时长'));
      audio.src = audioUrl;
    });
    if (!audioSelectionGuard.isCurrent(selectionId)) return;
    const durationError = getRealtimeAudioDurationError(duration);
    if (durationError) { realtimeError.value = durationError; event.target.value = ''; return; }
    cloneForm.audioFile = file;
  } catch (_) {
    if (audioSelectionGuard.isCurrent(selectionId)) {
      realtimeError.value = getRealtimeAudioDurationError(Number.NaN);
      event.target.value = '';
    }
  } finally {
    audio.removeAttribute('src'); audio.load(); URL.revokeObjectURL(audioUrl);
    if (audioSelectionGuard.isCurrent(selectionId)) audioValidating.value = false;
  }
}

async function submitClone() {
  if (cloneSaving.value || !cloneForm.configId || !cloneForm.audioFile || !cloneForm.authorized) return;
  if (cloneForm.mode === 'new' && !unusedRealtimeConfigs.value.some((config) => config.id === cloneForm.configId)) {
    realtimeError.value = '此实时模型已有绑定或不支持音色复刻，请重新选择。'; return;
  }
  if (cloneForm.mode === 'replace' && !realtimeRows.value.some((row) => row.runtime_config_id === cloneForm.configId)) {
    realtimeError.value = '找不到要替换的实时绑定，请刷新页面。'; return;
  }
  if (cloneForm.mode === 'replace' && !confirm('重新复刻会替换此实时模型当前绑定，使用该绑定的 Agent 后续通话会使用新音色。确定继续吗？')) return;
  const voiceId = voice.value.id; const generation = loadGuard.current();
  const mode = cloneForm.mode;
  cloneSaving.value = true; realtimeError.value = '';
  try {
    const data = new FormData(); data.append('realtime_config_id', cloneForm.configId);
    data.append('audio_file', cloneForm.audioFile); data.append('authorization_confirmed', 'true');
    const result = await submitAndRefreshRealtimeBinding(
      () => api.post(`/admin/voices/${voiceId}/realtime-bindings`, data),
      async () => (await api.get(`/admin/voices/${voiceId}/runtime-bindings`)).data,
    );
    if (!activeVoice(voiceId, generation)) return;
    realtimeNotice.value = mode === 'replace' ? '已更新该实时模型音色。' : '实时模型音色已复刻，可直接用于 Agent。';
    closeClone();
    if (result.refreshError) {
      realtimeRefreshFailed.value = true;
      realtimeError.value = '绑定列表刷新失败。';
    } else {
      runtimeRows.value = result.bindings;
      realtimeRefreshFailed.value = false;
    }
  } catch (error) { if (activeVoice(voiceId, generation)) realtimeError.value = error.response?.data?.detail || '音色复刻失败，请重试。'; }
  finally { if (activeVoice(voiceId, generation)) cloneSaving.value = false; }
}

async function refreshRealtimeBindings() {
  const voiceId = voice.value.id; const generation = loadGuard.current();
  try {
    const result = await api.get(`/admin/voices/${voiceId}/runtime-bindings`);
    if (!activeVoice(voiceId, generation)) return;
    runtimeRows.value = result.data;
    realtimeRefreshFailed.value = false; realtimeError.value = '';
  } catch (error) { if (activeVoice(voiceId, generation)) realtimeError.value = error.response?.data?.detail || '绑定列表仍无法刷新，请稍后再试。'; }
}

async function addTtsLink() {
  if (!addTtsId.value || ttsBusy.value) return;
  if (voice.value.has_classic_voice === false) { ttsError.value = '此档案还没有经典 TTS 音色，不能只添加模型关联。'; return; }
  const voiceId = voice.value.id; const generation = loadGuard.current();
  const configId = addTtsId.value;
  ttsBusy.value = true; ttsError.value = '';
  try {
    await api.post(`/admin/voices/${voiceId}/tts-configs`, { tts_config_id: configId });
    const result = await api.get(`/admin/voices/${voiceId}/tts-configs`);
    if (!activeVoice(voiceId, generation)) return;
    ttsLinks.value = result.data;
    addTtsId.value = '';
  } catch (error) { if (activeVoice(voiceId, generation)) ttsError.value = error.response?.data?.detail || '添加 TTS 绑定失败。'; }
  finally { if (activeVoice(voiceId, generation)) ttsBusy.value = false; }
}
async function removeTtsLink(config) {
  if (ttsBusy.value || !confirm(`确定移除“${config.name}”的经典 TTS 关联吗？`)) return;
  const voiceId = voice.value.id; const generation = loadGuard.current();
  ttsBusy.value = true; ttsError.value = '';
  try {
    await api.delete(`/admin/voices/${voiceId}/tts-configs/${config.id}`);
    const result = await api.get(`/admin/voices/${voiceId}/tts-configs`);
    if (!activeVoice(voiceId, generation)) return;
    ttsLinks.value = result.data;
  } catch (error) { if (activeVoice(voiceId, generation)) ttsError.value = error.response?.data?.detail || '移除 TTS 绑定失败。'; }
  finally { if (activeVoice(voiceId, generation)) ttsBusy.value = false; }
}

function startInfoEdit() { infoForm.name = voice.value.name; infoForm.auditionText = voice.value.audition_text || ''; infoError.value = ''; editingInfo.value = true; }
async function saveInfo() {
  if (!infoForm.name.trim() || infoSaving.value) return;
  const voiceId = voice.value.id; const generation = loadGuard.current();
  const update = { name: infoForm.name.trim(), audition_text: infoForm.auditionText };
  infoSaving.value = true; infoError.value = '';
  try {
    const result = await api.patch(`/admin/voices/${voiceId}`, update);
    if (!activeVoice(voiceId, generation)) return;
    voice.value = result.data;
    editingInfo.value = false;
  } catch (error) { if (activeVoice(voiceId, generation)) infoError.value = error.response?.data?.detail || '保存基本信息失败。'; }
  finally { if (activeVoice(voiceId, generation)) infoSaving.value = false; }
}

function openAudition() {
  if (voice.value.has_classic_voice === false || !ttsLinks.value.length) return;
  auditionConfigId.value = ttsLinks.value[0]?.id || '';
  auditionText.value = voice.value.audition_text || '你好，这是一段语音试听文本，用于测试音色效果。';
  auditionError.value = ''; auditionOpen.value = true;
}
function stopAudition() {
  auditionGuard.invalidate();
  if (auditionAudio) { auditionAudio.pause(); auditionAudio.removeAttribute('src'); auditionAudio.load(); auditionAudio = null; }
  if (auditionUrl) { URL.revokeObjectURL(auditionUrl); auditionUrl = null; }
  auditionPlaying.value = false; auditionLoading.value = false;
}
function closeAudition() { stopAudition(); auditionOpen.value = false; }
async function startAudition() {
  if (!auditionConfigId.value || !auditionText.value.trim() || auditionLoading.value) return;
  const voiceId = voice.value.id; const loadGeneration = loadGuard.current();
  const payload = { text: auditionText.value.trim(), tts_config_id: auditionConfigId.value };
  stopAudition();
  const auditionGeneration = auditionGuard.next();
  auditionLoading.value = true; auditionError.value = '';
  try {
    const response = await api.post(`/admin/voices/${voiceId}/audition`, payload);
    if (!activeVoice(voiceId, loadGeneration) || !auditionGuard.isCurrent(auditionGeneration)) return;
    const bytes = Uint8Array.from(atob(response.data.audio_base64), (char) => char.charCodeAt(0));
    auditionUrl = URL.createObjectURL(new Blob([bytes], { type: response.data.mime_type }));
    auditionAudio = new Audio(auditionUrl);
    auditionAudio.onended = () => { if (auditionGuard.isCurrent(auditionGeneration)) stopAudition(); };
    auditionAudio.onerror = () => { if (auditionGuard.isCurrent(auditionGeneration)) { stopAudition(); auditionError.value = '音频播放失败。'; } };
    await auditionAudio.play();
    if (activeVoice(voiceId, loadGeneration) && auditionGuard.isCurrent(auditionGeneration)) auditionPlaying.value = true;
  } catch (error) {
    if (activeVoice(voiceId, loadGeneration) && auditionGuard.isCurrent(auditionGeneration)) {
      stopAudition(); auditionError.value = error.response?.data?.detail || '经典 TTS 试听失败。';
    }
  } finally {
    if (activeVoice(voiceId, loadGeneration) && auditionGuard.isCurrent(auditionGeneration)) auditionLoading.value = false;
  }
}

watch(() => route.params.id, (id, previousId) => {
  if (id !== previousId) {
    closeClone(); closeAudition();
    voice.value = null; ttsLinks.value = []; runtimeRows.value = [];
    editingInfo.value = false; infoError.value = ''; infoSaving.value = false;
    addTtsId.value = ''; ttsError.value = ''; ttsBusy.value = false;
    cloneSaving.value = false; realtimeNotice.value = ''; realtimeRefreshFailed.value = false;
    auditionLoading.value = false; auditionError.value = '';
  }
  load();
}, { immediate: true });
onBeforeUnmount(() => { loadGuard.invalidate(); closeClone(); closeAudition(); });
</script>

<style scoped>
.voice-detail { max-width: 1160px; margin: 0 auto; }.muted,.section-help,.field-hint { color:#94a3b8; font-size:13px; line-height:1.6; }.detail-header { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; margin:5px 0 24px; }.detail-header h2 { font-size:26px; margin:4px 0 6px; }.detail-header .tag { vertical-align:middle; font-weight:400; }.eyebrow { color:#73abef; font-size:11px; letter-spacing:.08em; margin-bottom:4px; }.action-link { text-decoration:none; white-space:nowrap; }.section-grid { display:grid; grid-template-columns:1fr 1fr; gap:18px; align-items:start; }.detail-card,.state-card { background:#1a1a2e; border:1px solid #30354d; border-radius:10px; padding:20px; }.state-card { margin-top:18px; }.state-card h2 { margin-bottom:8px; }.section-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }.section-heading h3 { font-size:18px; }.section-help { margin:0 0 16px; }.section-help a { color:#8bbcff; }.binding-list { display:grid; gap:10px; margin:15px 0; }.binding-card { border:1px solid #374151; border-radius:8px; padding:13px; display:flex; justify-content:space-between; align-items:center; gap:12px; background:#111827; }.binding-card strong { font-size:14px; }.binding-card .muted { margin-top:4px; word-break:break-word; }.reuse-note { color:#86efac; font-size:12px; margin-top:7px; }.subtle-action { white-space:nowrap; }.empty-state { color:#94a3b8; border:1px dashed #475569; border-radius:8px; padding:20px; font-size:13px; line-height:1.6; margin:15px 0; }.action-panel { background:#111827; border:1px solid #374151; border-radius:8px; padding:16px; margin-top:16px; }.action-panel h4 { margin-bottom:12px; }.action-panel label:not(.consent),.audition-modal label { display:block; color:#cbd5e1; font-size:13px; margin:12px 0 6px; }.action-panel select,.action-panel input:not([type=checkbox]),.action-panel textarea,.audition-modal select,.audition-modal textarea { display:block; width:100%; box-sizing:border-box; padding:9px; background:#0f0f1a; color:#e0e0e0; border:1px solid #475569; border-radius:5px; }.field-hint { margin:6px 0 10px; font-size:12px; }.consent { display:block; color:#cbd5e1; font-size:13px; line-height:1.5; margin:14px 0; }.consent input { margin-right:6px; }.warning { color:#fbbf24; font-size:12px; line-height:1.6; }.classic-warning { margin:0 0 12px; }.form-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:15px; }.add-row { display:flex; gap:8px; margin-top:16px; }.add-row select { flex:1; min-width:0; padding:8px; background:#0f0f1a; color:#e0e0e0; border:1px solid #475569; border-radius:5px; }.danger { color:#f87171; }.success-note { color:#86efac; font-size:13px; margin-top:12px; }.info-card { margin-top:18px; }.info-summary { display:grid; gap:12px; }.info-summary > div { display:grid; gap:4px; }.info-summary strong { font-size:14px; font-weight:500; white-space:pre-wrap; }.audition-modal { min-width:0; width:min(480px, calc(100vw - 32px)); }.audition-modal .field-hint { margin:10px 0; }
@media (max-width: 900px) { .section-grid { grid-template-columns:1fr; } .detail-header { flex-wrap:wrap; } }
@media (max-width: 560px) { .detail-card { padding:15px; } .section-heading { align-items:flex-start; flex-wrap:wrap; } .binding-card { align-items:flex-start; flex-direction:column; } }
</style>

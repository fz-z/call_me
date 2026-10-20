<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal" style="min-width:460px">
      <h3>{{ editId ? '编辑 Agent' : '创建 Agent' }}</h3>

      <section v-if="step === 1">
        <p class="step">Step 1/3：选择运行模式</p>
        <label class="mode-option"><input v-model="runtimeMode" type="radio" value="pipeline" /> <strong>经典 Pipeline</strong><small>STT → LLM → TTS；可选择 LLM、TTS 和已关联的音色。</small></label>
        <label class="mode-option"><input v-model="runtimeMode" type="radio" value="realtime" /> <strong>端到端实时</strong><small>使用一个实时模型配置与其专属音色绑定；不会降级为经典 Pipeline。</small></label>
        <div class="modal-actions"><button class="btn-ghost" @click="$emit('close')">取消</button><button class="btn btn-primary" @click="nextFromMode">下一步</button></div>
      </section>

      <section v-else-if="step === 2">
        <p class="step">Step 2/3：{{ runtimeMode === 'realtime' ? '选择实时模型与音色' : '选择经典模型与音色' }}</p>
        <template v-if="runtimeMode === 'pipeline'">
          <label>音色</label>
          <select v-model="selectedVoiceId" @change="selectPipelineVoice"><option value="">-- 选择音色 --</option><option v-for="voice in allVoices" :key="voice.id" :value="voice.id">{{ voice.name }}（{{ voice.type === 'builtin' ? '内置' : '克隆' }}）</option></select>
          <label>TTS 模型</label>
          <select v-model="selectedTtsConfigId" :disabled="!selectedVoiceId"><option value="">系统默认</option><option v-for="config in selectedVoiceTtsConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option></select>
          <label>LLM 模型</label>
          <select v-model="selectedModelConfigId"><option value="">系统默认</option><option v-for="config in modelConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.provider }}/{{ config.model }})</option></select>
        </template>
        <template v-else>
          <label>端到端实时模型</label>
          <select v-model="selectedRealtimeConfigId" @change="selectRealtimeConfig"><option value="">-- 选择实时模型 --</option><option v-for="config in realtimeConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.provider }}/{{ config.model }})</option></select>
          <label>音色（仅显示此模型已有绑定的音色）</label>
          <select v-model="selectedVoiceId" :disabled="!selectedRealtimeConfigId"><option value="">-- 选择音色 --</option><option v-for="voice in realtimeVoices" :key="voice.id" :value="voice.id">{{ voice.name }}（{{ voice.type === 'builtin' ? '内置' : '克隆' }}）</option></select>
          <p v-if="selectedRealtimeConfigId && !realtimeVoices.length" class="hint">此模型还没有可用音色。请到 <router-link to="/voices">声音库</router-link> 上传参考音频并创建实时绑定。</p>
          <p class="hint">端到端实时模式不使用单独的 LLM 或 TTS 配置。</p>
        </template>
        <p v-if="error" class="error">{{ error }}</p>
        <div class="modal-actions"><button class="btn-ghost" @click="step = 1">上一步</button><button class="btn btn-primary" :disabled="!canContinueRuntime" @click="step = 3">下一步</button></div>
      </section>

      <section v-else>
        <p class="step">Step 3/3：填写人设</p>
        <input v-model="alias" placeholder="Agent 别名" required />
        <textarea v-model="systemPrompt" rows="5" placeholder="人设描述（system prompt）"></textarea>
        <div class="summary"><div>运行模式：<strong>{{ runtimeDisplayName(runtimeMode) }}</strong></div><div>音色：<strong>{{ selectedVoice?.name || '未选择' }}</strong></div><div v-if="runtimeMode === 'pipeline'">TTS：<strong>{{ selectedTtsName }}</strong>　LLM：<strong>{{ selectedModelName }}</strong></div><div v-else>实时模型：<strong>{{ selectedRealtimeName }}</strong></div></div>
        <p v-if="error" class="error">{{ error }}</p>
        <div class="modal-actions"><button class="btn-ghost" @click="step = 2">上一步</button><button class="btn btn-primary" :disabled="saving" @click="submit">{{ saving ? '保存中…' : (editId ? '更新' : '创建 Agent') }}</button></div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import api from '../api.js';
import { buildAgentRuntimePayload, filterRealtimeVoices, runtimeDisplayName } from '../utils/agentRuntimeForm.js';

const props = defineProps({ editId: String, editAlias: String, editPrompt: String, editModelConfigId: String, editVoicePoolId: String, editTtsConfigId: String, editRealtimeConfigId: String, editRuntimeMode: String, editPhotoUrl: String });
const emit = defineEmits(['close', 'saved']);
const step = ref(1); const runtimeMode = ref(props.editRuntimeMode || 'pipeline'); const allVoices = ref([]); const bindingsByVoice = ref({}); const ttsByVoice = ref({}); const modelConfigs = ref([]); const realtimeConfigs = ref([]);
const selectedVoiceId = ref(props.editVoicePoolId || ''); const selectedTtsConfigId = ref(props.editTtsConfigId || ''); const selectedModelConfigId = ref(props.editModelConfigId || ''); const selectedRealtimeConfigId = ref(props.editRealtimeConfigId || ''); const alias = ref(props.editAlias || ''); const systemPrompt = ref(props.editPrompt || ''); const saving = ref(false); const error = ref('');
const selectedVoice = computed(() => allVoices.value.find((voice) => voice.id === selectedVoiceId.value));
const selectedVoiceTtsConfigs = computed(() => ttsByVoice.value[selectedVoiceId.value] || []);
const realtimeVoices = computed(() => filterRealtimeVoices(allVoices.value, bindingsByVoice.value, selectedRealtimeConfigId.value));
const selectedTtsName = computed(() => selectedTtsConfigId.value ? (selectedVoiceTtsConfigs.value.find((config) => config.id === selectedTtsConfigId.value)?.name || '未知') : '系统默认');
const selectedModelName = computed(() => selectedModelConfigId.value ? (modelConfigs.value.find((config) => config.id === selectedModelConfigId.value)?.name || '未知') : '系统默认');
const selectedRealtimeName = computed(() => realtimeConfigs.value.find((config) => config.id === selectedRealtimeConfigId.value)?.name || '未选择');
const canContinueRuntime = computed(() => runtimeMode.value === 'realtime' ? Boolean(selectedRealtimeConfigId.value && selectedVoiceId.value) : Boolean(selectedVoiceId.value));

function nextFromMode() {
  if (props.editId && runtimeMode.value !== (props.editRuntimeMode || 'pipeline') && !confirm('切换运行模式会清空不兼容的模型字段，是否继续？')) return;
  if (runtimeMode.value === 'realtime') { selectedModelConfigId.value = ''; selectedTtsConfigId.value = ''; } else { selectedRealtimeConfigId.value = ''; }
  step.value = 2;
}
function selectPipelineVoice() { const configs = selectedVoiceTtsConfigs.value; if (selectedTtsConfigId.value && !configs.some((config) => config.id === selectedTtsConfigId.value)) selectedTtsConfigId.value = ''; if (!selectedTtsConfigId.value && configs.length) selectedTtsConfigId.value = configs[0].id; }
function selectRealtimeConfig() { selectedVoiceId.value = ''; }

async function load() {
  try {
    const [voiceResult, ttsResult, modelResult, realtimeResult] = await Promise.all([api.get('/admin/voices'), api.get('/admin/tts-configs'), api.get('/admin/model-configs'), api.get('/admin/realtime-configs')]);
    allVoices.value = voiceResult.data; modelConfigs.value = modelResult.data; realtimeConfigs.value = realtimeResult.data;
    const records = await Promise.all(voiceResult.data.map(async (voice) => {
      const [tts, bindings] = await Promise.allSettled([api.get(`/admin/voices/${voice.id}/tts-configs`), api.get(`/admin/voices/${voice.id}/runtime-bindings`)]);
      return [voice.id, tts.status === 'fulfilled' ? tts.value.data : [], bindings.status === 'fulfilled' ? bindings.value.data : []];
    }));
    ttsByVoice.value = Object.fromEntries(records.map(([id, tts]) => [id, tts])); bindingsByVoice.value = Object.fromEntries(records.map(([id, , bindings]) => [id, bindings]));
    if (runtimeMode.value === 'pipeline') selectPipelineVoice();
  } catch (requestError) { error.value = requestError.response?.data?.detail || '加载 Agent 配置失败'; }
}
async function submit() { if (!alias.value.trim()) { error.value = '请输入 Agent 别名'; return; } saving.value = true; error.value = ''; try { const body = buildAgentRuntimePayload({ alias: alias.value.trim(), systemPrompt: systemPrompt.value, voicePoolId: selectedVoiceId.value, runtimeMode: runtimeMode.value, realtimeConfigId: selectedRealtimeConfigId.value, modelConfigId: selectedModelConfigId.value, ttsConfigId: selectedTtsConfigId.value, photoUrl: props.editPhotoUrl || '' }); if (props.editId) await api.patch(`/agents/${props.editId}`, body); else await api.post('/agents', body); emit('saved'); emit('close'); } catch (requestError) { error.value = requestError.response?.data?.detail || '保存失败'; } finally { saving.value = false; } }
onMounted(load);
</script>

<style scoped>
.step,.hint { color:#888; font-size:12px; }.mode-option { display:block; padding:12px; margin:8px 0; background:#16213e; border-radius:6px; cursor:pointer; }.mode-option small { display:block; margin:4px 0 0 24px; color:#aaa; }.mode-option strong { margin-left:6px; }.summary { background:#16213e; padding:10px 12px; border-radius:5px; font-size:12px; line-height:1.8; margin:10px 0; } select,textarea,input { width:100%; box-sizing:border-box; margin:5px 0 12px; } label:not(.mode-option) { color:#aaa; font-size:12px; }
</style>

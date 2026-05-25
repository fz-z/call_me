<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal" style="min-width:440px">
      <h3>{{ editId ? '编辑 Agent' : '创建 Agent' }}</h3>

      <!-- Step 1: Voice Selection -->
      <div v-if="step === 1">
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 1/3: 选择声音</p>
        <select v-model="selectedVoiceId" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" size="8">
          <option v-for="v in allVoices" :key="v.id" :value="v.id">
            {{ v.name }} ({{ v.type === 'builtin' ? '内置' : '克隆' }}){{ v._ttsNames ? ' → ' + v._ttsNames : '' }}
          </option>
        </select>
        <p v-if="selectedVoiceId" style="font-size:11px;color:#4a90d9">
          已选: {{ allVoices.find(v=>v.id===selectedVoiceId)?.name }}
          <template v-if="resolvedTtsConfigId"> → TTS: {{ ttsConfigs.find(t=>t.id===resolvedTtsConfigId)?.name || '未知' }}</template>
        </p>
        <div class="modal-actions">
          <button class="btn-ghost" @click="$emit('close')">取消</button>
          <button class="btn btn-primary" @click="step = 2" :disabled="!selectedVoiceId">下一步</button>
        </div>
      </div>

      <!-- Step 2: LLM Selection -->
      <div v-if="step === 2">
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 2/3: 选择 LLM 模型</p>
        <select v-model="selectedModelConfigId" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" size="6">
          <option value="">系统默认</option>
          <option v-for="mc in modelConfigs" :key="mc.id" :value="mc.id">
            {{ mc.name }} ({{ mc.provider }}/{{ mc.model }})
          </option>
        </select>
        <p v-if="selectedModelConfigId" style="font-size:11px;color:#4a90d9">
          已选: {{ modelConfigs.find(m=>m.id===selectedModelConfigId)?.name }}
        </p>
        <div class="modal-actions">
          <button class="btn-ghost" @click="step = 1">上一步</button>
          <button class="btn btn-primary" @click="step = 3">下一步</button>
        </div>
      </div>

      <!-- Step 3: Persona & Confirm -->
      <div v-if="step === 3">
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 3/3: 填写人设</p>
        <input v-model="alias" placeholder="Agent 别名" required style="width:100%;padding:8px;margin-bottom:8px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" />
        <textarea v-model="systemPrompt" placeholder="人设描述 (system prompt)" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px;min-height:80px"></textarea>

        <!-- Summary card -->
        <div style="background:#16213e;padding:8px 12px;border-radius:4px;margin-bottom:12px;font-size:12px">
          <div>🎤 声音: <strong>{{ allVoices.find(v=>v.id===selectedVoiceId)?.name || '未选择' }}</strong></div>
          <div>🔊 TTS: <strong>{{ ttsConfigs.find(t=>t.id===resolvedTtsConfigId)?.name || '待定' }}</strong></div>
          <div>🧠 LLM: <strong>{{ selectedModelConfigId ? modelConfigs.find(m=>m.id===selectedModelConfigId)?.name : '系统默认' }}</strong></div>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <div class="modal-actions">
          <button class="btn-ghost" @click="step = 2">上一步</button>
          <button class="btn btn-primary" @click="submit" :disabled="saving">
            {{ saving ? '保存中...' : (editId ? '更新' : '创建 Agent') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import api from '../api.js';

const props = defineProps({
  editId: String,
  editAlias: String,
  editPrompt: String,
  editModelConfigId: String,
  editVoicePoolId: String,
  editTtsConfigId: String,
});
const emit = defineEmits(['close', 'saved']);

const step = ref(1);
const ttsConfigs = ref([]);
const allVoices = ref([]);
const voiceTtsMap = ref({});  // voice_id → first linked tts_config_id
const modelConfigs = ref([]);
const selectedVoiceId = ref(props.editVoicePoolId || '');
const selectedModelConfigId = ref(props.editModelConfigId || '');
const alias = ref(props.editAlias || '');
const systemPrompt = ref(props.editPrompt || '');
const saving = ref(false);
const error = ref('');

// Auto-resolve TTS from selected voice's linked TTS configs
const resolvedTtsConfigId = computed(() => {
  if (!selectedVoiceId.value) return '';
  return voiceTtsMap.value[selectedVoiceId.value] || '';
});

onMounted(async () => {
  try {
    const [r1, r2, r3] = await Promise.all([
      api.get('/admin/tts-configs'),
      api.get('/admin/voices'),
      api.get('/admin/model-configs'),
    ]);
    ttsConfigs.value = r1.data;
    modelConfigs.value = r3.data;

    // Load voice → TTS mappings and enrich voice names
    const voices = r2.data;
    for (const v of voices) {
      try {
        const ttsRes = await api.get(`/admin/voices/${v.id}/tts-configs`);
        if (ttsRes.data.length > 0) {
          voiceTtsMap.value[v.id] = ttsRes.data[0].id;
          v._ttsNames = ttsRes.data.map(tc => tc.name).join(', ');
        }
      } catch (_) {}
    }
    allVoices.value = voices;
  } catch (_) {}
});

async function submit() {
  saving.value = true; error.value = '';
  try {
    const body = {
      alias: alias.value,
      system_prompt: systemPrompt.value,
      voice_pool_id: selectedVoiceId.value,
      tts_config_id: resolvedTtsConfigId.value || null,
      model_config_id: selectedModelConfigId.value || null,
    };
    if (props.editId) {
      await api.patch(`/agents/${props.editId}`, body);
    } else {
      await api.post('/agents', body);
    }
    emit('saved');
    emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed';
  } finally { saving.value = false; }
}
</script>

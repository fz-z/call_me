<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal" style="min-width:440px">
      <h3>{{ editId ? '编辑 Agent' : '创建 Agent' }}</h3>

      <!-- Step 1: TTS Model Selection -->
      <div v-if="step === 1">
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 1/4: 选择 TTS 模型</p>
        <select v-model="selectedTtsConfigId" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" size="6">
          <option value="">系统默认</option>
          <option v-for="tc in ttsConfigs" :key="tc.id" :value="tc.id">
            {{ tc.name }} ({{ tc.provider }}/{{ tc.model }})
          </option>
        </select>
        <p v-if="selectedTtsConfigId" style="font-size:11px;color:#4a90d9">
          已选: {{ ttsConfigs.find(t=>t.id===selectedTtsConfigId)?.name || '系统默认' }}
        </p>
        <div class="modal-actions">
          <button class="btn-ghost" @click="$emit('close')">取消</button>
          <button class="btn btn-primary" @click="step = 2">下一步</button>
        </div>
      </div>

      <!-- Step 2: Voice Selection (cascaded by TTS config) -->
      <div v-if="step === 2">
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 2/4: 选择声音</p>
        <p v-if="!filteredVoices.length" style="color:#888;font-size:12px;margin-bottom:8px">
          {{ loadingVoices ? '加载中...' : '此 TTS 模型暂无关联声音。请在声音库中关联声音。' }}
        </p>
        <select v-model="selectedVoiceId" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" size="6">
          <option value="" disabled>选择声音...</option>
          <option v-for="v in filteredVoices" :key="v.id" :value="v.id">
            {{ v.name }} ({{ v.type === 'builtin' ? '内置' : '克隆' }})
          </option>
        </select>
        <p v-if="selectedVoiceId" style="font-size:11px;color:#4a90d9">
          已选: {{ filteredVoices.find(v=>v.id===selectedVoiceId)?.name }}
        </p>
        <div class="modal-actions">
          <button class="btn-ghost" @click="step = 1">上一步</button>
          <button class="btn btn-primary" @click="step = 3" :disabled="!selectedVoiceId">下一步</button>
        </div>
      </div>

      <!-- Step 3: LLM Selection -->
      <div v-if="step === 3">
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 3/4: 选择 LLM 模型</p>
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
          <button class="btn-ghost" @click="step = 2">上一步</button>
          <button class="btn btn-primary" @click="step = 4">下一步</button>
        </div>
      </div>

      <!-- Step 4: Persona & Confirm -->
      <div v-if="step === 4">
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 4/4: 填写人设</p>
        <input v-model="alias" placeholder="Agent 别名" required style="width:100%;padding:8px;margin-bottom:8px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" />
        <textarea v-model="systemPrompt" placeholder="人设描述 (system prompt)" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px;min-height:80px"></textarea>

        <!-- Summary card -->
        <div style="background:#16213e;padding:8px 12px;border-radius:4px;margin-bottom:12px;font-size:12px">
          <div>🔊 TTS: <strong>{{ selectedTtsConfigId ? ttsConfigs.find(t=>t.id===selectedTtsConfigId)?.name : '系统默认' }}</strong></div>
          <div>🎤 声音: <strong>{{ filteredVoices.find(v=>v.id===selectedVoiceId)?.name || '未选择' }}</strong></div>
          <div>🧠 LLM: <strong>{{ selectedModelConfigId ? modelConfigs.find(m=>m.id===selectedModelConfigId)?.name : '系统默认' }}</strong></div>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <div class="modal-actions">
          <button class="btn-ghost" @click="step = 3">上一步</button>
          <button class="btn btn-primary" @click="submit" :disabled="saving">
            {{ saving ? '保存中...' : (editId ? '更新' : '创建 Agent') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue';
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
const filteredVoices = ref([]);
const modelConfigs = ref([]);
const selectedTtsConfigId = ref(props.editTtsConfigId || '');
const selectedVoiceId = ref(props.editVoicePoolId || '');
const selectedModelConfigId = ref(props.editModelConfigId || '');
const alias = ref(props.editAlias || '');
const systemPrompt = ref(props.editPrompt || '');
const saving = ref(false);
const error = ref('');
const loadingVoices = ref(false);

onMounted(async () => {
  try {
    const [r1, r2, r3] = await Promise.all([
      api.get('/admin/tts-configs'),
      api.get('/admin/voices'),
      api.get('/admin/model-configs'),
    ]);
    ttsConfigs.value = r1.data;
    allVoices.value = r2.data;
    modelConfigs.value = r3.data;

    // If editing with a pre-selected TTS config, load cascaded voices
    if (selectedTtsConfigId.value) {
      filterVoices();
    } else {
      filteredVoices.value = allVoices.value;
    }
  } catch (_) {}
});

// Watch TTS config selection to cascade voice filter
watch(selectedTtsConfigId, async (newVal) => {
  filterVoices();
  // Reset voice selection when TTS config changes
  if (step.value === 2) {
    selectedVoiceId.value = '';
  }
});

async function filterVoices() {
  if (!selectedTtsConfigId.value) {
    filteredVoices.value = allVoices.value;
    return;
  }
  loadingVoices.value = true;
  try {
    const r = await api.get(`/admin/voices?tts_config_id=${selectedTtsConfigId.value}`);
    filteredVoices.value = r.data;
  } catch (_) {
    filteredVoices.value = [];
  } finally {
    loadingVoices.value = false;
  }
}

async function submit() {
  saving.value = true; error.value = '';
  try {
    const body = {
      alias: alias.value,
      system_prompt: systemPrompt.value,
      voice_pool_id: selectedVoiceId.value,
      tts_config_id: selectedTtsConfigId.value || null,
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

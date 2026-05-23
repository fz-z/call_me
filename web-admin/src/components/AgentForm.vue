<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal" style="min-width:420px">
      <h3>{{ editId ? '编辑 Agent' : '创建 Agent' }}</h3>

      <!-- Step 1: Voice Selection -->
      <div v-if="step === 1">
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 1/3: 选择声音</p>
        <select v-model="selectedVoiceId" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" size="6">
          <option value="" disabled>选择声音...</option>
          <option v-for="v in voices" :key="v.id" :value="v.id">
            {{ v.name }} ({{ v.type === 'builtin' ? '内置' : '克隆' }})
          </option>
        </select>
        <p v-if="selectedVoiceId" style="font-size:11px;color:#4a90d9">
          已选: {{ voices.find(v=>v.id===selectedVoiceId)?.name }}
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
          <option value="">系统默认 (.env)</option>
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
        <p style="color:#888;font-size:12px;margin-bottom:12px">Step 3/3: 写人设</p>
        <input v-model="alias" placeholder="Agent 别名" required style="width:100%;padding:8px;margin-bottom:8px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" />
        <textarea v-model="systemPrompt" placeholder="人设描述 (system prompt)" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px;min-height:80px"></textarea>

        <!-- Summary -->
        <div style="background:#16213e;padding:8px 12px;border-radius:4px;margin-bottom:12px;font-size:12px">
          <div>🎤 声音: <strong>{{ voices.find(v=>v.id===selectedVoiceId)?.name || '未选择' }}</strong></div>
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
import { ref, onMounted } from 'vue';
import api from '../api.js';

const props = defineProps({
  editId: String,
  editAlias: String,
  editPrompt: String,
  editModelConfigId: String,
  editVoicePoolId: String,
});
const emit = defineEmits(['close', 'saved']);

const step = ref(1);
const voices = ref([]);
const modelConfigs = ref([]);
const selectedVoiceId = ref(props.editVoicePoolId || '');
const selectedModelConfigId = ref(props.editModelConfigId || '');
const alias = ref(props.editAlias || '');
const systemPrompt = ref(props.editPrompt || '');
const saving = ref(false);
const error = ref('');

onMounted(async () => {
  try {
    const [r1, r2] = await Promise.all([
      api.get('/admin/voices'),
      api.get('/admin/model-configs'),
    ]);
    voices.value = r1.data;
    modelConfigs.value = r2.data;
  } catch (_) {}
});

async function submit() {
  saving.value = true; error.value = '';
  try {
    const body = {
      alias: alias.value,
      system_prompt: systemPrompt.value,
      voice_pool_id: selectedVoiceId.value,
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

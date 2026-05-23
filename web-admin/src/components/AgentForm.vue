<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <form class="modal" @submit.prevent="submit">
      <h3>{{ editId ? '编辑' : '创建' }} Agent</h3>
      <input v-model="alias" placeholder="别名" required />
      <textarea v-model="systemPrompt" placeholder="人设描述 (system prompt)"></textarea>
      <select v-model="modelConfigId" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px">
        <option value="">LLM: 系统默认 (.env)</option>
        <option v-for="mc in modelConfigs" :key="mc.id" :value="mc.id">
          {{ mc.name }} ({{ mc.provider }}/{{ mc.model }})
        </option>
      </select>
      <input v-if="!editId" type="file" accept="audio/*" @change="onFile" required />
      <p v-if="error" class="error">{{ error }}</p>
      <div class="modal-actions">
        <button type="button" class="btn-ghost" @click="$emit('close')">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="loading">
          {{ loading ? '保存中...' : '保存' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';

const props = defineProps({ editId: String, editAlias: String, editPrompt: String, editModelConfigId: String });
const emit = defineEmits(['close', 'saved']);

const alias = ref(props.editAlias || '');
const systemPrompt = ref(props.editPrompt || '');
const modelConfigs = ref([]);
const modelConfigId = ref(props.editModelConfigId || '');
const file = ref(null);
const loading = ref(false);
const error = ref('');

onMounted(async () => {
  try {
    const r = await api.get('/admin/model-configs');
    modelConfigs.value = r.data;
  } catch (_) {}
});

function onFile(e) { file.value = e.target.files[0]; }

async function submit() {
  loading.value = true;
  error.value = '';
  try {
    if (props.editId) {
      await api.patch(`/agents/${props.editId}`, {
        alias: alias.value,
        system_prompt: systemPrompt.value,
        model_config_id: modelConfigId.value || null,
      });
    } else {
      const fd = new FormData();
      fd.append('alias', alias.value);
      fd.append('system_prompt', systemPrompt.value);
      if (modelConfigId.value) fd.append('model_config_id', modelConfigId.value);
      fd.append('audio_file', file.value);
      await api.post('/agents', fd);
    }
    emit('saved');
    emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed';
  } finally {
    loading.value = false;
  }
}
</script>

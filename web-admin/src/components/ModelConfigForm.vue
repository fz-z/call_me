<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <form class="modal" @submit.prevent="submit" style="min-width:400px">
      <h3>{{ editId ? '编辑' : '新建' }}模型配置</h3>
      <input v-model="form.name" placeholder="配置名称" required />
      <select v-model="form.provider" required>
        <option value="qwen">qwen (通义千问)</option>
        <option value="deepseek">deepseek</option>
      </select>
      <input v-model="form.model" placeholder="模型名 (如 qwen3-max, deepseek-chat)" required />
      <select v-model="form.api_key_id" required>
        <option value="">-- 选择 API Key --</option>
        <option v-for="ak in apiKeys" :key="ak.id" :value="ak.id">{{ ak.name }} ({{ ak.provider }})</option>
      </select>
      <label style="font-size:12px;color:#888;display:block;margin-bottom:4px">Temperature: {{ form.temperature }}</label>
      <input v-model.number="form.temperature" type="range" min="0" max="2" step="0.1" style="width:100%;margin-bottom:12px" />
      <input v-model.number="form.max_tokens" placeholder="Max Tokens" type="number" style="width:100%;padding:8px;margin-bottom:12px;background:#0f0f1a;border:1px solid #333;color:#e0e0e0;border-radius:4px" />
      <p v-if="error" class="error">{{ error }}</p>
      <div class="modal-actions">
        <button type="button" class="btn-ghost" @click="$emit('close')">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="loading">保存</button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue';
import api from '../api.js';

const props = defineProps({ editId: String, editData: Object });
const emit = defineEmits(['close', 'saved']);

const apiKeys = ref([]);

const form = reactive({
  name: props.editData?.name || '',
  provider: props.editData?.provider || 'qwen',
  model: props.editData?.model || '',
  api_key_id: props.editData?.api_key_id || '',
  temperature: props.editData?.temperature ?? 0.7,
  max_tokens: props.editData?.max_tokens ?? 2048,
});
const loading = ref(false);
const error = ref('');

async function loadApiKeys() {
  try { const r = await api.get('/admin/api-keys'); apiKeys.value = r.data; } catch (_) {}
}

async function submit() {
  loading.value = true; error.value = '';
  try {
    const payload = {
      name: form.name,
      provider: form.provider,
      model: form.model,
      api_key_id: form.api_key_id || null,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
    };
    if (props.editId) {
      await api.patch(`/admin/model-configs/${props.editId}`, payload);
    } else {
      await api.post('/admin/model-configs', payload);
    }
    emit('saved'); emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed';
  } finally { loading.value = false; }
}

onMounted(loadApiKeys);
</script>

<style scoped>
select { width:100%; padding:8px; margin-bottom:12px; background:#0f0f1a; border:1px solid #333; color:#e0e0e0; border-radius:4px; }
</style>

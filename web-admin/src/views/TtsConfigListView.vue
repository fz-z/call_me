<template>
  <div>
    <div class="page-header">
      <h2>TTS 模型配置</h2>
      <button class="btn btn-primary" @click="showForm = true">+ 新建配置</button>
    </div>
    <table>
      <thead><tr>
        <th>名称</th><th>提供商</th><th>模型</th><th>关联音色</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="tc in configs" :key="tc.id">
          <td>{{ tc.name }}</td>
          <td>{{ tc.provider }}</td>
          <td style="color:#4a90d9">{{ tc.model }}</td>
          <td>
            <span v-for="v in tc._voices" :key="v.id" class="tag">{{ v.name }}</span>
            <span v-if="!tc._voices?.length" style="color:#888;font-size:12px">暂无</span>
          </td>
          <td>
            <button class="btn-ghost" @click="edit(tc)">编辑</button>
            <button class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(tc)">删除</button>
          </td>
        </tr>
        <tr v-if="!configs.length">
          <td colspan="5" style="color:#888;text-align:center;padding:24px">暂无配置。Agent 将使用 .env 系统默认 TTS。</td>
        </tr>
      </tbody>
    </table>

    <!-- Form modal -->
    <div v-if="showForm" class="modal-overlay" @click.self="closeForm">
      <form class="modal" @submit.prevent="submit" style="min-width:400px">
        <h3>{{ editId ? '编辑' : '新建' }} TTS 配置</h3>
        <input v-model="form.name" placeholder="配置名称" required />
        <select v-model="form.provider" required>
          <option value="qwen">qwen</option>
          <option value="elevenlabs">elevenlabs</option>
        </select>
        <input v-model="form.model" placeholder="模型名 (如 qwen3-tts-flash-realtime)" required />
        <select v-model="form.api_key_id" required>
          <option value="">-- 选择 API Key --</option>
          <option v-for="ak in apiKeys" :key="ak.id" :value="ak.id">{{ ak.name }} ({{ ak.provider }})</option>
        </select>
        <p v-if="error" class="error">{{ error }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="closeForm">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="loading">保存</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue';
import api from '../api.js';

const configs = ref([]);
const apiKeys = ref([]);
const showForm = ref(false);
const editId = ref(null);
const form = reactive({ name: '', provider: 'qwen', model: '', api_key_id: '' });
const loading = ref(false);
const error = ref('');

async function loadApiKeys() {
  try { const r = await api.get('/admin/api-keys'); apiKeys.value = r.data; } catch (_) {}
}

async function load() {
  const r1 = await api.get('/admin/tts-configs');

  configs.value = r1.data.map(tc => ({ ...tc, _voices: [] }));

  // Load linked voices per config (using the voice-TTS link API)
  for (const tc of configs.value) {
    try {
      const r = await api.get(`/admin/voices?tts_config_id=${tc.id}`);
      tc._voices = r.data;
    } catch (_) {}
  }
}

function edit(tc) {
  editId.value = tc.id;
  form.name = tc.name;
  form.provider = tc.provider;
  form.model = tc.model;
  form.api_key_id = tc.api_key_id || '';
  showForm.value = true;
}

function closeForm() {
  showForm.value = false;
  editId.value = null;
  form.name = '';
  form.provider = 'qwen';
  form.model = '';
  form.api_key_id = '';
  error.value = '';
}

async function submit() {
  loading.value = true;
  error.value = '';
  try {
    const payload = {
      name: form.name,
      provider: form.provider,
      model: form.model,
      api_key_id: form.api_key_id || null,
    };
    if (editId.value) {
      await api.patch(`/admin/tts-configs/${editId.value}`, payload);
    } else {
      await api.post('/admin/tts-configs', payload);
    }
    closeForm();
    await load();
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed';
  } finally {
    loading.value = false;
  }
}

async function del(tc) {
  const count = tc._voices?.length || 0;
  const msg = count
    ? `Delete "${tc.name}"? ${count} voice(s) will lose their TTS model link.`
    : `Delete "${tc.name}"?`;
  if (!confirm(msg)) return;
  await api.delete(`/admin/tts-configs/${tc.id}`);
  await load();
}

onMounted(() => { loadApiKeys(); load(); });
</script>

<style scoped>
select {
  width: 100%;
  padding: 8px;
  margin-bottom: 12px;
  background: #0f0f1a;
  border: 1px solid #333;
  color: #e0e0e0;
  border-radius: 4px;
}
</style>

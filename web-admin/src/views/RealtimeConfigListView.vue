<template>
  <div>
    <div class="page-header">
      <h2>实时模型</h2>
      <button class="btn btn-primary" @click="openCreate">+ 新建配置</button>
    </div>

    <p v-if="pageError" class="error page-error">{{ pageError }}</p>

    <table>
      <thead>
        <tr>
          <th>名称</th><th>API Key</th><th>提供商</th><th>模型</th><th>区域</th><th>能力</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="config in configs" :key="config.id">
          <td>{{ config.name }}</td>
          <td>{{ getApiKeyName(config.api_key_id) || '未配置' }}</td>
          <td>{{ config.provider }}</td>
          <td style="color:#4a90d9">{{ config.model }}</td>
          <td>{{ config.region || '-' }}</td>
          <td><code>{{ config.capabilities_json || '{}' }}</code></td>
          <td>
            <button class="btn-ghost" @click="edit(config)">编辑</button>
            <button class="btn-ghost danger" @click="del(config)">删除</button>
          </td>
        </tr>
        <tr v-if="!configs.length">
          <td colspan="7" class="empty">暂无实时模型配置。</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showForm" class="modal-overlay" @click.self="closeForm">
      <form class="modal" @submit.prevent="submit" style="min-width:440px">
        <h3>{{ editId ? '编辑' : '新建' }}实时模型配置</h3>
        <input v-model="form.name" placeholder="配置名称" required />

        <label>提供商</label>
        <select v-model="form.provider" disabled>
          <option value="qwen">qwen</option>
        </select>

        <label>模型</label>
        <input v-model="form.model" readonly />

        <label>API Key</label>
        <select v-model="form.api_key_id" required>
          <option value="">-- 选择 Qwen API Key --</option>
          <option v-for="apiKey in qwenApiKeys" :key="apiKey.id" :value="apiKey.id">
            {{ apiKey.name }}
          </option>
        </select>

        <label>Endpoint（可选）</label>
        <input v-model="form.endpoint" placeholder="wss://..." />

        <label>区域（可选）</label>
        <input v-model="form.region" placeholder="如 cn-hangzhou" />

        <label>Capabilities（JSON 对象）</label>
        <textarea v-model="form.capabilities" rows="4" spellcheck="false" />

        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="closeForm">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="loading">
            {{ loading ? '保存中...' : '保存' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import api from '../api.js';
import {
  buildRealtimeConfigPayload,
  getRealtimeConfigDeleteError,
  QWEN_REALTIME_MODEL,
  QWEN_REALTIME_PROVIDER,
} from '../utils/realtimeConfigForm.js';

const configs = ref([]);
const apiKeys = ref([]);
const showForm = ref(false);
const editId = ref(null);
const loading = ref(false);
const pageError = ref('');
const formError = ref('');
const form = reactive(defaultForm());

const qwenApiKeys = computed(() => apiKeys.value.filter((apiKey) => apiKey.provider === 'qwen'));

function defaultForm() {
  return {
    name: '',
    provider: QWEN_REALTIME_PROVIDER,
    model: QWEN_REALTIME_MODEL,
    api_key_id: '',
    endpoint: '',
    region: '',
    capabilities: '{\n  "voice_clone": true\n}',
  };
}

function getApiKeyName(apiKeyId) {
  return apiKeys.value.find((apiKey) => apiKey.id === apiKeyId)?.name;
}

function setForm(values) {
  Object.assign(form, defaultForm(), values);
}

function openCreate() {
  editId.value = null;
  formError.value = '';
  setForm({});
  showForm.value = true;
}

function edit(config) {
  editId.value = config.id;
  formError.value = '';
  setForm({
    name: config.name,
    api_key_id: config.api_key_id || '',
    endpoint: config.endpoint || '',
    region: config.region || '',
    capabilities: formatCapabilities(config.capabilities_json),
  });
  showForm.value = true;
}

function formatCapabilities(capabilitiesJson) {
  try {
    return JSON.stringify(JSON.parse(capabilitiesJson || '{}'), null, 2);
  } catch (_) {
    return capabilitiesJson || '{}';
  }
}

function closeForm() {
  showForm.value = false;
  editId.value = null;
  formError.value = '';
  setForm({});
}

async function loadApiKeys() {
  const response = await api.get('/admin/api-keys');
  apiKeys.value = response.data;
}

async function load() {
  pageError.value = '';
  try {
    const response = await api.get('/admin/realtime-configs');
    configs.value = response.data;
  } catch (error) {
    pageError.value = error.response?.data?.detail || '加载实时模型配置失败';
  }
}

async function submit() {
  loading.value = true;
  formError.value = '';
  try {
    const payload = buildRealtimeConfigPayload(form);
    if (editId.value) {
      await api.patch(`/admin/realtime-configs/${editId.value}`, payload);
    } else {
      await api.post('/admin/realtime-configs', payload);
    }
    closeForm();
    await load();
  } catch (error) {
    formError.value = error.response?.data?.detail || error.message || '保存失败';
  } finally {
    loading.value = false;
  }
}

async function del(config) {
  pageError.value = '';
  if (!confirm(`删除“${config.name}”吗？`)) return;
  try {
    await api.delete(`/admin/realtime-configs/${config.id}`);
    await load();
  } catch (error) {
    pageError.value = getRealtimeConfigDeleteError(error.response?.data?.detail);
  }
}

onMounted(async () => {
  await Promise.all([loadApiKeys(), load()]);
});
</script>

<style scoped>
select, textarea {
  width: 100%;
  padding: 8px;
  margin-bottom: 12px;
  background: #0f0f1a;
  border: 1px solid #333;
  color: #e0e0e0;
  border-radius: 4px;
  box-sizing: border-box;
}

label {
  display: block;
  margin: 0 0 4px;
  color: #aaa;
  font-size: 12px;
}

code {
  color: #b5b5c7;
  font-size: 11px;
  word-break: break-word;
}

.danger { color: #e74c3c; margin-left: 4px; }
.empty { color: #888; text-align: center; padding: 24px; }
.page-error { margin: 0 0 12px; }
</style>

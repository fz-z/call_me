<template>
  <div>
    <div class="page-header">
      <h2>API Key 管理</h2>
      <button class="btn btn-primary" @click="showForm = true">+ 新建 Key</button>
    </div>
    <table>
      <thead><tr>
        <th>名称</th><th>提供商</th><th>Key (脱敏)</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="k in keys" :key="k.id">
          <td>{{ k.name }}</td>
          <td>{{ k.provider }}</td>
          <td style="color:#888;font-size:12px">{{ maskKey(k.api_key) }}</td>
          <td>
            <button class="btn-ghost" @click="edit(k)">编辑</button>
            <button class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(k)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showForm" class="modal-overlay" @click.self="closeForm">
      <form class="modal" @submit.prevent="submit" style="min-width:400px">
        <h3>{{ editId ? '编辑' : '新建' }} API Key</h3>
        <input v-model="form.name" placeholder="名称 (如 DashScope, DeepSeek)" required />
        <input v-model="form.provider" placeholder="提供商 (如 qwen, deepseek, huoshan, openai)" required />
        <input v-model="form.api_key" placeholder="API Key" type="password" required />
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

const keys = ref([]);
const showForm = ref(false);
const editId = ref(null);
const form = reactive({ name: '', provider: 'qwen', api_key: '' });
const loading = ref(false);
const error = ref('');

function maskKey(k) { return k ? k.substring(0, 8) + '...' + k.substring(k.length - 4) : ''; }

async function load() {
  const r = await api.get('/admin/api-keys');
  keys.value = r.data;
}

function edit(k) { editId.value = k.id; form.name = k.name; form.provider = k.provider; form.api_key = k.api_key; showForm.value = true; }
function closeForm() { showForm.value = false; editId.value = null; form.name = ''; form.provider = 'qwen'; form.api_key = ''; }

async function submit() {
  loading.value = true; error.value = '';
  try {
    if (editId.value) { await api.patch(`/admin/api-keys/${editId.value}`, form); }
    else { await api.post('/admin/api-keys', form); }
    closeForm(); await load();
  } catch (e) { error.value = e.response?.data?.detail || 'Failed'; }
  finally { loading.value = false; }
}

async function del(k) {
  if (!confirm(`Delete "${k.name}"?`)) return;
  await api.delete(`/admin/api-keys/${k.id}`);
  await load();
}

onMounted(load);
</script>


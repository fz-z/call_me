<template>
  <div>
    <div class="page-header">
      <h2>LLM模型</h2>
      <button class="btn btn-primary" @click="showForm = true">+ 新建配置</button>
    </div>
    <table>
      <thead><tr>
        <th>名称</th><th>提供商</th><th>模型</th><th>使用此配置的 Agent</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="mc in configs" :key="mc.id">
          <td>{{ mc.name }}</td>
          <td>{{ getApiKeyName(mc.api_key_id) || mc.provider }}</td>
          <td style="color:#4a90d9">{{ mc.model }}</td>
          <td>
            <span v-for="a in mc._agents" :key="a.id" class="tag">{{ a.alias }}</span>
            <span v-if="!mc._agents?.length" style="color:#888;font-size:12px">暂无</span>
          </td>
          <td>
            <button class="btn-ghost" @click="edit(mc)">编辑</button>
            <button class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(mc)">删除</button>
          </td>
        </tr>
        <tr v-if="!configs.length">
          <td colspan="5" style="color:#888;text-align:center;padding:24px">暂无配置。Agent 将使用 .env 系统默认。</td>
        </tr>
      </tbody>
    </table>
    <ModelConfigForm v-if="showForm" :editId="editId" :editData="editData" @close="closeForm" @saved="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';
import ModelConfigForm from '../components/ModelConfigForm.vue';

const configs = ref([]);
const apiKeys = ref([]);
const showForm = ref(false);
const editId = ref(null);
const editData = ref(null);

function getApiKeyName(apiKeyId) {
  if (!apiKeyId) return null;
  const ak = apiKeys.value.find(k => k.id === apiKeyId);
  return ak ? ak.name : null;
}

async function loadApiKeys() {
  try { const r = await api.get('/admin/api-keys'); apiKeys.value = r.data; } catch (_) {}
}

async function load() {
  const [r1, r2] = await Promise.all([
    api.get('/admin/model-configs'),
    api.get('/admin/agents'),
  ]);
  const allAgents = r2.data;
  configs.value = r1.data.map(mc => ({
    ...mc,
    _agents: allAgents.filter(a => a.model_config_id === mc.id),
  }));
}

function edit(mc) { editId.value = mc.id; editData.value = mc; showForm.value = true; }
function closeForm() { showForm.value = false; editId.value = null; editData.value = null; }

async function del(mc) {
  const count = mc._agents?.length || 0;
  const msg = count ? `Delete "${mc.name}"? ${count} agent(s) will fall back to system default.` : `Delete "${mc.name}"?`;
  if (!confirm(msg)) return;
  await api.delete(`/admin/model-configs/${mc.id}`);
  await load();
}

onMounted(() => { loadApiKeys(); load(); });
</script>

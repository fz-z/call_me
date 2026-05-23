<template>
  <div>
    <router-link to="/users" class="back-link">← 返回列表</router-link>
    <div class="page-header"><h2>{{ username }} 的 Agent</h2></div>
    <table>
      <thead><tr>
        <th>别名</th><th>音色</th><th>自定义人设</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="a in agents" :key="a.id">
          <td>{{ a.alias }}</td>
          <td style="color:#4a90d9;font-size:12px">{{ (a.voice_id || '').substring(0, 25) }}</td>
          <td style="color:#888;max-width:300px">{{ a.system_prompt }}</td>
          <td>
            <button class="btn-ghost" @click="startEdit(a)">编辑人设</button>
            <button class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="revoke(a)">回收</button>
          </td>
        </tr>
        <tr v-if="!agents.length">
          <td colspan="4" style="color:#888;text-align:center;padding:24px">暂无 Agent</td>
        </tr>
      </tbody>
    </table>

    <div v-if="editingAgent" class="modal-overlay" @click.self="editingAgent = null">
      <form class="modal" @submit.prevent="saveEdit" style="min-width:400px">
        <h3>编辑 {{ editingAgent.alias }} 的人设</h3>
        <textarea v-model="editText" rows="6" style="width:100%;background:#111;color:#ddd;border:1px solid #333;border-radius:6px;padding:10px;font-size:14px" placeholder="输入新的 system prompt"></textarea>
        <p v-if="editError" class="error">{{ editError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="editingAgent = null">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="editLoading">保存</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import api from '../api.js';

const route = useRoute();
const username = route.params.username;
const agents = ref([]);
const editingAgent = ref(null);
const editText = ref('');
const editLoading = ref(false);
const editError = ref('');

async function load() {
  const r = await api.get(`/admin/users/${username}/agents`);
  agents.value = r.data;
}

function startEdit(agent) {
  editingAgent.value = agent;
  editText.value = agent.system_prompt || '';
  editError.value = '';
}

async function saveEdit() {
  if (!editText.value.trim()) return;
  editLoading.value = true; editError.value = '';
  try {
    await api.patch(`/agents/${editingAgent.value.id}`, { system_prompt: editText.value.trim() });
    editingAgent.value = null;
    await load();
  } catch (e) {
    editError.value = e.response?.data?.detail || 'Update failed';
  } finally { editLoading.value = false; }
}

async function revoke(agent) {
  if (!confirm(`Revoke ${agent.alias}?`)) return;
  const rootId = agent.source_agent_id || agent.id;
  await api.delete(`/agents/${rootId}/grant/${username}`);
  await load();
}

onMounted(load);
</script>

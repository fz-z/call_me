<template>
  <div>
    <div class="page-header">
      <h2>Agent 管理</h2>
      <button class="btn btn-primary" @click="showCreate = true">+ 创建 Agent</button>
    </div>
    <table>
      <thead><tr>
        <th>别名</th><th>运行模式</th><th>音色</th><th>创建者</th><th>已授权用户</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="a in agents" :key="a.id">
          <td>{{ a.alias }}</td>
          <td><span class="tag" :style="a.runtime_mode === 'realtime' ? 'background:#3d2d00' : 'background:#1a3a5c'">{{ runtimeLabel(a) }}</span></td>
          <td style="color:#4a90d9;font-size:12px">{{ getVoiceName(a.voice_pool_id) }}</td>
          <td>{{ getUserName(a.owner_id) }}</td>
          <td>
            <span v-for="u in a.authorized_users" :key="u" class="tag">
              {{ u }} <span class="revoke" @click="revoke(a.id, u)">✕</span>
            </span>
            <span v-if="!a.authorized_users?.length" style="color:#888;font-size:12px">暂无</span>
          </td>
          <td>
            <button class="btn-ghost" @click="startEdit(a)">编辑</button>
            <button class="btn-ghost" @click="openGrant(a)">授权</button>
            <button class="btn-ghost" style="margin-left:4px" @click="$router.push(`/agents/${a.id}`)">详情</button>
            <button class="btn-ghost" style="margin-left:4px;color:#e74c3c" @click="del(a.id)">删除</button>
          </td>
        </tr>
        <tr v-if="!agents.length">
          <td colspan="6" style="color:#888;text-align:center;padding:24px">暂无 Agent</td>
        </tr>
      </tbody>
    </table>

    <AgentForm v-if="showCreate" @close="showCreate = false" @saved="load" />
    <GrantDialog v-if="grantTarget" :agent="grantTarget" @close="grantTarget = null" @done="load" />

    <div v-if="editing" class="modal-overlay" @click.self="editing = null">
      <form class="modal" @submit.prevent="saveEdit" style="min-width:400px">
        <h3>编辑 Agent</h3>
        <input v-model="editForm.alias" placeholder="别名" required />
        <textarea v-model="editForm.system_prompt" rows="5" placeholder="人设 (system prompt)" style="width:100%;background:#111;color:#ddd;border:1px solid #333;border-radius:6px;padding:10px;font-size:14px;margin-bottom:12px"></textarea>
        <label style="display:block;color:#888;font-size:12px;margin-bottom:6px">语速：{{ Number(editForm.speech_rate || 1).toFixed(1) }}x（0.5 慢 – 2.0 快）</label>
        <input v-model.number="editForm.speech_rate" type="range" min="0.5" max="2" step="0.1" style="width:100%;margin-bottom:12px" />
        <p v-if="editError" class="error">{{ editError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="editing = null">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="editLoading">保存</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';
import AgentForm from '../components/AgentForm.vue';
import GrantDialog from '../components/GrantDialog.vue';
import { runtimeDisplayName } from '../utils/agentRuntimeForm.js';

const agents = ref([]);
const users = ref([]);
const voices = ref([]);
const realtimeConfigs = ref([]);
const showCreate = ref(false);
const grantTarget = ref(null);
const editing = ref(null);
const editForm = ref({ alias: '', system_prompt: '', speech_rate: 1.0 });
const editLoading = ref(false);
const editError = ref('');

async function load() {
  const [r1, r2, r3, r4] = await Promise.all([
    api.get('/admin/root-agents'),
    api.get('/admin/users'),
    api.get('/admin/voices'),
    api.get('/admin/realtime-configs'),
  ]);
  users.value = r2.data;
  voices.value = r3.data;
  realtimeConfigs.value = r4.data;
  for (const a of r1.data) {
    const copies = await api.get(`/admin/agents/${a.id}/copies`);
    a.authorized_users = copies.data.map(c => users.value.find(u => u.id === c.owner_id)?.username || '?');
  }
  agents.value = r1.data;
}

function getVoiceName(id) {
  if (!id) return '-';
  const v = voices.value.find(x => x.id === id);
  return v ? v.name : id.substring(0, 8);
}

function getUserName(uid) {
  return users.value.find(u => u.id === uid)?.username || uid?.substring(0, 8);
}

function runtimeLabel(agent) {
  if (agent.runtime_mode !== 'realtime') return runtimeDisplayName('pipeline');
  const config = realtimeConfigs.value.find((item) => item.id === agent.realtime_config_id);
  return config ? `${runtimeDisplayName('realtime')} · ${config.provider}` : runtimeDisplayName('realtime');
}

async function revoke(agentId, username) {
  if (!confirm(`Revoke ${username}'s access?`)) return;
  await api.delete(`/agents/${agentId}/grant/${username}`);
  await load();
}

async function del(id) {
  if (!confirm('Delete this agent and all its copies?')) return;
  await api.delete(`/agents/${id}`);
  await load();
}

function openGrant(a) { grantTarget.value = a; }

function startEdit(a) {
  editing.value = a;
  editForm.value = { alias: a.alias, system_prompt: a.system_prompt || '', speech_rate: Number(a.speech_rate || 1.0) };
  editError.value = '';
}

async function saveEdit() {
  if (!editForm.value.alias.trim()) return;
  editLoading.value = true; editError.value = '';
  try {
    await api.patch(`/agents/${editing.value.id}`, editForm.value);
    editing.value = null;
    await load();
  } catch (e) {
    editError.value = e.response?.data?.detail || 'Update failed';
  } finally { editLoading.value = false; }
}

onMounted(load);
</script>

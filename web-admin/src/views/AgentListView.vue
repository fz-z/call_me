<template>
  <div>
    <div class="page-header">
      <h2>Agent 管理</h2>
      <button class="btn btn-primary" @click="showCreate = true">+ 创建 Agent</button>
    </div>
    <table>
      <thead><tr>
        <th>别名</th><th>音色</th><th>创建者</th><th>已授权用户</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="a in agents" :key="a.id">
          <td>{{ a.alias }}</td>
          <td style="color:#4a90d9;font-size:12px">{{ (a.voice_id || '').substring(0, 25) }}</td>
          <td>{{ getUserName(a.owner_id) }}</td>
          <td>
            <span v-for="u in a.authorized_users" :key="u" class="tag">
              {{ u }} <span class="revoke" @click="revoke(a.id, u)">✕</span>
            </span>
            <span v-if="!a.authorized_users?.length" style="color:#888;font-size:12px">暂无</span>
          </td>
          <td>
            <button class="btn-ghost" @click="openGrant(a)">授权</button>
            <button class="btn-ghost" style="margin-left:4px" @click="$router.push(`/agents/${a.id}`)">详情</button>
            <button class="btn-ghost" style="margin-left:4px;color:#e74c3c" @click="del(a.id)">删除</button>
          </td>
        </tr>
        <tr v-if="!agents.length">
          <td colspan="5" style="color:#888;text-align:center;padding:24px">暂无 Agent</td>
        </tr>
      </tbody>
    </table>

    <AgentForm v-if="showCreate" @close="showCreate = false" @saved="load" />
    <GrantDialog v-if="grantTarget" :agent="grantTarget" @close="grantTarget = null" @done="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';
import AgentForm from '../components/AgentForm.vue';
import GrantDialog from '../components/GrantDialog.vue';

const agents = ref([]);
const users = ref([]);
const showCreate = ref(false);
const grantTarget = ref(null);

async function load() {
  const [r1, r2] = await Promise.all([
    api.get('/admin/root-agents'),
    api.get('/admin/users'),
  ]);
  users.value = r2.data;
  for (const a of r1.data) {
    const copies = await api.get(`/admin/agents/${a.id}/copies`);
    a.authorized_users = copies.data.map(c => users.value.find(u => u.id === c.owner_id)?.username || '?');
  }
  agents.value = r1.data;
}

function getUserName(uid) {
  return users.value.find(u => u.id === uid)?.username || uid?.substring(0, 8);
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

onMounted(load);
</script>

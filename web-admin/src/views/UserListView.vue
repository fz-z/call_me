<template>
  <div>
    <div class="page-header"><h2>用户管理</h2></div>
    <table>
      <thead><tr>
        <th>用户名</th><th>角色</th><th>拥有 Agent</th><th>注册时间</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.username }}</td>
          <td>{{ u.role === 'admin' ? '管理员' : '用户' }}</td>
          <td>
            <span v-for="a in u.agents" :key="a.id" class="tag">
              {{ a.alias }} <span class="revoke" @click="revoke(a, u.username)">✕</span>
            </span>
            <span v-if="!u.agents?.length" style="color:#888;font-size:12px">无</span>
          </td>
          <td style="color:#888;font-size:12px">{{ (u.created_at || '').substring(0, 10) }}</td>
          <td>
            <button class="btn-ghost" @click="$router.push(`/users/${u.username}`)">详情</button>
            <button v-if="u.role !== 'admin'" class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(u.username)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';

const users = ref([]);

async function load() {
  const [r1, r2] = await Promise.all([
    api.get('/admin/users'),
    api.get('/admin/agents'),
  ]);
  const allAgents = r2.data;
  users.value = r1.data.map(u => ({
    ...u,
    agents: allAgents.filter(a => a.owner_id === u.id),
  }));
}

async function revoke(agent, username) {
  if (!confirm(`Revoke ${agent.alias} from ${username}?`)) return;
  const rootId = agent.source_agent_id || agent.id;
  await api.delete(`/agents/${rootId}/grant/${username}`);
  await load();
}

async function del(username) {
  if (!confirm(`Delete user "${username}" and all their agents?`)) return;
  await api.delete(`/admin/users/${username}`);
  await load();
}

onMounted(load);
</script>

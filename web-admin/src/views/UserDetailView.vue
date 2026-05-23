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
            <button class="btn-ghost" style="color:#e74c3c" @click="revoke(a)">回收</button>
          </td>
        </tr>
        <tr v-if="!agents.length">
          <td colspan="4" style="color:#888;text-align:center;padding:24px">暂无 Agent</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import api from '../api.js';

const route = useRoute();
const username = route.params.username;
const agents = ref([]);

async function load() {
  const r = await api.get(`/admin/users/${username}/agents`);
  agents.value = r.data;
}

async function revoke(agent) {
  if (!confirm(`Revoke ${agent.alias}?`)) return;
  const rootId = agent.source_agent_id || agent.id;
  await api.delete(`/agents/${rootId}/grant/${username}`);
  await load();
}

onMounted(load);
</script>

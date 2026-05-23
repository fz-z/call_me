<template>
  <div>
    <router-link to="/agents" class="back-link">← 返回列表</router-link>
    <div class="page-header">
      <h2>{{ agent.alias }} 的授权详情</h2>
      <button class="btn btn-primary" @click="showGrant = true">+ 授权给新用户</button>
    </div>
    <p style="color:#888;font-size:13px;margin-bottom:16px">
      音色: {{ agent.voice_id }} | 人设: {{ agent.system_prompt }}
    </p>
    <table>
      <thead><tr>
        <th>授权用户</th><th>自定义人设</th><th>授权时间</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="c in copies" :key="c.id">
          <td>{{ getUserName(c.owner_id) }}</td>
          <td style="color:#888;max-width:300px">{{ c.system_prompt }}</td>
          <td style="color:#888;font-size:12px">{{ (c.created_at || '').substring(0, 10) }}</td>
          <td>
            <button class="btn-ghost" style="color:#e74c3c" @click="revoke(c.owner_id)">回收授权</button>
          </td>
        </tr>
        <tr v-if="!copies.length">
          <td colspan="4" style="color:#888;text-align:center;padding:24px">暂无授权</td>
        </tr>
      </tbody>
    </table>
    <GrantDialog v-if="showGrant" :agent="agent" @close="showGrant = false" @done="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import api from '../api.js';
import GrantDialog from '../components/GrantDialog.vue';

const route = useRoute();
const agent = ref({});
const copies = ref([]);
const users = ref([]);
const showGrant = ref(false);

async function load() {
  const id = route.params.id;
  const [r1, r2, r3] = await Promise.all([
    api.get(`/agents/${id}`),
    api.get(`/admin/agents/${id}/copies`),
    api.get('/admin/users'),
  ]);
  agent.value = r1.data;
  copies.value = r2.data;
  users.value = r3.data;
}

function getUserName(uid) {
  return users.value.find(u => u.id === uid)?.username || (uid || '').substring(0, 8);
}

async function revoke(ownerId) {
  if (!confirm('Revoke?')) return;
  const username = getUserName(ownerId);
  await api.delete(`/agents/${agent.value.id}/grant/${username}`);
  await load();
}

onMounted(load);
</script>

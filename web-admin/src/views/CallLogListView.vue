<template>
  <div>
    <div class="page-header">
      <h2>通话记录</h2>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      <select v-model="filters.status" @change="load" style="width:140px">
        <option value="">全部状态</option>
        <option value="running">进行中</option>
        <option value="completed">已完成</option>
      </select>
      <button v-if="filters.status || filters.agent_id" class="btn-ghost" @click="clearFilters">清除筛选</button>
    </div>
    <table>
      <thead><tr>
        <th>时间</th><th>主叫用户</th><th>Agent</th><th>时长</th><th>状态</th>
      </tr></thead>
      <tbody>
        <tr v-for="log in logs" :key="log.id">
          <td style="font-size:12px">{{ (log.started_at || '').substring(0, 19).replace('T', ' ') }}</td>
          <td>{{ log.caller_username }}</td>
          <td>{{ log.agent_alias }}</td>
          <td>{{ log.duration_seconds != null ? formatDuration(log.duration_seconds) : '-' }}</td>
          <td><span :style="{color: log.status === 'completed' ? '#4caf50' : '#ff9800'}">{{ log.status === 'completed' ? '已完成' : '进行中' }}</span></td>
        </tr>
        <tr v-if="!logs.length">
          <td colspan="5" style="color:#888;text-align:center;padding:24px">暂无通话记录</td>
        </tr>
      </tbody>
    </table>
    <div v-if="total > pageSize" style="display:flex;justify-content:center;gap:8px;margin-top:16px">
      <button class="btn-ghost" :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span style="color:#888;font-size:12px;line-height:32px">{{ page }} / {{ Math.ceil(total / pageSize) }}</span>
      <button class="btn-ghost" :disabled="page >= Math.ceil(total / pageSize)" @click="page++; load()">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';

const logs = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const filters = ref({ status: '', agent_id: '' });

function formatDuration(s) {
  if (s < 60) return `${s}秒`;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}分${sec}秒`;
}

function clearFilters() {
  filters.value.status = '';
  filters.value.agent_id = '';
  page.value = 1;
  load();
}

async function load() {
  const params = new URLSearchParams({ page: page.value, page_size: pageSize });
  if (filters.value.status) params.set('status', filters.value.status);
  if (filters.value.agent_id) params.set('agent_id', filters.value.agent_id);
  try {
    const r = await api.get(`/admin/call-logs?${params}`);
    logs.value = r.data.items;
    total.value = r.data.total;
  } catch (_) {}
}

onMounted(load);
</script>

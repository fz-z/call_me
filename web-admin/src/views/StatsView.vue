<template>
  <div>
    <div class="page-header">
      <h2>数据统计</h2>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px">
      <div class="stat-card">
        <div class="stat-value">{{ overview.total_calls }}</div>
        <div class="stat-label">总通话数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ overview.today_calls }}</div>
        <div class="stat-label">今日通话</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ formatHours(overview.total_duration_seconds) }}</div>
        <div class="stat-label">总时长 (小时)</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ overview.active_users }}</div>
        <div class="stat-label">活跃用户</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:2fr 1fr 1fr;gap:24px">
      <div class="chart-box">
        <h4 style="margin-bottom:12px;color:#888">通话趋势 (近30天)</h4>
        <canvas ref="trendCanvas"></canvas>
      </div>
      <div class="chart-box">
        <h4 style="margin-bottom:12px;color:#888">热门 Agent TOP 10</h4>
        <canvas ref="agentCanvas"></canvas>
      </div>
      <div class="chart-box">
        <h4 style="margin-bottom:12px;color:#888">活跃用户 TOP 10</h4>
        <canvas ref="userCanvas"></canvas>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { Chart, registerables } from 'chart.js';
import api from '../api.js';

Chart.register(...registerables);

const overview = ref({ total_calls: 0, today_calls: 0, total_duration_seconds: 0, active_users: 0 });
const trendCanvas = ref(null);
const agentCanvas = ref(null);
const userCanvas = ref(null);

function formatHours(s) {
  return (s / 3600).toFixed(1);
}

function destroyChart(canvasRef) {
  const instance = Chart.getChart(canvasRef.value);
  if (instance) instance.destroy();
}

function renderTrend(labels, data) {
  destroyChart(trendCanvas);
  new Chart(trendCanvas.value, {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: '通话数', data, borderColor: '#4a90d9', tension: 0.3, fill: false }],
    },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
  });
}

function renderBar(canvasRef, labels, data, color) {
  destroyChart(canvasRef);
  new Chart(canvasRef.value, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label: '通话数', data, backgroundColor: color }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true } },
    },
  });
}

onMounted(async () => {
  try {
    const r = await api.get('/admin/stats/overview');
    overview.value = r.data;
  } catch (_) {}

  try {
    const r = await api.get('/admin/stats/trend?days=30');
    renderTrend(r.data.map(d => d.date), r.data.map(d => d.count));
  } catch (_) {}

  try {
    const r = await api.get('/admin/stats/top-agents?limit=10');
    renderBar(agentCanvas, r.data.map(d => d.name), r.data.map(d => d.count), '#4a90d9');
  } catch (_) {}

  try {
    const r = await api.get('/admin/stats/top-users?limit=10');
    renderBar(userCanvas, r.data.map(d => d.name), r.data.map(d => d.count), '#4caf50');
  } catch (_) {}
});
</script>

<style scoped>
.stat-card {
  background: #1a1a2e;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
}
.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: #4a90d9;
}
.stat-label {
  font-size: 12px;
  color: #888;
  margin-top: 4px;
}
.chart-box {
  background: #1a1a2e;
  border-radius: 8px;
  padding: 16px;
}
</style>

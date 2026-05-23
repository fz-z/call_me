<template>
  <div>
    <router-link to="/agents" class="back-link">← 返回列表</router-link>
    <div class="page-header">
      <h2>{{ agent.alias }} 的授权详情</h2>
      <button class="btn btn-primary" @click="showGrant = true">+ 授权给新用户</button>
    </div>
    <div style="background:#1a1a2e;border-radius:8px;padding:16px;margin-bottom:16px">
      <h4 style="margin-bottom:12px">Pipeline 配置</h4>
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #222">
        <span style="color:#888">LLM</span>
        <span>{{ agent.model_config_id ? getConfigName(agent.model_config_id) : '系统默认 (.env)' }}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #222">
        <span style="color:#888">TTS</span>
        <span>{{ agent.tts_config_id ? getTtsConfigName(agent.tts_config_id) : '系统默认 (.env)' }}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:6px 0">
        <span style="color:#888">STT</span>
        <span style="color:#888">全局配置</span>
      </div>
      <div style="margin-top:8px;font-size:11px;color:#666">LLM 模型在"LLM模型"页面管理。人设可通过编辑修改。</div>
    </div>
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
const modelConfigs = ref([]);
const ttsConfigs = ref([]);
const showGrant = ref(false);

async function load() {
  const id = route.params.id;
  const [r1, r2, r3, r4, r5] = await Promise.all([
    api.get(`/agents/${id}`),
    api.get(`/admin/agents/${id}/copies`),
    api.get('/admin/users'),
    api.get('/admin/model-configs'),
    api.get('/admin/tts-configs'),
  ]);
  agent.value = r1.data;
  copies.value = r2.data;
  users.value = r3.data;
  modelConfigs.value = r4.data;
  ttsConfigs.value = r5.data;
}

function getConfigName(id) {
  const mc = modelConfigs.value.find(m => m.id === id);
  return mc ? `${mc.name} (${mc.provider}/${mc.model})` : id?.substring(0, 8);
}

function getTtsConfigName(id) {
  const tc = ttsConfigs.value.find(t => t.id === id);
  return tc ? `${tc.name} (${tc.provider}/${tc.model})` : id?.substring(0, 8);
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

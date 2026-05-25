<template>
  <div>
    <router-link to="/agents" class="back-link">← 返回列表</router-link>
    <div class="page-header">
      <h2>{{ agent.alias }} 的授权详情</h2>
      <button class="btn btn-primary" @click="showGrant = true">+ 授权给新用户</button>
    </div>
    <div style="background:#1a1a2e;border-radius:8px;padding:16px;margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <h4 style="margin:0">Pipeline 配置</h4>
        <button class="btn-ghost" @click="startEditPipeline">编辑配置</button>
      </div>
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #222">
        <span style="color:#888">音色</span>
        <span style="color:#4a90d9">{{ getVoiceName(agent.voice_pool_id) }}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #222">
        <span style="color:#888">LLM</span>
        <span>{{ agent.model_config_id ? getConfigName(agent.model_config_id) : '系统默认' }}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #222">
        <span style="color:#888">TTS</span>
        <span>{{ agent.tts_config_id ? getTtsConfigName(agent.tts_config_id) : '系统默认' }}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:6px 0">
        <span style="color:#888">STT</span>
        <span style="color:#888">全局配置</span>
      </div>
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
            <button class="btn-ghost" @click="startEditCopy(c)">编辑人设</button>
            <button class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="revoke(c.owner_id)">回收授权</button>
          </td>
        </tr>
        <tr v-if="!copies.length">
          <td colspan="4" style="color:#888;text-align:center;padding:24px">暂无授权</td>
        </tr>
      </tbody>
    </table>
    <GrantDialog v-if="showGrant" :agent="agent" @close="showGrant = false" @done="load" />

    <!-- Edit Pipeline config -->
    <div v-if="showPipelineEdit" class="modal-overlay" @click.self="showPipelineEdit = false">
      <form class="modal" @submit.prevent="savePipeline" style="min-width:420px">
        <h3>编辑 Pipeline 配置</h3>
        <label style="display:block;margin:12px 0 4px;color:#888;font-size:13px">音色</label>
        <select v-model="pipelineForm.voice_pool_id" @change="onVoiceChange">
          <option value="">选择音色...</option>
          <option v-for="v in voices" :key="v.id" :value="v.id">{{ v.name }} ({{ v.type === 'builtin' ? '内置' : '克隆' }})</option>
        </select>
        <label style="display:block;margin:12px 0 4px;color:#888;font-size:13px">TTS 模型 <span style="font-size:11px;color:#888">（自动匹配音色关联的模型）</span></label>
        <select v-model="pipelineForm.tts_config_id">
          <option value="">系统默认</option>
          <option v-for="t in voiceTtsOptions" :key="t.id" :value="t.id">{{ t.name }} ({{ t.provider }}/{{ t.model }})</option>
        </select>
        <label style="display:block;margin:12px 0 4px;color:#888;font-size:13px">LLM 模型</label>
        <select v-model="pipelineForm.model_config_id">
          <option value="">系统默认</option>
          <option v-for="m in modelConfigs" :key="m.id" :value="m.id">{{ m.name }} ({{ m.provider }}/{{ m.model }})</option>
        </select>
        <p v-if="pipelineEditError" class="error">{{ pipelineEditError }}</p>
        <div class="modal-actions" style="margin-top:16px">
          <button type="button" class="btn-ghost" @click="showPipelineEdit = false">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="pipelineEditLoading">保存</button>
        </div>
      </form>
    </div>

    <!-- Edit copy system prompt -->
    <div v-if="editingCopy" class="modal-overlay" @click.self="editingCopy = null">
      <form class="modal" @submit.prevent="saveEditCopy" style="min-width:400px">
        <h3>编辑 {{ getUserName(editingCopy.owner_id) }} 的人设</h3>
        <textarea v-model="editPromptText" rows="6" style="width:100%;background:#111;color:#ddd;border:1px solid #333;border-radius:6px;padding:10px;font-size:14px" placeholder="输入新的 system prompt"></textarea>
        <p v-if="editPromptError" class="error">{{ editPromptError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="editingCopy = null">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="editPromptLoading">保存</button>
        </div>
      </form>
    </div>
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
const editingCopy = ref(null);
const editPromptText = ref('');
const editPromptLoading = ref(false);
const editPromptError = ref('');
const voices = ref([]);
const voiceTtsMap = ref({});  // voice_id → [tts_configs]
const voiceTtsOptions = ref([]);
const showPipelineEdit = ref(false);
const pipelineForm = ref({ voice_pool_id: null, model_config_id: null, tts_config_id: null });
const pipelineEditLoading = ref(false);
const pipelineEditError = ref('');

async function load() {
  const id = route.params.id;
  const [r1, r2, r3, r4, r5] = await Promise.all([
    api.get(`/agents/${id}`),
    api.get(`/admin/agents/${id}/copies`),
    api.get('/admin/users'),
    api.get('/admin/model-configs'),
    api.get('/admin/tts-configs'),
    api.get('/admin/voices'),
  ]);
  agent.value = r1.data;
  copies.value = r2.data;
  users.value = r3.data;
  modelConfigs.value = r4.data;
  ttsConfigs.value = r5.data;
  voices.value = r6.data;

  // Load voice → TTS mappings
  for (const v of voices.value) {
    try {
      const ttsRes = await api.get(`/admin/voices/${v.id}/tts-configs`);
      if (ttsRes.data.length > 0) {
        voiceTtsMap.value[v.id] = ttsRes.data;
      }
    } catch (_) {}
  }
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

function getVoiceName(id) {
  if (!id) return '系统默认';
  const v = voices.value.find(x => x.id === id);
  return v ? `${v.name} (${v.voice_id?.substring(0, 20)}...)` : id.substring(0, 8);
}

function onVoiceChange() {
  const ttsConfigs = voiceTtsMap.value[pipelineForm.value.voice_pool_id] || [];
  voiceTtsOptions.value = ttsConfigs;
  // Auto-select first linked TTS
  pipelineForm.value.tts_config_id = ttsConfigs.length > 0 ? ttsConfigs[0].id : '';
}

function startEditPipeline() {
  pipelineForm.value = {
    voice_pool_id: agent.value.voice_pool_id || '',
    model_config_id: agent.value.model_config_id || '',
    tts_config_id: agent.value.tts_config_id || '',
  };
  // Pre-populate TTS options for current voice
  const ttsConfigs = voiceTtsMap.value[agent.value.voice_pool_id] || [];
  voiceTtsOptions.value = ttsConfigs;
  pipelineEditError.value = '';
  showPipelineEdit.value = true;
}

async function savePipeline() {
  pipelineEditLoading.value = true; pipelineEditError.value = '';
  try {
    await api.patch(`/agents/${agent.value.id}`, {
      voice_pool_id: pipelineForm.value.voice_pool_id || '',
      model_config_id: pipelineForm.value.model_config_id || '',
      tts_config_id: pipelineForm.value.tts_config_id || '',
    });
    showPipelineEdit.value = false;
    await load();
  } catch (e) {
    pipelineEditError.value = e.response?.data?.detail || 'Update failed';
  } finally { pipelineEditLoading.value = false; }
}

function startEditCopy(c) {
  editingCopy.value = c;
  editPromptText.value = c.system_prompt || '';
  editPromptError.value = '';
}

async function saveEditCopy() {
  if (!editPromptText.value.trim()) return;
  editPromptLoading.value = true; editPromptError.value = '';
  try {
    await api.patch(`/agents/${editingCopy.value.id}`, { system_prompt: editPromptText.value.trim() });
    editingCopy.value = null;
    await load();
  } catch (e) {
    editPromptError.value = e.response?.data?.detail || 'Update failed';
  } finally { editPromptLoading.value = false; }
}

async function revoke(ownerId) {
  if (!confirm('Revoke?')) return;
  const username = getUserName(ownerId);
  await api.delete(`/agents/${agent.value.id}/grant/${username}`);
  await load();
}

onMounted(load);
</script>

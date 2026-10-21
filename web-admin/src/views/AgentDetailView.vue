<template>
  <div>
    <router-link to="/agents" class="back-link">← 返回列表</router-link>
    <div class="page-header">
      <img v-if="agent.photo_url" :src="agent.photo_url" class="avatar" />
      <div v-else class="avatar avatar-empty">无</div>
      <h2>{{ agent.alias }} 的授权详情</h2>
      <div class="header-actions">
        <label class="btn-ghost upload-link">{{ photoUploading ? '上传中…' : (agent.photo_url ? '更换头像' : '上传头像') }}<input type="file" accept="image/*" @change="uploadAgentPhoto" :disabled="photoUploading" /></label>
        <button v-if="agent.photo_url" class="btn-ghost danger" @click="removeAgentPhoto">移除头像</button>
        <button class="btn btn-primary" @click="showGrant = true">+ 授权给新用户</button>
      </div>
    </div>
    <p v-if="photoError" class="error">{{ photoError }}</p>
    <div class="runtime-card">
      <div class="runtime-title"><h4>{{ runtimeDisplayName(agent.runtime_mode) }} 配置</h4><button class="btn-ghost" @click="showRuntimeEdit = true">编辑配置</button></div>
      <div class="line"><span>运行模式</span><strong><span class="tag" :class="agent.runtime_mode === 'realtime' ? 'tag-realtime' : 'tag-classic'">{{ runtimeDisplayName(agent.runtime_mode) }}</span></strong></div>
      <div class="line"><span>音色</span><strong class="accent">{{ getVoiceName(agent.voice_pool_id) }}</strong></div>
      <template v-if="agent.runtime_mode === 'realtime'"><div class="line"><span>提供商 / 模型</span><strong>{{ getRealtimeConfigName(agent.realtime_config_id) }}</strong></div><p class="hint">此 Agent 只会使用上方实时模型与音色的精确绑定；配置缺失时通话会直接报错，不会降级为 Pipeline。</p></template>
      <template v-else><div class="line"><span>LLM</span><strong>{{ agent.model_config_id ? getModelConfigName(agent.model_config_id) : '系统默认' }}</strong></div><div class="line"><span>TTS</span><strong>{{ agent.tts_config_id ? getTtsConfigName(agent.tts_config_id) : '系统默认' }}</strong></div><div class="line"><span>STT</span><strong class="muted">全局配置</strong></div></template>
      <div class="speech-rate-row">
        <span>语速</span>
        <input v-model.number="speechRate" type="range" min="0.5" max="2" step="0.1" @change="saveSpeechRate" />
        <strong>{{ speechRate.toFixed(1) }}x</strong>
        <span v-if="speechRateSaving" class="muted">保存中…</span>
        <span v-if="speechRateError" class="error">{{ speechRateError }}</span>
      </div>
      <div class="speech-rate-row">
        <span>打断</span>
        <label class="interrupt-toggle"><input v-model="allowInterruptions" type="checkbox" @change="saveAllowInterruptions" /> 允许用户在 Agent 说话时打断</label>
        <span v-if="interruptionsSaving" class="muted">保存中…</span>
        <span v-if="interruptionsError" class="error">{{ interruptionsError }}</span>
      </div>
    </div>

    <table><thead><tr><th>授权用户</th><th>自定义人设</th><th>授权时间</th><th>操作</th></tr></thead><tbody><tr v-for="copy in copies" :key="copy.id"><td>{{ getUserName(copy.owner_id) }}</td><td class="prompt">{{ copy.system_prompt }}</td><td class="muted">{{ (copy.created_at || '').substring(0, 10) }}</td><td><button class="btn-ghost" @click="startEditCopy(copy)">编辑人设</button><button class="btn-ghost danger" @click="revoke(copy.owner_id)">回收授权</button></td></tr><tr v-if="!copies.length"><td colspan="4" class="empty">暂无授权</td></tr></tbody></table>

    <GrantDialog v-if="showGrant" :agent="agent" @close="showGrant = false" @done="load" />
    <AgentForm v-if="showRuntimeEdit" :edit-id="agent.id" :edit-alias="agent.alias" :edit-prompt="agent.system_prompt" :edit-model-config-id="agent.model_config_id" :edit-tts-config-id="agent.tts_config_id" :edit-voice-pool-id="agent.voice_pool_id" :edit-realtime-config-id="agent.realtime_config_id" :edit-runtime-mode="agent.runtime_mode" :edit-photo-url="agent.photo_url" :edit-speech-rate="agent.speech_rate" :edit-allow-interruptions="agent.allow_interruptions" @close="showRuntimeEdit = false" @saved="load" />
    <div v-if="editingCopy" class="modal-overlay" @click.self="editingCopy = null"><form class="modal" @submit.prevent="saveCopy"><h3>编辑 {{ getUserName(editingCopy.owner_id) }} 的 Agent</h3><input v-model="copyForm.alias" placeholder="Agent 名字" required /><textarea v-model="copyForm.system_prompt" rows="6" placeholder="输入新的 system prompt"></textarea><p v-if="copyError" class="error">{{ copyError }}</p><div class="modal-actions"><button type="button" class="btn-ghost" @click="editingCopy = null">取消</button><button class="btn btn-primary" :disabled="copySaving">保存</button></div></form></div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import api from '../api.js';
import AgentForm from '../components/AgentForm.vue';
import GrantDialog from '../components/GrantDialog.vue';
import { runtimeDisplayName } from '../utils/agentRuntimeForm.js';

const route = useRoute(); const agent = ref({}); const copies = ref([]); const users = ref([]); const voices = ref([]); const modelConfigs = ref([]); const ttsConfigs = ref([]); const realtimeConfigs = ref([]); const showGrant = ref(false); const showRuntimeEdit = ref(false); const editingCopy = ref(null); const copyForm = reactive({ alias: '', system_prompt: '' }); const copySaving = ref(false); const copyError = ref(''); const speechRate = ref(1.0); const speechRateSaving = ref(false); const speechRateError = ref(''); const allowInterruptions = ref(true); const interruptionsSaving = ref(false); const interruptionsError = ref(''); const photoUploading = ref(false); const photoError = ref('');
async function load() { const id = route.params.id; const [agentResult, copyResult, userResult, modelResult, ttsResult, voiceResult, realtimeResult] = await Promise.all([api.get(`/agents/${id}`), api.get(`/admin/agents/${id}/copies`), api.get('/admin/users'), api.get('/admin/model-configs'), api.get('/admin/tts-configs'), api.get('/admin/voices'), api.get('/admin/realtime-configs')]); agent.value = agentResult.data; speechRate.value = Number(agent.value.speech_rate || 1.0); allowInterruptions.value = agent.value.allow_interruptions !== false; copies.value = copyResult.data; users.value = userResult.data; modelConfigs.value = modelResult.data; ttsConfigs.value = ttsResult.data; voices.value = voiceResult.data; realtimeConfigs.value = realtimeResult.data; }
async function saveSpeechRate() { speechRateSaving.value = true; speechRateError.value = ''; try { const result = await api.patch(`/agents/${agent.value.id}`, { speech_rate: Number(speechRate.value) }); agent.value = result.data; speechRate.value = Number(result.data.speech_rate || 1.0); } catch (error) { speechRateError.value = error.response?.data?.detail || '保存语速失败'; } finally { speechRateSaving.value = false; } }
async function saveAllowInterruptions() { interruptionsSaving.value = true; interruptionsError.value = ''; try { const result = await api.patch(`/agents/${agent.value.id}`, { allow_interruptions: Boolean(allowInterruptions.value) }); agent.value = result.data; allowInterruptions.value = result.data.allow_interruptions !== false; } catch (error) { interruptionsError.value = error.response?.data?.detail || '保存打断设置失败'; } finally { interruptionsSaving.value = false; } }
async function uploadAgentPhoto(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  photoUploading.value = true;
  photoError.value = '';
  try {
    const data = new FormData();
    data.append('file', file);
    const upload = await api.post('/admin/upload', data);
    if (!upload.data.ok) {
      photoError.value = upload.data.error || '头像上传失败';
      return;
    }
    await api.patch(`/agents/${agent.value.id}`, { photo_url: upload.data.url });
    await load();
  } catch (error) {
    photoError.value = error.response?.data?.detail || '头像上传失败';
  } finally {
    photoUploading.value = false;
    event.target.value = '';
  }
}
async function removeAgentPhoto() {
  photoUploading.value = true;
  photoError.value = '';
  try {
    await api.patch(`/agents/${agent.value.id}`, { photo_url: '' });
    await load();
  } catch (error) {
    photoError.value = error.response?.data?.detail || '移除头像失败';
  } finally {
    photoUploading.value = false;
  }
}
function getVoiceName(id) { return voices.value.find((voice) => voice.id === id)?.name || (id ? id.substring(0, 8) : '未配置'); }
function getUserName(id) { return users.value.find((user) => user.id === id)?.username || (id || '').substring(0, 8); }
function getModelConfigName(id) { const config = modelConfigs.value.find((item) => item.id === id); return config ? `${config.name} (${config.provider}/${config.model})` : id?.substring(0, 8); }
function getTtsConfigName(id) { const config = ttsConfigs.value.find((item) => item.id === id); return config ? `${config.name} (${config.provider}/${config.model})` : id?.substring(0, 8); }
function getRealtimeConfigName(id) { const config = realtimeConfigs.value.find((item) => item.id === id); return config ? `${config.name} (${config.provider}/${config.model})` : id?.substring(0, 8); }
function startEditCopy(copy) { editingCopy.value = copy; copyForm.alias = copy.alias || ''; copyForm.system_prompt = copy.system_prompt || ''; copyError.value = ''; }
async function saveCopy() { if (!copyForm.alias.trim()) return; copySaving.value = true; copyError.value = ''; try { await api.patch(`/agents/${editingCopy.value.id}`, { alias: copyForm.alias.trim(), system_prompt: copyForm.system_prompt }); editingCopy.value = null; await load(); } catch (error) { copyError.value = error.response?.data?.detail || '保存失败'; } finally { copySaving.value = false; } }
async function revoke(ownerId) { if (!confirm('回收该用户的授权吗？')) return; try { await api.delete(`/agents/${agent.value.id}/grant/${getUserName(ownerId)}`); await load(); } catch (error) { alert(error.response?.data?.detail || '回收授权失败'); } }
onMounted(load);
</script>

<style scoped>
.avatar { width:48px; height:48px; border-radius:50%; object-fit:cover; border:2px solid #4a90d9; margin-right:12px; }.avatar-empty { display:flex; align-items:center; justify-content:center; color:#666; font-size:10px; background:#111; border-style:dashed; }.header-actions { display:flex; align-items:center; gap:8px; margin-left:auto; }.upload-link { cursor:pointer; }.upload-link input { display:none; }.runtime-card { background:#1a1a2e; border-radius:8px; padding:16px; margin-bottom:16px; }.runtime-title,.line { display:flex; justify-content:space-between; align-items:center; }.runtime-title { margin-bottom:10px; }.runtime-title h4 { margin:0; }.line { padding:7px 0; border-bottom:1px solid #222; }.line span:first-child { color:#888; }.accent { color:#4a90d9; }.tag-classic { background:#1a3a5c; }.tag-realtime { background:#3d2d00; }.hint,.muted,.prompt { color:#888; font-size:12px; }.hint { margin:10px 0 0; line-height:1.5; }.prompt { max-width:300px; }.danger { color:#e74c3c; margin-left:4px; }.empty { color:#888; text-align:center; padding:24px; } input,textarea { width:100%; box-sizing:border-box; margin-bottom:10px; } .speech-rate-row { display:flex; align-items:center; gap:12px; padding-top:12px; } .speech-rate-row span:first-child { color:#888; white-space:nowrap; } .speech-rate-row input[type=range] { flex:1; margin:0; } .speech-rate-row strong { color:#4a90d9; white-space:nowrap; } .speech-rate-row .error { margin:0; } .interrupt-toggle { display:flex; align-items:center; gap:6px; color:#bbb; font-size:13px; } .interrupt-toggle input { width:auto; margin:0; }
</style>

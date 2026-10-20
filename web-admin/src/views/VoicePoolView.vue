<template>
  <div>
    <div class="page-header">
      <h2>声音库</h2>
      <button class="btn btn-primary" @click="showUpload = true">+ 上传音频生成经典音色</button>
    </div>
    <p class="hint">声音库只展示内部音色池名称；提供商音色 ID 仅由服务端运行时使用。</p>
    <table>
      <thead><tr>
        <th>名称</th><th>类型</th><th>经典 TTS 绑定</th><th>端到端实时绑定</th><th>使用此音色的 Agent</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="voice in voices" :key="voice.id">
          <td>{{ voice.name }}</td>
          <td><span class="tag" :style="voice.type === 'builtin' ? '' : 'background:#3d2d00'">{{ voice.type === 'builtin' ? '内置' : '克隆' }}</span></td>
          <td>
            <span v-for="config in voice._ttsConfigs" :key="config.id" class="tag tag-classic">{{ config.name }}</span>
            <span v-if="!voice._ttsConfigs.length" class="muted">未绑定</span>
          </td>
          <td>
            <span v-for="binding in voice._runtimeBindings" :key="binding.id" class="tag tag-realtime">{{ binding.runtime_config_name }}</span>
            <span v-if="!voice._runtimeBindings.length" class="muted">未克隆</span>
          </td>
          <td>
            <span v-for="agent in voice._agents" :key="agent.id" class="tag">{{ agent.alias }}</span>
            <span v-if="!voice._agents.length" class="muted">暂无</span>
          </td>
          <td>
            <button class="btn-ghost" :disabled="!voice._ttsConfigs.length" @click="openAudition(voice)">试听</button>
            <button class="btn-ghost" @click="startEdit(voice)">管理绑定</button>
            <button class="btn-ghost danger" @click="del(voice)">删除</button>
          </td>
        </tr>
        <tr v-if="!voices.length"><td colspan="6" class="empty">暂无声音</td></tr>
      </tbody>
    </table>

    <div v-if="showUpload" class="modal-overlay" @click.self="showUpload = false">
      <form class="modal" @submit.prevent="upload" style="min-width:390px">
        <h3>生成经典 Pipeline 音色</h3>
        <input v-model="voiceName" placeholder="音色名称" required />
        <select v-model="selectedTtsConfigId" required>
          <option value="">-- 选择 TTS 模型 --</option>
          <option v-for="config in cloneableTtsConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option>
        </select>
        <input type="file" accept="audio/*" @change="(event) => uploadAudioFile = event.target.files[0]" required />
        <p class="hint">上传 30 秒至 5 分钟的 wav、mp3 或 m4a 音频。端到端实时模型需要在创建后单独克隆绑定。</p>
        <p v-if="uploadError" class="error">{{ uploadError }}</p>
        <div class="modal-actions"><button type="button" class="btn-ghost" @click="showUpload = false">取消</button><button class="btn btn-primary" :disabled="uploading">{{ uploading ? '上传中…' : '上传' }}</button></div>
      </form>
    </div>

    <div v-if="showEdit" class="modal-overlay" @click.self="showEdit = false">
      <form class="modal" @submit.prevent="saveEdit" style="min-width:480px">
        <h3>管理音色绑定</h3>
        <input v-model="editForm.name" placeholder="音色名称" required />
        <textarea v-model="editForm.audition_text" rows="3" placeholder="经典 TTS 试听文本（可选）"></textarea>

        <h4>经典 TTS 绑定</h4>
        <div v-for="config in editForm.ttsConfigs" :key="config.id" class="binding-row"><span class="tag tag-classic">{{ config.name }} ({{ config.model }})</span><button type="button" class="btn-ghost danger" @click="removeTtsLink(config.id)">移除</button></div>
        <div class="binding-row"><select v-model="editForm.addTtsId"><option value="">-- 添加 TTS 模型 --</option><option v-for="config in availableTtsConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option></select><button type="button" class="btn-ghost" :disabled="!editForm.addTtsId" @click="addTtsLink">添加</button></div>

        <h4>端到端实时绑定</h4>
        <div v-for="binding in editForm.runtimeBindings" :key="binding.id" class="binding-row"><span class="tag tag-realtime">{{ binding.runtime_config_name }} ({{ binding.runtime_config_model }})</span></div>
        <p v-if="!realtimeConfigs.length" class="muted">请先在“实时模型”创建支持 voice_clone 的配置。</p>
        <select v-model="editForm.realtimeConfigId"><option value="">-- 选择要克隆到的实时模型 --</option><option v-for="config in cloneableRealtimeConfigs" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option></select>
        <input type="file" accept="audio/*" @change="(event) => editForm.realtimeAudioFile = event.target.files[0]" />
        <label class="consent"><input v-model="editForm.authorizationConfirmed" type="checkbox" /> 我确认有权使用这段参考音频进行该模型的音色复刻。</label>
        <button type="button" class="btn btn-primary" :disabled="bindingLoading || !canCreateRealtimeBinding" @click="createRealtimeBinding">{{ bindingLoading ? '克隆中…' : '创建/更新实时绑定' }}</button>
        <p class="hint">实时模型的音色与模型配置一一对应；不会复用经典 TTS 的提供商音色 ID。</p>

        <p v-if="editError" class="error">{{ editError }}</p>
        <div class="modal-actions"><button type="button" class="btn-ghost" @click="showEdit = false">取消</button><button class="btn btn-primary" :disabled="editLoading">保存名称与试听文本</button></div>
      </form>
    </div>

    <div v-if="showAudition" class="modal-overlay" @click.self="closeAudition">
      <div class="modal" style="min-width:420px">
        <h3>试听 - {{ auditionVoice?.name }}</h3>
        <select v-model="auditionTtsConfigId"><option v-for="config in auditionVoice?._ttsConfigs || []" :key="config.id" :value="config.id">{{ config.name }} ({{ config.model }})</option></select>
        <textarea v-model="auditionText" rows="4" placeholder="输入试听文本…"></textarea>
        <p class="hint">试听只支持明确选择的经典 TTS 绑定；端到端实时模型暂不提供离线试听。</p>
        <div class="modal-actions"><button v-if="!auditionPlaying" class="btn btn-primary" :disabled="auditionLoading || !auditionText.trim() || !auditionTtsConfigId" @click="startAudition">{{ auditionLoading ? '合成中…' : '试听' }}</button><button v-else class="btn btn-primary" @click="stopAudition">停止</button><button class="btn-ghost" @click="closeAudition">关闭</button></div>
        <p v-if="auditionError" class="error">{{ auditionError }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import api from '../api.js';

const voices = ref([]); const ttsConfigs = ref([]); const realtimeConfigs = ref([]);
const showUpload = ref(false); const voiceName = ref(''); const selectedTtsConfigId = ref(''); const uploadAudioFile = ref(null); const uploading = ref(false); const uploadError = ref('');
const showEdit = ref(false); const editLoading = ref(false); const bindingLoading = ref(false); const editError = ref('');
const editForm = reactive({ id: '', name: '', audition_text: '', ttsConfigs: [], runtimeBindings: [], addTtsId: '', realtimeConfigId: '', realtimeAudioFile: null, authorizationConfirmed: false });
const showAudition = ref(false); const auditionVoice = ref(null); const auditionTtsConfigId = ref(''); const auditionText = ref(''); const auditionLoading = ref(false); const auditionPlaying = ref(false); const auditionError = ref('');
let auditionAudio = null;

const cloneableTtsConfigs = computed(() => ttsConfigs.value.filter((config) => config.supports_voice_clone !== false));
const cloneableRealtimeConfigs = computed(() => realtimeConfigs.value.filter((config) => supportsVoiceClone(config)));
const availableTtsConfigs = computed(() => ttsConfigs.value.filter((config) => !editForm.ttsConfigs.some((linked) => linked.id === config.id)));
const canCreateRealtimeBinding = computed(() => editForm.realtimeConfigId && editForm.realtimeAudioFile && editForm.authorizationConfirmed);

function supportsVoiceClone(config) { try { return JSON.parse(config.capabilities_json || '{}').voice_clone === true; } catch (_) { return false; } }

async function load() {
  const [voiceResult, agentResult, ttsResult, realtimeResult] = await Promise.all([api.get('/admin/voices'), api.get('/admin/agents'), api.get('/admin/tts-configs'), api.get('/admin/realtime-configs')]);
  ttsConfigs.value = ttsResult.data; realtimeConfigs.value = realtimeResult.data;
  voices.value = await Promise.all(voiceResult.data.map(async (voice) => {
    const [tts, runtime] = await Promise.allSettled([api.get(`/admin/voices/${voice.id}/tts-configs`), api.get(`/admin/voices/${voice.id}/runtime-bindings`)]);
    return { ...voice, _agents: agentResult.data.filter((agent) => agent.voice_pool_id === voice.id && !agent.source_agent_id), _ttsConfigs: tts.status === 'fulfilled' ? tts.value.data : [], _runtimeBindings: runtime.status === 'fulfilled' ? runtime.value.data : [] };
  }));
}

async function upload() { if (!voiceName.value.trim() || !selectedTtsConfigId.value || !uploadAudioFile.value) return; uploading.value = true; uploadError.value = ''; try { const data = new FormData(); data.append('name', voiceName.value.trim()); data.append('tts_config_id', selectedTtsConfigId.value); data.append('audio_file', uploadAudioFile.value); await api.post('/admin/voices', data); showUpload.value = false; voiceName.value = ''; selectedTtsConfigId.value = ''; uploadAudioFile.value = null; await load(); } catch (error) { uploadError.value = error.response?.data?.detail || '上传失败'; } finally { uploading.value = false; } }

async function startEdit(voice) { editForm.id = voice.id; editForm.name = voice.name; editForm.audition_text = voice.audition_text || ''; editForm.ttsConfigs = [...voice._ttsConfigs]; editForm.runtimeBindings = [...voice._runtimeBindings]; editForm.addTtsId = ''; editForm.realtimeConfigId = ''; editForm.realtimeAudioFile = null; editForm.authorizationConfirmed = false; editError.value = ''; showEdit.value = true; }
async function saveEdit() { if (!editForm.name.trim()) return; editLoading.value = true; editError.value = ''; try { await api.patch(`/admin/voices/${editForm.id}`, { name: editForm.name.trim(), audition_text: editForm.audition_text || '' }); showEdit.value = false; await load(); } catch (error) { editError.value = error.response?.data?.detail || '保存失败'; } finally { editLoading.value = false; } }
async function addTtsLink() { try { await api.post(`/admin/voices/${editForm.id}/tts-configs`, { tts_config_id: editForm.addTtsId }); editForm.ttsConfigs = (await api.get(`/admin/voices/${editForm.id}/tts-configs`)).data; editForm.addTtsId = ''; } catch (error) { editError.value = error.response?.data?.detail || '添加绑定失败'; } }
async function removeTtsLink(id) { try { await api.delete(`/admin/voices/${editForm.id}/tts-configs/${id}`); editForm.ttsConfigs = (await api.get(`/admin/voices/${editForm.id}/tts-configs`)).data; } catch (error) { editError.value = error.response?.data?.detail || '移除绑定失败'; } }
async function createRealtimeBinding() { bindingLoading.value = true; editError.value = ''; try { const data = new FormData(); data.append('realtime_config_id', editForm.realtimeConfigId); data.append('audio_file', editForm.realtimeAudioFile); data.append('authorization_confirmed', String(editForm.authorizationConfirmed)); await api.post(`/admin/voices/${editForm.id}/realtime-bindings`, data); editForm.runtimeBindings = (await api.get(`/admin/voices/${editForm.id}/runtime-bindings`)).data; editForm.realtimeAudioFile = null; editForm.authorizationConfirmed = false; } catch (error) { editError.value = error.response?.data?.detail || '实时音色克隆失败'; } finally { bindingLoading.value = false; } }
async function del(voice) { if (!confirm(`删除“${voice.name}”吗？`)) return; try { await api.delete(`/admin/voices/${voice.id}`); await load(); } catch (error) { alert(error.response?.data?.detail || '删除失败'); } }
function openAudition(voice) { auditionVoice.value = voice; auditionTtsConfigId.value = voice._ttsConfigs[0]?.id || ''; auditionText.value = voice.audition_text || '你好，这是一段语音试听文本，用于测试音色效果。'; auditionError.value = ''; showAudition.value = true; }
function closeAudition() { stopAudition(); showAudition.value = false; auditionVoice.value = null; }
async function startAudition() { auditionLoading.value = true; auditionError.value = ''; try { const result = await api.post(`/admin/voices/${auditionVoice.value.id}/audition`, { text: auditionText.value.trim(), tts_config_id: auditionTtsConfigId.value }); const bytes = Uint8Array.from(atob(result.data.audio_base64), (char) => char.charCodeAt(0)); auditionAudio = new Audio(URL.createObjectURL(new Blob([bytes], { type: result.data.mime_type }))); auditionAudio.onended = () => { auditionPlaying.value = false; }; auditionAudio.onerror = () => { auditionPlaying.value = false; auditionError.value = '播放失败'; }; auditionPlaying.value = true; await auditionAudio.play(); } catch (error) { auditionError.value = error.response?.data?.detail || '试听失败'; } finally { auditionLoading.value = false; } }
function stopAudition() { if (auditionAudio) { auditionAudio.pause(); auditionAudio.currentTime = 0; auditionAudio = null; } auditionPlaying.value = false; }
onMounted(load);
</script>

<style scoped>
.hint,.muted { color:#888; font-size:12px; }.hint { margin:0 0 12px; line-height:1.5; }.empty { color:#888; text-align:center; padding:24px; }.danger { color:#e74c3c; margin-left:4px; }.tag-classic { background:#1a3a5c; }.tag-realtime { background:#3d2d00; }.binding-row { display:flex; gap:8px; align-items:center; margin:6px 0; }.binding-row select { flex:1; }.consent { display:block; color:#bbb; font-size:12px; margin:10px 0; } h4 { margin:18px 0 8px; font-size:14px; } select,textarea,input[type=file] { width:100%; box-sizing:border-box; margin-bottom:10px; }
</style>

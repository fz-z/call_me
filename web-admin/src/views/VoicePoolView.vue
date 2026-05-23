<template>
  <div>
    <div class="page-header">
      <h2>声音库</h2>
      <button class="btn btn-primary" @click="showUpload = true">+ 上传音频生成音色</button>
    </div>
    <table>
      <thead><tr>
        <th>名称</th><th>voice_id</th><th>类型</th><th>使用此音色的 Agent</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="v in voices" :key="v.id">
          <td>{{ v.name }}</td>
          <td style="color:#4a90d9;font-size:11px">{{ v.voice_id?.substring(0, 30) }}{{ v.voice_id?.length > 30 ? '...' : '' }}</td>
          <td><span class="tag" :style="v.type==='builtin'?'':'background:#3d2d00'">{{ v.type === 'builtin' ? '内置' : '克隆' }}</span></td>
          <td>
            <span v-for="a in v._agents" :key="a.id" class="tag">{{ a.alias }}</span>
            <span v-if="!v._agents?.length" style="color:#888;font-size:12px">暂无</span>
          </td>
          <td>
            <button v-if="v.type !== 'builtin'" class="btn-ghost" style="color:#e74c3c" @click="del(v)">删除</button>
            <span v-else style="color:#888;font-size:12px">-</span>
          </td>
        </tr>
        <tr v-if="!voices.length">
          <td colspan="5" style="color:#888;text-align:center;padding:24px">暂无声音</td>
        </tr>
      </tbody>
    </table>

    <!-- Upload Modal -->
    <div v-if="showUpload" class="modal-overlay" @click.self="showUpload = false">
      <form class="modal" @submit.prevent="upload" style="min-width:380px">
        <h3>上传音频生成音色</h3>
        <input v-model="voiceName" placeholder="音色名称" required />
        <input type="file" accept="audio/*" @change="onFile" required style="margin-bottom:12px" />
        <p style="font-size:11px;color:#888;margin-bottom:12px">上传 30s~5min 的 wav/mp3/m4a 音频</p>
        <p v-if="uploadError" class="error">{{ uploadError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="showUpload = false">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="uploading">上传</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';

const voices = ref([]);
const showUpload = ref(false);
const voiceName = ref('');
const audioFile = ref(null);
const uploading = ref(false);
const uploadError = ref('');

async function load() {
  const [r1, r2] = await Promise.all([
    api.get('/admin/voices'),
    api.get('/admin/agents'),
  ]);
  const allAgents = r2.data;
  voices.value = r1.data.map(v => ({
    ...v,
    _agents: allAgents.filter(a => a.voice_pool_id === v.id),
  }));
}

function onFile(e) { audioFile.value = e.target.files[0]; }

async function upload() {
  if (!audioFile.value || !voiceName.value.trim()) return;
  uploading.value = true; uploadError.value = '';
  try {
    const fd = new FormData();
    fd.append('name', voiceName.value.trim());
    fd.append('audio_file', audioFile.value);
    await api.post('/admin/voices', fd);
    showUpload.value = false;
    voiceName.value = '';
    audioFile.value = null;
    await load();
  } catch (e) {
    uploadError.value = e.response?.data?.detail || 'Upload failed';
  } finally { uploading.value = false; }
}

async function del(v) {
  if (!confirm(`Delete "${v.name}"?`)) return;
  try {
    await api.delete(`/admin/voices/${v.id}`);
    await load();
  } catch (e) {
    alert(e.response?.data?.detail || 'Delete failed');
  }
}

onMounted(load);
</script>

<template>
  <div>
    <router-link to="/users" class="back-link">← 返回列表</router-link>
    <div class="page-header"><h2>{{ username }} 的 Agent</h2></div>
    <table>
      <thead><tr>
        <th>照片</th><th>别名</th><th>音色</th><th>自定义人设</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="a in agents" :key="a.id">
          <td>
            <img v-if="a.photo_url" :src="a.photo_url" style="width:36px;height:36px;border-radius:50%;object-fit:cover;border:1px solid #444" />
            <span v-else style="color:#666;font-size:10px">-</span>
          </td>
          <td>{{ a.alias }}</td>
          <td style="color:#4a90d9;font-size:12px">{{ (a.voice_id || '').substring(0, 25) }}</td>
          <td style="color:#888;max-width:300px">{{ a.system_prompt }}</td>
          <td>
            <button class="btn-ghost" @click="startEdit(a)">编辑</button>
            <button class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="revoke(a)">回收</button>
          </td>
        </tr>
        <tr v-if="!agents.length">
          <td colspan="5" style="color:#888;text-align:center;padding:24px">暂无 Agent</td>
        </tr>
      </tbody>
    </table>

    <div v-if="editingAgent" class="modal-overlay" @click.self="editingAgent = null">
      <form class="modal" @submit.prevent="saveEdit" style="min-width:400px">
        <h3>编辑 {{ editingAgent.alias }}</h3>
        <input v-model="editAliasText" style="width:100%;background:#111;color:#ddd;border:1px solid #333;border-radius:6px;padding:8px 10px;font-size:14px;margin-bottom:8px;box-sizing:border-box" placeholder="Agent 名字" />
        <textarea v-model="editPromptText" rows="6" style="width:100%;background:#111;color:#ddd;border:1px solid #333;border-radius:6px;padding:10px;font-size:14px" placeholder="输入新的 system prompt"></textarea>
        <label style="display:block;margin-bottom:4px;color:#888;font-size:13px">照片</label>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <img v-if="editPhotoPreview" :src="editPhotoPreview" style="width:56px;height:56px;border-radius:50%;object-fit:cover;border:2px solid #4a90d9" />
          <div v-else style="width:56px;height:56px;border-radius:50%;background:#111;border:2px dashed #333;display:flex;align-items:center;justify-content:center;color:#666;font-size:9px">无</div>
          <div>
            <label style="cursor:pointer;color:#4a90d9;font-size:12px">
              {{ uploadLoading ? '上传中...' : '选择图片' }}
              <input type="file" accept="image/*" style="display:none" @change="handleUpload" :disabled="uploadLoading" />
            </label>
            <button v-if="editPhotoUrl" class="btn-ghost" style="color:#e74c3c;font-size:11px;display:block;margin-top:4px" @click="editPhotoUrl = ''; editPhotoPreview = ''">移除照片</button>
          </div>
        </div>
        <p v-if="uploadError" class="error" style="font-size:11px">{{ uploadError }}</p>
        <p v-if="editError" class="error">{{ editError }}</p>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" @click="editingAgent = null">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="editLoading">保存</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import api from '../api.js';

const route = useRoute();
const username = route.params.username;
const agents = ref([]);
const editingAgent = ref(null);
const editAliasText = ref('');
const editPromptText = ref('');
const editPhotoUrl = ref('');
const editPhotoPreview = ref('');
const uploadLoading = ref(false);
const uploadError = ref('');
const editLoading = ref(false);
const editError = ref('');

async function load() {
  const r = await api.get(`/admin/users/${username}/agents`);
  agents.value = r.data;
}

function startEdit(agent) {
  editingAgent.value = agent;
  editAliasText.value = agent.alias || '';
  editPromptText.value = agent.system_prompt || '';
  editPhotoUrl.value = agent.photo_url || '';
  editPhotoPreview.value = agent.photo_url || '';
  uploadError.value = '';
  editError.value = '';
}

async function handleUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  uploadError.value = '';
  uploadLoading.value = true;
  try {
    const formData = new FormData();
    formData.append('file', file);
    const r = await api.post('/admin/upload', formData);
    if (r.data.ok) {
      editPhotoUrl.value = r.data.url;
      editPhotoPreview.value = r.data.url;
    } else {
      uploadError.value = r.data.error || 'Upload failed';
    }
  } catch (err) {
    uploadError.value = err.response?.data?.detail || 'Upload failed';
  } finally { uploadLoading.value = false; }
}

async function saveEdit() {
  editLoading.value = true; editError.value = '';
  try {
    await api.patch(`/agents/${editingAgent.value.id}`, {
      alias: editAliasText.value.trim(),
      system_prompt: editPromptText.value.trim(),
      photo_url: editPhotoUrl.value,
    });
    editingAgent.value = null;
    await load();
  } catch (e) {
    editError.value = e.response?.data?.detail || 'Update failed';
  } finally { editLoading.value = false; }
}

async function revoke(agent) {
  if (!confirm(`Revoke ${agent.alias}?`)) return;
  const rootId = agent.source_agent_id || agent.id;
  await api.delete(`/agents/${rootId}/grant/${username}`);
  await load();
}

onMounted(load);
</script>

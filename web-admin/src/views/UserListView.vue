<template>
  <div>
    <div class="page-header">
      <h2>用户管理</h2>
      <button class="btn-primary" @click="openCreate">+ 创建用户</button>
    </div>

    <!-- Create User Modal -->
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal">
        <h3>创建用户</h3>
        <p class="modal-subtitle">新用户角色默认为 user，默认密码 aB@12345</p>
        <input v-model="createForm.username" placeholder="输入用户名" @keyup.enter="doCreate">
        <input v-model="createForm.password" type="text">
        <div class="modal-actions">
          <button class="btn-ghost" @click="showCreate = false" :disabled="creating">取消</button>
          <button class="btn-primary" @click="doCreate" :disabled="creating">{{ creating ? '创建中...' : '确认创建' }}</button>
        </div>
        <p v-if="createError" class="error">{{ createError }}</p>
      </div>
    </div>

    <!-- Reset Password Modal -->
    <div v-if="showReset" class="modal-overlay" @click.self="showReset = false">
      <div class="modal">
        <h3>重置用户密码</h3>
        <p class="modal-subtitle">为用户 <strong>{{ resetTarget }}</strong> 设置新密码</p>
        <input v-model="resetForm.new_password" type="text" @keyup.enter="doReset">
        <div class="modal-actions">
          <button class="btn-ghost" @click="showReset = false" :disabled="resetting">取消</button>
          <button class="btn-primary" @click="doReset" :disabled="resetting">{{ resetting ? '重置中...' : '确认重置' }}</button>
        </div>
        <p v-if="resetError" class="error">{{ resetError }}</p>
      </div>
    </div>

    <!-- Success Toast -->
    <div v-if="toast" class="toast">{{ toast }}</div>

    <table>
      <thead><tr>
        <th>用户名</th><th>角色</th><th>拥有 Agent</th><th>注册时间</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.username }}</td>
          <td>{{ u.role === 'admin' ? '管理员' : '用户' }}</td>
          <td>
            <span v-for="a in u.agents" :key="a.id" class="tag">
              {{ a.alias }} <span class="revoke" @click="revoke(a, u.username)">✕</span>
            </span>
            <span v-if="!u.agents?.length" style="color:#888;font-size:12px">无</span>
          </td>
          <td style="color:#888;font-size:12px">{{ (u.created_at || '').substring(0, 10) }}</td>
          <td>
            <button class="btn-ghost" @click="$router.push(`/users/${u.username}`)">详情</button>
            <button class="btn-ghost" @click="openReset(u)">重置密码</button>
            <button v-if="u.role !== 'admin'" class="btn-ghost" style="color:#e74c3c;margin-left:4px" @click="del(u)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../api.js';

const users = ref([]);

const showCreate = ref(false);
const creating = ref(false);
const createError = ref('');
const createForm = ref({ username: '', password: 'aB@12345' });

const showReset = ref(false);
const resetting = ref(false);
const resetError = ref('');
const resetTarget = ref('');
const resetForm = ref({ new_password: 'aB@12345' });

const toast = ref('');

function showToast(msg) {
  toast.value = msg;
  setTimeout(() => { toast.value = ''; }, 3000);
}

async function load() {
  const [r1, r2] = await Promise.all([
    api.get('/admin/users'),
    api.get('/admin/agents'),
  ]);
  const allAgents = r2.data;
  users.value = r1.data.map(u => ({
    ...u,
    agents: allAgents.filter(a => a.owner_id === u.id),
  }));
}

function openCreate() {
  createForm.value = { username: '', password: 'aB@12345' };
  createError.value = '';
  showCreate.value = true;
}

async function doCreate() {
  createError.value = '';
  if (!createForm.value.username.trim()) {
    createError.value = '用户名不能为空';
    return;
  }
  creating.value = true;
  try {
    await api.post('/admin/users', createForm.value);
    showCreate.value = false;
    showToast('用户创建成功');
    await load();
  } catch (e) {
    createError.value = e.response?.data?.detail || '创建失败';
  } finally {
    creating.value = false;
  }
}

function openReset(user) {
  resetTarget.value = user.username;
  resetForm.value = { new_password: 'aB@12345' };
  resetError.value = '';
  showReset.value = true;
}

async function doReset() {
  resetError.value = '';
  resetting.value = true;
  try {
    await api.put(`/admin/users/${encodeURIComponent(resetTarget.value)}/reset-password`, resetForm.value);
    showReset.value = false;
    showToast(`${resetTarget.value} 密码已重置`);
  } catch (e) {
    resetError.value = e.response?.data?.detail || '重置失败';
  } finally {
    resetting.value = false;
  }
}

async function revoke(agent, username) {
  if (!confirm(`Revoke ${agent.alias} from ${username}?`)) return;
  const rootId = agent.source_agent_id || agent.id;
  await api.delete(`/agents/${rootId}/grant/${username}`);
  await load();
}

async function del(user) {
  const name = user.username;
  if (!name || user.role === 'admin') return;
  if (!confirm(`Delete user "${name}" and all their agents?`)) return;
  await api.delete(`/admin/users/${encodeURIComponent(name)}`);
  await load();
}

onMounted(load);
</script>

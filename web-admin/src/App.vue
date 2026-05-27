<template>
  <div v-if="$route.path === '/login'">
    <router-view />
  </div>
  <div v-else class="layout">
    <aside class="sidebar">
      <h2 class="logo">call_me Admin</h2>
      <nav>
        <router-link to="/agents">Agent 管理</router-link>
        <router-link to="/users">用户管理</router-link>
        <router-link to="/model-configs">LLM模型</router-link>
        <router-link to="/tts-configs">TTS 模型</router-link>
        <router-link to="/voices">声音库</router-link>
        <router-link to="/api-keys">API Keys</router-link>
        <router-link to="/call-logs">通话记录</router-link>
        <router-link to="/stats">数据统计</router-link>
      </nav>
      <div class="sidebar-footer">
        <span>{{ username }}</span>
        <button @click="openChangePassword">修改密码</button>
        <button @click="logout">退出</button>
      </div>
    </aside>
    <main class="content">
      <router-view />
    </main>

    <!-- Change Password Modal -->
    <div v-if="showChangePassword" class="modal-overlay" @click.self="showChangePassword = false">
      <div class="modal">
        <h3>修改管理员密码</h3>
        <input v-model="changePwForm.old_password" type="password" placeholder="输入当前密码">
        <input v-model="changePwForm.new_password" type="password" placeholder="输入新密码">
        <input v-model="confirmNewPassword" type="password" placeholder="再次输入新密码">
        <div class="modal-actions">
          <button class="btn-ghost" @click="showChangePassword = false" :disabled="changing">取消</button>
          <button class="btn-primary" @click="doChangePassword" :disabled="changing">{{ changing ? '修改中...' : '确认修改' }}</button>
        </div>
        <p v-if="changePwError" class="error">{{ changePwError }}</p>
      </div>
    </div>

    <!-- Success Toast -->
    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import api from './api.js';

const router = useRouter();
const username = ref('');

const showChangePassword = ref(false);
const changing = ref(false);
const changePwError = ref('');
const changePwForm = ref({ old_password: '', new_password: '' });
const confirmNewPassword = ref('');
const toast = ref('');

function showToast(msg) {
  toast.value = msg;
  setTimeout(() => { toast.value = ''; }, 3000);
}

onMounted(() => {
  username.value = localStorage.getItem('admin_user') || '';
});

function openChangePassword() {
  changePwForm.value = { old_password: '', new_password: '' };
  confirmNewPassword.value = '';
  changePwError.value = '';
  showChangePassword.value = true;
}

async function doChangePassword() {
  changePwError.value = '';
  if (changePwForm.value.new_password !== confirmNewPassword.value) {
    changePwError.value = '两次输入的新密码不一致';
    return;
  }
  changing.value = true;
  try {
    await api.put('/auth/change-password', changePwForm.value);
    showChangePassword.value = false;
    showToast('密码修改成功');
  } catch (e) {
    changePwError.value = e.response?.data?.detail || '修改失败';
  } finally {
    changing.value = false;
  }
}

function logout() {
  localStorage.removeItem('admin_token');
  localStorage.removeItem('admin_user');
  router.push('/login');
}
</script>

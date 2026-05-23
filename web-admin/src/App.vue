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
      </nav>
      <div class="sidebar-footer">
        <span>{{ username }}</span>
        <button @click="logout">退出</button>
      </div>
    </aside>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
const router = useRouter();
const username = ref('');

onMounted(() => {
  username.value = localStorage.getItem('admin_user') || '';
});

function logout() {
  localStorage.removeItem('admin_token');
  localStorage.removeItem('admin_user');
  router.push('/login');
}
</script>

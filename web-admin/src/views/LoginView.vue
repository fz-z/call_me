<template>
  <div class="login-page">
    <form @submit.prevent="login" class="login-form">
      <h1>call_me Admin</h1>
      <input v-model="form.username" placeholder="用户名" required />
      <input v-model="form.password" type="password" placeholder="密码" required />
      <p v-if="error" class="error">{{ error }}</p>
      <button type="submit" :disabled="loading">登录</button>
    </form>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import api from '../api.js';

const router = useRouter();
const form = reactive({ username: '', password: '' });
const loading = ref(false);
const error = ref('');

async function login() {
  loading.value = true;
  error.value = '';
  try {
    const r = await api.post('/auth/login', form);
    if (r.data.user.role !== 'admin') {
      error.value = '仅限管理员登录';
      return;
    }
    localStorage.setItem('admin_token', r.data.token);
    localStorage.setItem('admin_user', r.data.user.username);
    router.push('/agents');
  } catch (e) {
    error.value = e.response?.data?.detail || '登录失败';
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal">
      <h3>授权 "{{ agent.alias }}"</h3>
      <input v-model="username" placeholder="输入用户名" />
      <p v-if="error" class="error">{{ error }}</p>
      <div class="modal-actions">
        <button class="btn-ghost" @click="$emit('close')">取消</button>
        <button class="btn btn-primary" @click="grant" :disabled="loading">授权</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import api from '../api.js';

const props = defineProps({ agent: Object });
const emit = defineEmits(['close', 'done']);

const username = ref('');
const loading = ref(false);
const error = ref('');

async function grant() {
  if (!username.value.trim()) return;
  loading.value = true;
  error.value = '';
  try {
    await api.post(`/agents/${props.agent.id}/grant`, { username: username.value.trim() });
    emit('done');
    emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || '授权失败';
  } finally {
    loading.value = false;
  }
}
</script>

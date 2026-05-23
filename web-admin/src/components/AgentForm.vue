<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <form class="modal" @submit.prevent="submit">
      <h3>{{ editId ? '编辑' : '创建' }} Agent</h3>
      <input v-model="alias" placeholder="别名" required />
      <textarea v-model="systemPrompt" placeholder="人设描述 (system prompt)"></textarea>
      <input v-if="!editId" type="file" accept="audio/*" @change="onFile" required />
      <p v-if="error" class="error">{{ error }}</p>
      <div class="modal-actions">
        <button type="button" class="btn-ghost" @click="$emit('close')">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="loading">
          {{ loading ? '保存中...' : '保存' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import api from '../api.js';

const props = defineProps({ editId: String, editAlias: String, editPrompt: String });
const emit = defineEmits(['close', 'saved']);

const alias = ref(props.editAlias || '');
const systemPrompt = ref(props.editPrompt || '');
const file = ref(null);
const loading = ref(false);
const error = ref('');

function onFile(e) { file.value = e.target.files[0]; }

async function submit() {
  loading.value = true;
  error.value = '';
  try {
    if (props.editId) {
      await api.patch(`/agents/${props.editId}`, { alias: alias.value, system_prompt: systemPrompt.value });
    } else {
      const fd = new FormData();
      fd.append('alias', alias.value);
      fd.append('system_prompt', systemPrompt.value);
      fd.append('audio_file', file.value);
      await api.post('/agents', fd);
    }
    emit('saved');
    emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed';
  } finally {
    loading.value = false;
  }
}
</script>

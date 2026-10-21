<template>
  <div class="modal-overlay" @click.self="close">
    <form class="modal preview-modal" @submit.prevent="submit">
      <h3>实时音色试听 · {{ binding.runtime_config_name }}</h3>
      <p class="hint">使用此实时模型绑定的克隆音色生成短音频；每次生成可能产生模型费用。模型可能略微改写文案。</p>
      <label for="realtime-preview-text">本次试听文案</label>
      <textarea id="realtime-preview-text" v-model="text" rows="4"></textarea>
      <p class="hint">最多 120 个字；关闭后不会保存。</p>
      <p v-if="getRealtimeAuditionTextError(text)" class="error" role="alert">{{ getRealtimeAuditionTextError(text) }}</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <audio v-if="audioUrl" ref="player" :src="audioUrl" controls @error="error = '音频播放失败。'"></audio>
      <div class="actions">
        <button type="button" class="btn-ghost" @click="close">关闭</button>
        <button type="submit" class="btn btn-primary" :disabled="loading || !!getRealtimeAuditionTextError(text)">
          {{ loading ? '生成中…' : '生成试听' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue';
import api from '../api.js';
import { createGenerationGuard } from '../utils/voiceManagement.js';
import {
  DEFAULT_REALTIME_AUDITION_TEXT, getRealtimeAuditionTextError, runCurrentPreview,
} from '../utils/realtimeVoiceAudition.js';

const props = defineProps({ voiceId: { type: String, required: true }, binding: { type: Object, required: true } });
const emit = defineEmits(['close']);
const text = ref(DEFAULT_REALTIME_AUDITION_TEXT);
const loading = ref(false);
const error = ref('');
const audioUrl = ref('');
const player = ref(null);
const guard = createGenerationGuard();
let controller = null;

function releaseAudio() {
  player.value?.pause();
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value);
  audioUrl.value = '';
}
function cleanup() {
  guard.invalidate();
  controller?.abort();
  controller = null;
  loading.value = false;
  releaseAudio();
}
function close() { cleanup(); emit('close'); }
onBeforeUnmount(cleanup);

async function submit() {
  const message = getRealtimeAuditionTextError(text.value);
  if (message || loading.value) { error.value = message; return; }
  releaseAudio();
  error.value = '';
  loading.value = true;
  const requestController = new AbortController();
  controller = requestController;
  try {
    const response = await runCurrentPreview(() => api.post(
      `/admin/voices/${props.voiceId}/realtime-bindings/${props.binding.runtime_config_id}/audition`,
      { text: text.value.trim() }, { signal: requestController.signal },
    ), guard);
    if (!response) return;
    const bytes = Uint8Array.from(atob(response.data.audio_base64), (char) => char.charCodeAt(0));
    audioUrl.value = URL.createObjectURL(new Blob([bytes], { type: response.data.mime_type }));
  } catch (requestError) {
    if (!requestController.signal.aborted) {
      error.value = requestError.response?.data?.detail || '实时音色试听失败，请重试。';
    }
  } finally {
    if (controller === requestController) {
      controller = null;
      loading.value = false;
    }
  }
}
</script>

<style scoped>
.preview-modal { width: min(520px, calc(100vw - 32px)); min-width: 0; box-sizing: border-box; }
.preview-modal h3 { margin-bottom: 12px; }
.hint { color: #94a3b8; font-size: 12px; line-height: 1.6; margin: 8px 0; }
label { display: block; margin: 14px 0 6px; color: #cbd5e1; }
textarea { width: 100%; box-sizing: border-box; padding: 9px; background: #0f0f1a; color: #e0e0e0; border: 1px solid #475569; border-radius: 5px; }
audio { display: block; width: 100%; margin-top: 12px; }
.error { color: #f87171; font-size: 13px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>

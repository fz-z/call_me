<template>
  <div class="modal-overlay" @click.self="close">
    <form class="modal preview-modal" @submit.prevent="submit">
      <h3>实时音色试听 · {{ binding.runtime_config_name }}</h3>
      <p class="hint">使用此实时模型绑定的克隆音色分段生成并播放。每段都会调用模型，可能产生费用；模型可能略微改写文案，段间也可能有短暂停顿。</p>
      <label for="realtime-preview-text">本次试听文案</label>
      <textarea id="realtime-preview-text" v-model="text" rows="6"></textarea>
      <p class="hint">{{ characterCount }}/{{ MAX_REALTIME_AUDITION_TEXT_LENGTH }} 字；关闭后不会保存。</p>
      <p v-if="getRealtimeAuditionTextError(text)" class="error" role="alert">{{ getRealtimeAuditionTextError(text) }}</p>
      <p v-if="queueState.error" class="error" role="alert">第 {{ queueState.index + 1 }} 段：{{ queueState.error }}</p>
      <p v-if="queueState.total" class="progress" role="status">
        第 {{ Math.min(queueState.index + 1, queueState.total) }}/{{ queueState.total }} 段
        <span v-if="queueState.status === 'loading'"> · 正在生成</span>
        <span v-else-if="queueState.status === 'waiting'"> · 正在准备下一段</span>
        <span v-else-if="queueState.status === 'paused'"> · 已暂停</span>
        <span v-else-if="queueState.status === 'completed'"> · 试听完成</span>
      </p>
      <audio ref="player" :src="audioUrl" @ended="queue.ended()" @error="onAudioError"></audio>
      <div v-if="queueState.total" class="playback-actions">
        <button v-if="queueState.status === 'playing'" type="button" class="btn-ghost" @click="queue.pause()">暂停</button>
        <button v-if="queueState.status === 'paused'" type="button" class="btn-ghost" @click="queue.resume()">继续</button>
        <button v-if="queueState.status === 'error'" type="button" class="btn-ghost" @click="queue.retry()">重试当前段</button>
        <button v-if="queueState.status !== 'idle' && queueState.status !== 'completed'" type="button" class="btn-ghost" @click="queue.stop()">停止</button>
      </div>
      <div class="actions">
        <button type="button" class="btn-ghost" @click="close">关闭</button>
        <button type="submit" class="btn btn-primary" :disabled="!!getRealtimeAuditionTextError(text)">
          {{ queueState.total ? '重新生成并试听' : '生成并试听' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import api from '../api.js';
import { createRealtimeAuditionQueue } from '../utils/realtimeAuditionQueue.js';
import {
  DEFAULT_REALTIME_AUDITION_TEXT, MAX_REALTIME_AUDITION_TEXT_LENGTH,
  createSilentAuditionWav, getRealtimeAuditionTextError,
  isSilentRealtimeAuditionSegment, splitRealtimeAuditionText,
} from '../utils/realtimeVoiceAudition.js';

const props = defineProps({ voiceId: { type: String, required: true }, binding: { type: Object, required: true } });
const emit = defineEmits(['close']);
const text = ref(DEFAULT_REALTIME_AUDITION_TEXT);
const audioUrl = ref('');
const player = ref(null);
const queueState = ref({ status: 'idle', index: 0, total: 0, error: '' });
const characterCount = computed(() => Array.from(text.value.trim()).length);

const queue = createRealtimeAuditionQueue({
  request: async (part, signal) => {
    if (isSilentRealtimeAuditionSegment(part)) return { silent: true };
    try {
      const response = await api.post(
        `/admin/voices/${props.voiceId}/realtime-bindings/${props.binding.runtime_config_id}/audition`,
        { text: part }, { signal },
      );
      return response.data;
    } catch (requestError) {
      throw new Error(requestError.response?.data?.detail || '实时音色试听失败，请重试。');
    }
  },
  makeUrl: (audio) => {
    if (audio.silent) {
      return URL.createObjectURL(new Blob([createSilentAuditionWav()], { type: 'audio/wav' }));
    }
    const bytes = Uint8Array.from(atob(audio.audio_base64), (char) => char.charCodeAt(0));
    return URL.createObjectURL(new Blob([bytes], { type: audio.mime_type }));
  },
  revokeUrl: (url) => URL.revokeObjectURL(url),
  play: async (url) => {
    audioUrl.value = url;
    await nextTick();
    await player.value?.play();
  },
  pause: () => player.value?.pause(),
  onState: (state) => {
    queueState.value = state;
    if (state.status === 'idle' || state.status === 'completed') {
      audioUrl.value = '';
    }
  },
});

function submit() {
  if (getRealtimeAuditionTextError(text.value)) return;
  queue.start(splitRealtimeAuditionText(text.value));
}
function onAudioError() {
  queue.failPlayback('音频播放失败。');
  audioUrl.value = '';
}
function close() { queue.dispose(); emit('close'); }
watch(() => [props.voiceId, props.binding.runtime_config_id], () => {
  queue.stop();
  text.value = DEFAULT_REALTIME_AUDITION_TEXT;
});
onBeforeUnmount(() => queue.dispose());
</script>

<style scoped>
.preview-modal { width: min(560px, calc(100vw - 32px)); min-width: 0; box-sizing: border-box; }
.preview-modal h3 { margin-bottom: 12px; }
.hint { color: #94a3b8; font-size: 12px; line-height: 1.6; margin: 8px 0; }
label { display: block; margin: 14px 0 6px; color: #cbd5e1; }
textarea { width: 100%; box-sizing: border-box; padding: 9px; background: #0f0f1a; color: #e0e0e0; border: 1px solid #475569; border-radius: 5px; }
audio { display: none; }
.error { color: #f87171; font-size: 13px; }
.progress { color: #cbd5e1; font-size: 13px; }
.playback-actions { display: flex; gap: 8px; margin-top: 12px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>

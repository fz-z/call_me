import test from 'node:test';
import assert from 'node:assert/strict';

import {
  getRealtimeAudioDurationError,
  MAX_REALTIME_AUDIO_SECONDS,
} from '../src/utils/audioDuration.js';

test('explains when a realtime voice sample exceeds the 60 second limit', () => {
  assert.equal(MAX_REALTIME_AUDIO_SECONDS, 60);
  assert.equal(
    getRealtimeAudioDurationError(108.72),
    '音频时长为 1 分 49 秒，超过端到端音色克隆的 60 秒上限。请剪辑到 60 秒以内后重新选择。',
  );
});

test('accepts audio exactly at the realtime voice duration limit', () => {
  assert.equal(getRealtimeAudioDurationError(60), '');
});

test('explains when audio duration cannot be read', () => {
  assert.equal(
    getRealtimeAudioDurationError(Number.NaN),
    '无法读取音频时长，请确认文件未损坏并重新选择。',
  );
});

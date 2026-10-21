import test from 'node:test';
import assert from 'node:assert/strict';

import {
  filterRealtimeVoices,
  runtimeDisplayName,
  buildAgentRuntimePayload,
} from '../src/utils/agentRuntimeForm.js';

const voices = [
  { id: 'voice-a', name: '晨光' },
  { id: 'voice-b', name: '晚风' },
];

test('only offers voices bound to the selected realtime config', () => {
  const bindings = {
    'voice-a': [{ runtime_kind: 'realtime', runtime_config_id: 'realtime-a' }],
    'voice-b': [{ runtime_kind: 'realtime', runtime_config_id: 'realtime-b' }],
  };

  assert.deepEqual(
    filterRealtimeVoices(voices, bindings, 'realtime-a').map((voice) => voice.id),
    ['voice-a'],
  );
});

test('builds a realtime agent payload without classic runtime fields', () => {
  assert.deepEqual(buildAgentRuntimePayload({
    alias: '实时助手',
    systemPrompt: '保持自然对话',
    voicePoolId: 'voice-a',
    runtimeMode: 'realtime',
    realtimeConfigId: 'realtime-a',
    modelConfigId: 'llm-a',
    ttsConfigId: 'tts-a',
    photoUrl: '/photos/a.png',
  }), {
    alias: '实时助手',
    system_prompt: '保持自然对话',
    voice_pool_id: 'voice-a',
    runtime_mode: 'realtime',
    realtime_config_id: 'realtime-a',
    model_config_id: null,
    tts_config_id: null,
    photo_url: '/photos/a.png',
    speech_rate: 1.0,
  });
});

test('builds a pipeline agent payload without a realtime configuration', () => {
  assert.deepEqual(buildAgentRuntimePayload({
    alias: '经典助手',
    systemPrompt: '',
    voicePoolId: 'voice-a',
    runtimeMode: 'pipeline',
    realtimeConfigId: 'realtime-a',
    modelConfigId: 'llm-a',
    ttsConfigId: 'tts-a',
    photoUrl: '',
  }), {
    alias: '经典助手',
    system_prompt: '',
    voice_pool_id: 'voice-a',
    runtime_mode: 'pipeline',
    realtime_config_id: null,
    model_config_id: 'llm-a',
    tts_config_id: 'tts-a',
    photo_url: '',
    speech_rate: 1.0,
  });
});

test('passes the per-agent speech rate through', () => {
  assert.equal(buildAgentRuntimePayload({
    alias: '快语速助手',
    systemPrompt: '',
    voicePoolId: 'voice-a',
    runtimeMode: 'pipeline',
    modelConfigId: 'llm-a',
    ttsConfigId: 'tts-a',
    speechRate: 1.4,
  }).speech_rate, 1.4);
});

test('renders readable runtime labels without exposing provider voice ids', () => {
  assert.equal(runtimeDisplayName('pipeline'), '经典 Pipeline');
  assert.equal(runtimeDisplayName('realtime'), '端到端实时');
});

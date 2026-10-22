import test from 'node:test';
import assert from 'node:assert/strict';
import { canExpandCallLog, runtimeLabel } from './callLogRuntime.js';

test('realtime label prefers the saved configuration name', () => {
  assert.equal(runtimeLabel({ runtime_mode: 'realtime', runtime_config_name: 'Qwen 3.0 实时测试', model: 'qwen-audio-3.0-realtime-plus', provider: 'qwen' }), '端到端实时 · Qwen 3.0 实时测试');
});

test('old records fall back to model, then provider, then mode', () => {
  assert.equal(runtimeLabel({ runtime_mode: 'realtime', model: 'qwen-audio-3.0-realtime-plus', provider: 'qwen' }), '端到端实时 · qwen-audio-3.0-realtime-plus');
  assert.equal(runtimeLabel({ runtime_mode: 'realtime', provider: 'qwen' }), '端到端实时 · qwen');
  assert.equal(runtimeLabel({ runtime_mode: 'realtime' }), '端到端实时');
  assert.equal(runtimeLabel({ runtime_mode: 'pipeline', model: 'qwen-plus', provider: 'qwen' }), 'Pipeline · qwen-plus');
});

test('diagnostic failures remain expandable without a transcript', () => {
  assert.equal(canExpandCallLog({ has_transcript: false, failure_stage: 'provider_connect' }), true);
  assert.equal(canExpandCallLog({ has_transcript: true, failure_stage: null }), true);
  assert.equal(canExpandCallLog({ has_transcript: false, failure_stage: null }), false);
});

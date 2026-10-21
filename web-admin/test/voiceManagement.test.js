import test from 'node:test';
import assert from 'node:assert/strict';

import {
  realtimeBindings,
  availableRealtimeConfigs,
  getRealtimeAudioFileError,
  createGenerationGuard,
  submitAndRefreshRealtimeBinding,
} from '../src/utils/voiceManagement.js';

const mixedBindings = [
  { runtime_kind: 'tts', runtime_config_id: 'tts-a', runtime_config_name: 'TTS Flash' },
  { runtime_kind: 'realtime', runtime_config_id: 'rt-a', runtime_config_name: 'Realtime Plus' },
];

test('realtime binding list excludes TTS runtime bindings', () => {
  assert.deepEqual(realtimeBindings(mixedBindings), [mixedBindings[1]]);
});

test('new clone choices exclude existing and non-cloneable configs', () => {
  const configs = [
    { id: 'rt-a', capabilities_json: '{"voice_clone":true}' },
    { id: 'rt-b', capabilities_json: '{"voice_clone":true}' },
    { id: 'rt-c', capabilities_json: '{}' },
    { id: 'rt-d', capabilities_json: 'invalid' },
  ];
  assert.deepEqual(availableRealtimeConfigs(configs, mixedBindings).map((item) => item.id), ['rt-b']);
});

test('realtime clone rejects unsupported files and oversize audio before upload', () => {
  assert.match(getRealtimeAudioFileError({ name: 'sample.txt', size: 100 }), /WAV、MP3、M4A/);
  assert.match(getRealtimeAudioFileError({ name: 'sample.wav', size: 10 * 1024 * 1024 + 1 }), /10 MB/);
  assert.equal(getRealtimeAudioFileError({ name: 'sample.M4A', size: 10 * 1024 * 1024 }), '');
});

test('switching clone target invalidates an in-flight audio selection', () => {
  const guard = createGenerationGuard();
  const firstSelection = guard.next();
  assert.equal(guard.isCurrent(firstSelection), true);
  guard.invalidate();
  assert.equal(guard.isCurrent(firstSelection), false);
  const secondSelection = guard.next();
  assert.equal(guard.isCurrent(secondSelection), true);
});

test('a newer detail load invalidates an older response', () => {
  const guard = createGenerationGuard();
  const oldLoad = guard.next();
  const newLoad = guard.next();
  assert.equal(guard.isCurrent(oldLoad), false);
  assert.equal(guard.isCurrent(newLoad), true);
});

test('a failed refresh after successful cloning does not become a failed submission', async () => {
  let submissions = 0;
  const refreshFailure = new Error('temporary GET failure');
  const result = await submitAndRefreshRealtimeBinding(
    async () => { submissions += 1; },
    async () => { throw refreshFailure; },
  );
  assert.equal(submissions, 1);
  assert.equal(result.refreshError, refreshFailure);
  assert.equal(result.bindings, null);
});

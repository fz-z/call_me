import test from 'node:test';
import assert from 'node:assert/strict';

import {
  realtimeBindings,
  availableRealtimeConfigs,
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

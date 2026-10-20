import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildRealtimeConfigPayload,
  getRealtimeConfigDeleteError,
} from '../src/utils/realtimeConfigForm.js';

test('builds the supported Qwen realtime configuration payload', () => {
  assert.deepEqual(buildRealtimeConfigPayload({
    name: '华东实时',
    api_key_id: 'qwen-key',
    endpoint: ' wss://dashscope.aliyuncs.com/api-ws/v1/realtime ',
    region: ' cn-hangzhou ',
    capabilities: '{"voice_clone":true}',
  }), {
    name: '华东实时',
    provider: 'qwen',
    model: 'qwen-audio-3.1-realtime-plus',
    api_key_id: 'qwen-key',
    endpoint: 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime',
    region: 'cn-hangzhou',
    capabilities_json: '{"voice_clone":true}',
  });
});

test('rejects non-object capabilities before sending a request', () => {
  assert.throws(
    () => buildRealtimeConfigPayload({
      name: '实时', api_key_id: '', endpoint: '', region: '', capabilities: '[]',
    }),
    /Capabilities 必须是 JSON 对象/,
  );
});

test('explains that a configuration with references cannot be deleted', () => {
  assert.equal(
    getRealtimeConfigDeleteError({ message: 'Config is referenced by agents or voice bindings' }),
    '该实时模型配置正在被 Agent 或音色绑定引用，无法删除。',
  );
});

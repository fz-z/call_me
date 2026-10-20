export const QWEN_REALTIME_PROVIDER = 'qwen';
export const QWEN_REALTIME_MODEL = 'qwen-audio-3.1-realtime-plus';

function trimString(value) {
  return typeof value === 'string' ? value.trim() : '';
}

export function buildRealtimeConfigPayload(form) {
  let capabilities;
  try {
    capabilities = JSON.parse(trimString(form.capabilities) || '{}');
  } catch (_) {
    throw new Error('Capabilities 必须是有效 JSON 对象');
  }

  if (!capabilities || Array.isArray(capabilities) || typeof capabilities !== 'object') {
    throw new Error('Capabilities 必须是 JSON 对象');
  }

  return {
    name: trimString(form.name),
    provider: QWEN_REALTIME_PROVIDER,
    model: QWEN_REALTIME_MODEL,
    api_key_id: form.api_key_id || null,
    endpoint: trimString(form.endpoint),
    region: trimString(form.region),
    capabilities_json: JSON.stringify(capabilities),
  };
}

export function getRealtimeConfigDeleteError(detail) {
  const message = typeof detail === 'string' ? detail : detail?.message;
  if (message?.includes('referenced by agents or voice bindings')) {
    return '该实时模型配置正在被 Agent 或音色绑定引用，无法删除。';
  }
  return message || '删除失败';
}

export function realtimeBindings(bindings = []) {
  return bindings.filter((binding) => binding.runtime_kind === 'realtime');
}

export function availableRealtimeConfigs(configs = [], bindings = []) {
  const used = new Set(realtimeBindings(bindings).map((binding) => binding.runtime_config_id));
  return configs.filter((config) => {
    try {
      return JSON.parse(config.capabilities_json || '{}').voice_clone === true && !used.has(config.id);
    } catch (_) {
      return false;
    }
  });
}

export function getRealtimeAudioFileError(file) {
  if (!file || !/\.(wav|mp3|m4a)$/i.test(file.name || '')) {
    return '请选择 WAV、MP3、M4A 格式的参考音频。';
  }
  if (file.size > 10 * 1024 * 1024) {
    return '参考音频不能超过 10 MB。';
  }
  return '';
}

export function createGenerationGuard() {
  let current = 0;
  return {
    next() { current += 1; return current; },
    invalidate() { current += 1; },
    current() { return current; },
    isCurrent(value) { return value === current; },
  };
}

export async function submitAndRefreshRealtimeBinding(submit, refresh) {
  await submit();
  try {
    return { bindings: await refresh(), refreshError: null };
  } catch (refreshError) {
    return { bindings: null, refreshError };
  }
}

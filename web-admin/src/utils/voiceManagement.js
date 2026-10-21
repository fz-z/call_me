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

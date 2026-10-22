export function runtimeLabel(log) {
  const mode = log.runtime_mode === 'realtime' ? '端到端实时' : 'Pipeline';
  const name = log.runtime_config_name || log.model || log.provider;
  return name ? `${mode} · ${name}` : mode;
}

export function canExpandCallLog(log) {
  return Boolean(log.has_transcript || log.failure_stage);
}

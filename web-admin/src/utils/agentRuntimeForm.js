export function runtimeDisplayName(runtimeMode) {
  return runtimeMode === 'realtime' ? '端到端实时' : '经典 Pipeline';
}

export function filterRealtimeVoices(voices, bindingsByVoice, realtimeConfigId) {
  if (!realtimeConfigId) return [];
  return voices.filter((voice) => (bindingsByVoice[voice.id] || []).some(
    (binding) => binding.runtime_kind === 'realtime'
      && binding.runtime_config_id === realtimeConfigId,
  ));
}

export function filterClassicVoices(voices) {
  return voices.filter((voice) => voice.has_classic_voice !== false);
}

export function buildAgentRuntimePayload({
  alias,
  systemPrompt,
  greetingText,
  voicePoolId,
  runtimeMode,
  realtimeConfigId,
  modelConfigId,
  ttsConfigId,
  photoUrl,
  speechRate,
  allowInterruptions,
}) {
  const realtime = runtimeMode === 'realtime';
  return {
    alias,
    system_prompt: systemPrompt,
    greeting_text: greetingText || '',
    voice_pool_id: voicePoolId,
    runtime_mode: realtime ? 'realtime' : 'pipeline',
    realtime_config_id: realtime ? (realtimeConfigId || null) : null,
    model_config_id: realtime ? null : (modelConfigId || null),
    tts_config_id: realtime ? null : (ttsConfigId || null),
    photo_url: photoUrl || '',
    speech_rate: speechRate == null ? 1.0 : Number(speechRate),
    allow_interruptions: allowInterruptions !== false,
  };
}

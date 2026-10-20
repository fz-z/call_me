export const MAX_REALTIME_AUDIO_SECONDS = 60;

function formatAudioDuration(durationSeconds) {
  const totalSeconds = Math.ceil(durationSeconds);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes && seconds) return `${minutes} 分 ${seconds} 秒`;
  if (minutes) return `${minutes} 分钟`;
  return `${seconds} 秒`;
}

export function getRealtimeAudioDurationError(durationSeconds) {
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    return '无法读取音频时长，请确认文件未损坏并重新选择。';
  }
  if (durationSeconds > MAX_REALTIME_AUDIO_SECONDS) {
    return `音频时长为 ${formatAudioDuration(durationSeconds)}，超过端到端音色克隆的 60 秒上限。请剪辑到 60 秒以内后重新选择。`;
  }
  return '';
}

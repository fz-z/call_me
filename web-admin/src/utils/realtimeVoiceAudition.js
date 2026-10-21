export const DEFAULT_REALTIME_AUDITION_TEXT = '你好，这是实时音色试听。';

export function getRealtimeAuditionTextError(text) {
  const trimmed = text.trim();
  if (!trimmed) return '请输入试听文案。';
  if (Array.from(trimmed).length > 120) return '试听文案不能超过 120 个字。';
  return '';
}

export async function runCurrentPreview(send, guard) {
  const generation = guard.next();
  try {
    const result = await send();
    return guard.isCurrent(generation) ? result : null;
  } catch (error) {
    if (!guard.isCurrent(generation)) return null;
    throw error;
  }
}

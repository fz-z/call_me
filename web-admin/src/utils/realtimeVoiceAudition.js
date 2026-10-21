export const DEFAULT_REALTIME_AUDITION_TEXT = '你好，这是实时音色试听。';
export const MAX_REALTIME_AUDITION_TEXT_LENGTH = 3000;
export const MAX_REALTIME_AUDITION_SEGMENT_LENGTH = 120;

export function getRealtimeAuditionTextError(text) {
  const trimmed = text.trim();
  if (!trimmed) return '请输入试听文案。';
  if (Array.from(trimmed).length > MAX_REALTIME_AUDITION_TEXT_LENGTH) {
    return `试听文案不能超过 ${MAX_REALTIME_AUDITION_TEXT_LENGTH} 个字。`;
  }
  return '';
}

export function splitRealtimeAuditionText(text, maxLength = MAX_REALTIME_AUDITION_SEGMENT_LENGTH) {
  if (!Number.isInteger(maxLength) || maxLength < 1) throw new RangeError('Invalid segment length');
  const characters = Array.from(text.trim());
  const segments = [];
  for (let start = 0; start < characters.length;) {
    let end = Math.min(start + maxLength, characters.length);
    if (end < characters.length) {
      for (let index = end - 1; index >= start; index--) {
        if (/[。！？.!?；;\n]/u.test(characters[index])) {
          end = index + 1;
          break;
        }
      }
    }
    segments.push(characters.slice(start, end).join(''));
    start = end;
  }
  return segments;
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

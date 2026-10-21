export const DEFAULT_REALTIME_AUDITION_TEXT = '你好，这是实时音色试听。';
export const MAX_REALTIME_AUDITION_TEXT_LENGTH = 3000;
export const MAX_REALTIME_AUDITION_SEGMENT_LENGTH = 120;

export function isSilentRealtimeAuditionSegment(text) { return !text.trim(); }

export function createSilentAuditionWav() {
  const dataLength = 2400 * 2; // 100 ms of 24 kHz mono PCM16 silence.
  const bytes = new Uint8Array(44 + dataLength);
  const view = new DataView(bytes.buffer);
  for (const [offset, label] of [[0, 'RIFF'], [8, 'WAVE'], [12, 'fmt '], [36, 'data']]) {
    for (let index = 0; index < 4; index++) bytes[offset + index] = label.charCodeAt(index);
  }
  view.setUint32(4, 36 + dataLength, true);
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 24000, true);
  view.setUint32(28, 48000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  view.setUint32(40, dataLength, true);
  return bytes;
}

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

import test from 'node:test';
import assert from 'node:assert/strict';
import { createGenerationGuard } from '../src/utils/voiceManagement.js';
import { getRealtimeAuditionTextError, runCurrentPreview, splitRealtimeAuditionText } from '../src/utils/realtimeVoiceAudition.js';

test('one-off audition text is required and limited to 3000 code points', () => {
  assert.match(getRealtimeAuditionTextError('  '), /请输入/);
  assert.match(getRealtimeAuditionTextError('字'.repeat(3001)), /3000/);
  assert.equal(getRealtimeAuditionTextError('字'.repeat(3000)), '');
  assert.equal(getRealtimeAuditionTextError('😀'.repeat(3000)), '');
});

test('audition segments preserve text and prefer sentence boundaries', () => {
  assert.deepEqual(splitRealtimeAuditionText('  你好。世界。  ', 3), ['你好。', '世界。']);
  const input = `第一句。\n${'字'.repeat(121)}结尾。`;
  const segments = splitRealtimeAuditionText(input);
  assert.equal(segments.join(''), input);
  assert.ok(segments.every((segment) => Array.from(segment).length <= 120));
  assert.equal(segments[0], '第一句。\n');
});

test('a long sentence splits by Unicode code point without loss', () => {
  const input = '😀'.repeat(121);
  assert.deepEqual(splitRealtimeAuditionText(input).map((part) => Array.from(part).length), [120, 1]);
  assert.equal(splitRealtimeAuditionText(input).join(''), input);
});

test('a response from a closed preview is discarded', async () => {
  const guard = createGenerationGuard();
  let resolve;
  const pending = new Promise((done) => { resolve = done; });
  const result = runCurrentPreview(() => pending, guard);
  guard.invalidate();
  resolve({ audio_base64: 'old' });
  assert.equal(await result, null);
  assert.deepEqual(await runCurrentPreview(async () => ({ audio_base64: 'new' }), guard),
    { audio_base64: 'new' });
});

test('a rejected request from a closed preview is discarded', async () => {
  const guard = createGenerationGuard();
  let reject;
  const pending = new Promise((_, fail) => { reject = fail; });
  const result = runCurrentPreview(() => pending, guard);
  guard.invalidate();
  reject(new Error('aborted'));
  assert.equal(await result, null);
});

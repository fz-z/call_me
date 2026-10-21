import test from 'node:test';
import assert from 'node:assert/strict';
import { createGenerationGuard } from '../src/utils/voiceManagement.js';
import { getRealtimeAuditionTextError, runCurrentPreview } from '../src/utils/realtimeVoiceAudition.js';

test('one-off audition text is required and limited to 120 code points', () => {
  assert.match(getRealtimeAuditionTextError('  '), /请输入/);
  assert.match(getRealtimeAuditionTextError('字'.repeat(121)), /120/);
  assert.equal(getRealtimeAuditionTextError('字'.repeat(120)), '');
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

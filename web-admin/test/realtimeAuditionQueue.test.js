import test from 'node:test';
import assert from 'node:assert/strict';
import { createRealtimeAuditionQueue } from '../src/utils/realtimeAuditionQueue.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function tick() { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); }

function harness() {
  const requests = [];
  const played = [];
  const revoked = [];
  let paused = 0;
  const queue = createRealtimeAuditionQueue({
    request: (text, signal) => {
      const pending = deferred();
      requests.push({ text, signal, ...pending });
      return pending.promise;
    },
    makeUrl: (audio) => `blob:${audio}`,
    revokeUrl: (url) => revoked.push(url),
    play: (url) => { played.push(url); },
    pause: () => { paused++; },
    onState: () => {},
  });
  return { queue, requests, played, revoked, get paused() { return paused; } };
}

test('plays the first segment, prefetches only the next, and continues in order', async () => {
  const h = harness();
  h.queue.start(['一', '二', '三']);
  assert.deepEqual(h.requests.map((item) => item.text), ['一']);
  h.requests[0].resolve('one');
  await tick();
  assert.deepEqual(h.played, ['blob:one']);
  assert.deepEqual(h.requests.map((item) => item.text), ['一', '二']);
  h.requests[1].resolve('two');
  await tick();
  assert.deepEqual(h.played, ['blob:one']);
  h.queue.ended();
  assert.deepEqual(h.played, ['blob:one', 'blob:two']);
  assert.deepEqual(h.revoked, ['blob:one']);
  assert.deepEqual(h.requests.map((item) => item.text), ['一', '二', '三']);
  h.requests[2].resolve('three');
  await tick();
  h.queue.ended();
  h.queue.ended();
  assert.equal(h.queue.state.status, 'completed');
  assert.deepEqual(h.revoked, ['blob:one', 'blob:two', 'blob:three']);
});

test('waits for a slow next segment then automatically resumes', async () => {
  const h = harness();
  h.queue.start(['一', '二']);
  h.requests[0].resolve('one');
  await tick();
  h.queue.ended();
  assert.equal(h.queue.state.status, 'waiting');
  h.requests[1].resolve('two');
  await tick();
  assert.deepEqual(h.played, ['blob:one', 'blob:two']);
});

test('pause, resume and stop release audio and abort the pending request', async () => {
  const h = harness();
  h.queue.start(['一', '二']);
  h.requests[0].resolve('one');
  await tick();
  h.queue.pause();
  assert.equal(h.queue.state.status, 'paused');
  assert.equal(h.paused, 1);
  h.requests[1].resolve('two');
  await tick();
  assert.deepEqual(h.played, ['blob:one']);
  h.queue.resume();
  assert.deepEqual(h.played, ['blob:one', 'blob:one']);
  h.queue.stop();
  assert.deepEqual(h.revoked, ['blob:one', 'blob:two']);
  assert.equal(h.queue.state.status, 'idle');
});

test('stopping ignores an old result and aborts its request', async () => {
  const h = harness();
  h.queue.start(['旧']);
  h.queue.stop();
  assert.equal(h.requests[0].signal.aborted, true);
  h.requests[0].resolve('old');
  await tick();
  assert.deepEqual(h.played, []);
  assert.deepEqual(h.revoked, []);
});

test('a stale playback rejection cannot fail a newer audition', async () => {
  const oldPlayback = deferred();
  const requests = [];
  const queue = createRealtimeAuditionQueue({
    request: (text) => { requests.push(text); return Promise.resolve(text); },
    makeUrl: (text) => `blob:${text}`,
    revokeUrl: () => {},
    play: (url) => url === 'blob:旧' ? oldPlayback.promise : Promise.resolve(),
    pause: () => {},
    onState: () => {},
  });
  queue.start(['旧']);
  await tick();
  queue.start(['新']);
  await tick();
  oldPlayback.reject(new Error('旧音频失败'));
  await tick();
  assert.deepEqual(requests, ['旧', '新']);
  assert.equal(queue.state.status, 'playing');
});

test('a playback rejection from before pause cannot fail resumed playback', async () => {
  const firstPlayback = deferred();
  let plays = 0;
  const queue = createRealtimeAuditionQueue({
    request: async () => 'audio',
    makeUrl: () => 'blob:audio',
    revokeUrl: () => {},
    play: () => (++plays === 1 ? firstPlayback.promise : Promise.resolve()),
    pause: () => {},
    onState: () => {},
  });
  queue.start(['一']);
  await tick();
  queue.pause();
  queue.resume();
  firstPlayback.reject(new Error('旧播放失败'));
  await tick();
  assert.equal(queue.state.status, 'playing');
});

test('a failed segment can be retried without replaying completed segments', async () => {
  const h = harness();
  h.queue.start(['一', '二']);
  h.requests[0].resolve('one');
  await tick();
  h.requests[1].reject(new Error('模型错误'));
  await tick();
  h.queue.ended();
  assert.equal(h.queue.state.status, 'error');
  assert.equal(h.queue.state.index, 1);
  assert.match(h.queue.state.error, /模型错误/);
  h.queue.retry();
  assert.deepEqual(h.requests.map((item) => item.text), ['一', '二', '二']);
  h.requests[2].resolve('two');
  await tick();
  assert.deepEqual(h.played, ['blob:one', 'blob:two']);
});

test('a media decode error enters retry state and regenerates only the current segment', async () => {
  const h = harness();
  h.queue.start(['一', '二']);
  h.requests[0].resolve('one');
  await tick();
  h.queue.failPlayback('音频播放失败。');
  assert.equal(h.queue.state.status, 'error');
  assert.match(h.queue.state.error, /音频播放失败/);
  assert.deepEqual(h.revoked, ['blob:one']);
  assert.equal(h.requests[1].signal.aborted, true);
  h.queue.retry();
  assert.deepEqual(h.requests.map((item) => item.text), ['一', '二', '一']);
  h.requests[2].resolve('one-retry');
  await tick();
  assert.deepEqual(h.played, ['blob:one', 'blob:one-retry']);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadCallLogDetail } from './callLogDetails.js';

test('loads a transcript once per page and reuses the detail', async () => {
  const cache = new Map();
  let calls = 0;
  const fetchDetail = async () => {
    calls += 1;
    return { id: 'call-1', transcript: 'full transcript' };
  };
  assert.equal((await loadCallLogDetail('call-1', fetchDetail, cache)).transcript, 'full transcript');
  assert.equal((await loadCallLogDetail('call-1', fetchDetail, cache)).transcript, 'full transcript');
  assert.equal(calls, 1);
});

test('failed detail loads are retryable', async () => {
  const cache = new Map();
  let calls = 0;
  const fetchDetail = async () => {
    calls += 1;
    if (calls === 1) throw new Error('temporary failure');
    return { id: 'call-1', transcript: 'recovered' };
  };
  await assert.rejects(loadCallLogDetail('call-1', fetchDetail, cache), /temporary failure/);
  assert.equal((await loadCallLogDetail('call-1', fetchDetail, cache)).transcript, 'recovered');
  assert.equal(calls, 2);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { groupTranscriptTurns } from '../src/utils/callTranscript.js';

test('legacy realtime Agent subtitle fragments display as one utterance', () => {
  const turns = [
    { role: 'assistant', text: '哼', time: 0.2 },
    { role: 'assistant', text: '！', time: 0.3 },
    { role: 'assistant', text: '你好', time: 0.4 },
    { role: 'assistant', text: '哼！你好', time: 0.5 },
  ];
  assert.deepEqual(groupTranscriptTurns(turns, 'realtime'), [
    { role: 'assistant', text: '哼！你好', time: 0.2 },
  ]);
  assert.equal(turns[0].text, '哼');
});

test('legacy partial output is grouped without requiring a final event', () => {
  assert.deepEqual(groupTranscriptTurns([
    { role: 'assistant', text: '你', time: 0.2 },
    { role: 'assistant', text: '好', time: 0.3 },
    { role: 'assistant', text: '吗？', time: 0.4 },
  ], 'realtime').map((turn) => turn.text), ['你好吗？']);
});

test('a short corrected final subtitle replaces fragments without duplication', () => {
  assert.deepEqual(groupTranscriptTurns([
    { role: 'assistant', text: '你', time: 0.2 },
    { role: 'assistant', text: '好', time: 0.3 },
    { role: 'assistant', text: '你好！', time: 0.4 },
  ], 'realtime').map((turn) => turn.text), ['你好！']);
});

test('identical single-character deltas are not mistaken for a completed subtitle', () => {
  assert.deepEqual(groupTranscriptTurns([
    { role: 'assistant', text: '好', time: 0.2 },
    { role: 'assistant', text: '好', time: 0.3 },
  ], 'realtime').map((turn) => turn.text), ['好好']);
});

test('speaker changes and long pauses separate historical turns', () => {
  const turns = [
    { role: 'assistant', text: '你好', time: 0.2 },
    { role: 'user', text: '你好', time: 0.5 },
    { role: 'assistant', text: '有什么事', time: 0.7 },
    { role: 'assistant', text: '再见', time: 5.0 },
  ];
  assert.deepEqual(groupTranscriptTurns(turns, 'realtime'), turns);
});

test('an already complete long Agent turn is not merged with a short next turn', () => {
  const turns = [
    { role: 'assistant', text: '这是已经保存的完整回复内容，并且明确不是短字幕碎片。', time: 0.2 },
    { role: 'assistant', text: '好的', time: 0.5 },
  ];
  assert.deepEqual(groupTranscriptTurns(turns, 'realtime'), turns);
});

test('new turn-level records and pipeline records are left separate', () => {
  const turns = [
    { role: 'assistant', text: '你好', time: 0.2, granularity: 'turn' },
    { role: 'assistant', text: '再见', time: 0.5, granularity: 'turn' },
  ];
  assert.deepEqual(groupTranscriptTurns(turns, 'realtime'), turns);
  assert.deepEqual(groupTranscriptTurns(turns.map(({ granularity, ...turn }) => turn), 'pipeline'),
    turns.map(({ granularity, ...turn }) => turn));
});

test('call log view applies display-only transcript grouping', () => {
  const view = readFileSync(new URL('../src/views/CallLogListView.vue', import.meta.url), 'utf8');
  assert.match(view, /groupTranscriptTurns/);
  assert.match(view, /runtimeMode/);
});

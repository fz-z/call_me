const LEGACY_FRAGMENT_MAX_GAP_SECONDS = 2;
const LEGACY_FRAGMENT_MAX_LENGTH = 16;

/** Best-effort display grouping for old realtime logs with no response IDs. */
export function groupTranscriptTurns(turns, runtimeMode) {
  if (!Array.isArray(turns)) return [];
  if (runtimeMode !== 'realtime') return turns;

  const grouped = [];
  let chain = null;
  for (const original of turns) {
    if (!original || typeof original !== 'object') continue;
    const turn = { ...original };
    const previous = grouped.at(-1);
    const sameLegacyAgent = previous?.role === 'assistant'
      && turn.role === 'assistant'
      && previous.granularity !== 'turn'
      && turn.granularity !== 'turn';
    const gap = Number(turn.time) - Number(chain?.lastTime);
    const closeInTime = Number.isFinite(gap) && gap >= 0 && gap <= LEGACY_FRAGMENT_MAX_GAP_SECONDS;
    const canMerge = sameLegacyAgent && chain?.fragmented && !chain.closed && closeInTime;

    if (!canMerge) {
      grouped.push(turn);
      chain = turn.role === 'assistant' && turn.granularity !== 'turn'
        ? { lastTime: Number(turn.time), fragmentCount: 1, fragmented: String(turn.text || '').length <= LEGACY_FRAGMENT_MAX_LENGTH, closed: false }
        : null;
      continue;
    }

    const incoming = String(turn.text || '');
    const assembled = String(previous.text || '');
    // Old rows have no event type. Only treat a prefix match as a final subtitle
    // after multiple fragments; one repeated delta must not silently lose text.
    if (chain.fragmentCount > 1 && assembled.length >= 2 && incoming.startsWith(assembled)) {
      previous.text = incoming;
      chain.closed = true;
    } else {
      previous.text = assembled + incoming;
      chain.fragmentCount += 1;
    }
    chain.lastTime = Number(turn.time);
  }
  return grouped;
}

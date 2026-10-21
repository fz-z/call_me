export function createRealtimeAuditionQueue({ request, makeUrl, revokeUrl, play, pause, onState }) {
  let generation = 0;
  let segments = [];
  let index = 0;
  let status = 'idle';
  let error = '';
  let currentUrl = '';
  let nextUrl = '';
  let nextError = '';
  let inFlight = null;

  function snapshot() { return { status, index, total: segments.length, error }; }
  function emit() { onState(snapshot()); }
  function release(url) { if (url) revokeUrl(url); }
  function prefetch() {
    if (status === 'playing' && index + 1 < segments.length && !nextUrl && !nextError && !inFlight) {
      load(index + 1);
    }
  }
  function beginPlay() {
    const capturedGeneration = generation;
    const playingUrl = currentUrl;
    status = 'playing';
    error = '';
    emit();
    try {
      Promise.resolve(play(playingUrl)).catch((failure) => {
        if (generation !== capturedGeneration || currentUrl !== playingUrl || status !== 'playing') return;
        status = 'error';
        error = failure?.message || '音频播放失败。';
        emit();
      });
    } catch (failure) {
      status = 'error';
      error = failure?.message || '音频播放失败。';
      emit();
    }
    prefetch();
  }
  function load(target) {
    if (inFlight) return;
    const capturedGeneration = generation;
    const controller = new AbortController();
    inFlight = { target, controller };
    let pending;
    try { pending = request(segments[target], controller.signal); }
    catch (failure) { pending = Promise.reject(failure); }
    Promise.resolve(pending).then((audio) => {
      if (generation !== capturedGeneration || controller.signal.aborted) return;
      const url = makeUrl(audio);
      if (target === index) {
        currentUrl = url;
        if (status !== 'paused') beginPlay();
      } else if (target === index + 1) {
        nextUrl = url;
      } else {
        release(url);
      }
    }).catch((failure) => {
      if (generation !== capturedGeneration || controller.signal.aborted) return;
      const message = failure?.message || '实时音色试听失败，请重试。';
      if (target === index) {
        status = 'error';
        error = message;
        emit();
      } else if (target === index + 1) {
        nextError = message;
      }
    }).finally(() => {
      if (generation !== capturedGeneration || inFlight?.controller !== controller) return;
      inFlight = null;
      if (status === 'waiting' && target === index && currentUrl) beginPlay();
      prefetch();
    });
  }
  function stop() {
    generation++;
    inFlight?.controller.abort();
    inFlight = null;
    if (currentUrl) pause();
    release(currentUrl);
    release(nextUrl);
    currentUrl = '';
    nextUrl = '';
    nextError = '';
    segments = [];
    index = 0;
    status = 'idle';
    error = '';
    emit();
  }
  return {
    get state() { return snapshot(); },
    start(parts) {
      stop();
      segments = [...parts];
      if (!segments.length) return;
      status = 'loading';
      emit();
      load(0);
    },
    ended() {
      if (status !== 'playing') return;
      release(currentUrl);
      currentUrl = '';
      if (index + 1 === segments.length) {
        status = 'completed';
        emit();
        return;
      }
      index++;
      if (nextError) {
        status = 'error';
        error = nextError;
        nextError = '';
        emit();
      } else if (nextUrl) {
        currentUrl = nextUrl;
        nextUrl = '';
        beginPlay();
      } else {
        status = 'waiting';
        emit();
        if (!inFlight) load(index);
      }
    },
    pause() {
      if (status !== 'playing') return;
      pause();
      status = 'paused';
      emit();
    },
    resume() {
      if (status === 'paused' && currentUrl) beginPlay();
    },
    retry() {
      if (status !== 'error') return;
      error = '';
      if (currentUrl) { beginPlay(); return; }
      status = 'loading';
      emit();
      load(index);
    },
    stop,
    dispose: stop,
  };
}

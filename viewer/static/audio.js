/* Stream the guest's captured PCM with a small Web Audio scheduling buffer. */
(() => {
  const toggle = document.getElementById('audio-toggle');
  const replay = document.getElementById('audio-replay');
  const status = document.getElementById('audio-status');
  let context, enabled = false, generation = null, offset = 0, next = 0, epoch = 0;
  // Live joins the current DAC output; only Replay reads historical capture.
  let replaying = false, joinLive = true, silent = true;
  const sources = new Set();
  // How far behind the capture live playback joins. With the 0.08 s start margin in
  // poll(), it is what covers the time between polls (two requests, then a 150 ms
  // wait); 0.15 s only equalled that wait, with nothing left for the two requests.
  const LIVE_LAG = .3;
  function liveOffset(info) {
    const frameBytes = info.channels * info.sample_bytes;
    const frames = Math.floor(info.bytes / frameBytes);
    return Math.max(0, frames - Math.ceil(info.rate * LIVE_LAG)) * frameBytes;
  }
  let splitter, outputGains;
  function clear() {
    epoch++;
    for (const source of sources) source.stop();
    sources.clear();
    next = 0;
  }
  function paint() {
    const label = enabled ? 'Mute sound' : 'Enable sound';
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('aria-pressed', String(enabled));
    toggle.classList.toggle('is-connected', enabled);
    toggle.querySelector('.key-label').textContent = label;
  }
  async function enable() {
    context ||= new AudioContext();
    if (!splitter) {
      splitter = context.createChannelSplitter(2);
      const merger = context.createChannelMerger(2);
      outputGains = [context.createGain(), context.createGain()];
      outputGains.forEach((gain, channel) => {
        gain.gain.value = 0;
        splitter.connect(gain, channel); gain.connect(merger, 0, channel);
      });
      merger.connect(context.destination);
    }
    await context.resume();
    enabled = true;
    paint();
  }
  toggle.onclick = async () => {
    if (toggle.disabled) return;
    toggle.disabled = true;
    try {
      if (enabled) {
        enabled = false;
        clear();
        paint();
        status.textContent = 'Sound off';
      } else {
        replaying = false; joinLive = true;
        await enable();
      }
    } catch (e) {
      status.textContent = e.message;
      window.viewerControls?.error(e.message);
    } finally { toggle.disabled = false; }
  };
  replay.onclick = async () => {
    replaying = true; joinLive = false;
    clear();
    generation = null;
    offset = 0;
    try { await enable(); } catch (e) { status.textContent = e.message; window.viewerControls?.error(e.message); }
  };
  async function poll() {
    if (!enabled) return;
    const ticket = epoch;
    const info = await (await fetch('/audio.json')).json();
    if (!enabled || ticket !== epoch) return;
    if (info.running === false) { clear(); status.textContent = 'Player off'; return; }
    outputGains.forEach((gain, channel) => {
      gain.gain.setTargetAtTime(info.output_gain?.[channel] ?? 1, context.currentTime, .02);
    });
    if (!info.generation) { status.textContent = 'Waiting for a track…'; return; }
    if (context.state === 'suspended' || context.state === 'interrupted') {
      joinLive = !replaying; clear();
      status.textContent = 'Audio suspended — reconnect headphones'; return;
    }
    if (info.generation !== generation || info.bytes < offset) {
      clear();
      generation = info.generation;
      offset = replaying ? 0 : liveOffset(info);
      silent = true;
    }
    const bytesPerSecond = info.rate * info.channels * info.sample_bytes;
    // A hidden tab/network stall must not turn live audio into a delayed replay.
    // Keep a short scheduling cushion; only discard history after >2 s of lag.
    if (!replaying && (joinLive || (info.bytes - offset) / bytesPerSecond +
        Math.max(0, next - context.currentTime) > 2)) {
      clear(); offset = liveOffset(info); joinLive = false; silent = true;
    }
    const current = epoch;
    const buffered = Math.max(0, next - context.currentTime);
    const report = () => {
      status.textContent = `${info.rate / 1000} kHz · ${info.channels} ch · ${replaying ? 'replay' : 'live'}${silent ? ' · silence' : ''} · ${info.seconds.toFixed(1)} s captured`;
    };
    report();
    if (buffered > 0.7 || info.bytes <= offset) return;
    const response = await fetch(`/audio.pcm?generation=${encodeURIComponent(generation)}&offset=${offset}`);
    if (!response.ok) return;
    const raw = await response.arrayBuffer();
    if (!enabled || current !== epoch || !raw.byteLength) return;
    const width = info.sample_bytes, channels = info.channels;
    const frames = raw.byteLength / (width * channels);
    const buffer = context.createBuffer(channels, frames, info.rate);
    const view = new DataView(raw);
    let peak = 0;
    for (let c = 0; c < channels; c++) {
      const out = buffer.getChannelData(c);
      for (let i = 0; i < frames; i++) {
        const p = (i * channels + c) * width;
        if (width === 4) out[i] = view.getInt32(p, true) / 2147483648;
        else if (width === 3) out[i] = ((view.getUint8(p) | (view.getUint8(p+1)<<8) | (view.getInt8(p+2)<<16))) / 8388608;
        else if (width === 2) out[i] = view.getInt16(p, true) / 32768;
        else out[i] = view.getInt8(p) / 128;
        peak = Math.max(peak, Math.abs(out[i]));
      }
    }
    silent = peak === 0; report();
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(splitter);
    source.onended = () => sources.delete(source);
    sources.add(source);
    next = Math.max(next, context.currentTime + 0.08);
    source.start(next);
    next += frames / info.rate;
    offset += raw.byteLength;
  }
  async function loop() {
    try { await poll(); } catch (e) { if (enabled) status.textContent = `Audio: ${e.message}`; }
    setTimeout(loop, 150);
  }
  loop();
})();

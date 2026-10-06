/* Full lossless PNG frames, explicit decoding and a bounded latest-frame slot.
   The parts are read as plain bytes (/stream?raw=1): a multipart/x-mixed-replace body
   never reaches the page through fetch() in WebKit, so Safari stayed black. */
class FrameParser {
  constructor(onFrame) { this.onFrame = onFrame; this.buffer = new Uint8Array(); this.size = null; }
  push(chunk) {
    const joined = new Uint8Array(this.buffer.length + chunk.length);
    joined.set(this.buffer); joined.set(chunk, this.buffer.length); this.buffer = joined;
    for (;;) {
      if (this.size === null) {
        let end = -1;
        for (let i = 0; i + 3 < this.buffer.length; i++) {
          if (this.buffer[i] === 13 && this.buffer[i+1] === 10 &&
              this.buffer[i+2] === 13 && this.buffer[i+3] === 10) { end = i; break; }
        }
        if (end < 0) {
          if (this.buffer.length > 8192) throw new Error('Oversized frame header');
          return;
        }
        if (end > 8192) throw new Error('Oversized frame header');
        const header = new TextDecoder().decode(this.buffer.subarray(0, end));
        const match = header.match(/\r\nContent-Length: (\d+)$/im);
        if (!/^\r?\n?--FRAME\r\n/i.test(header) || !/\r\nContent-Type: image\/png\r\n/i.test(header) || !match) {
          throw new Error('Invalid PNG frame header');
        }
        this.size = Number(match[1]);
        if (this.size < 1 || this.size > 2 * 1024 * 1024) throw new Error('Invalid PNG frame size');
        this.buffer = this.buffer.subarray(end + 4);
      }
      if (this.buffer.length < this.size) return;
      const frame = this.buffer.slice(0, this.size);
      this.buffer = this.buffer.subarray(this.size);
      this.size = null;
      this.onFrame(frame);
    }
  }
}

class FrameStream {
  constructor(image, {fetch, decode, timers}) {
    this.image = image; this.displayed = null;
    this.fetch = fetch; this.decode = decode; this.timers = timers;
    this.run = null; this.retry = null; this.closed = false;
  }
  stop() {
    this.closed = true;
    this.timers.clear(this.retry); this.retry = null;
    this.run?.controller.abort(); this.run = null;
  }
  start() {
    this.stop(); this.closed = false;
    const run = this.run = {controller: new AbortController(), latest: null, drawing: false};
    this.read(run);
  }
  async draw(run) {
    if (run.drawing) return;
    run.drawing = true;
    try {
      while (run.latest && this.run === run) {
        const png = run.latest; run.latest = null;
        const bitmap = await this.decode(png);
        if (this.run === run) {
          this.image.src = bitmap.url;
          this.displayed?.close();
          this.displayed = bitmap; // Retain the displayed URL until replacement.
        } else { bitmap.close(); }
      }
    } catch (error) {
      this.failed(run);
    } finally { run.drawing = false; }
  }
  failed(run) {
    if (this.run !== run) return;
    run.controller.abort(); this.run = null;
    if (!this.closed && this.retry === null) {
      this.retry = this.timers.set(() => { this.retry = null; this.start(); }, 1000);
    }
  }
  async read(run) {
    let reader;
    try {
      const response = await this.fetch('/stream?raw=1', {signal: run.controller.signal, cache: 'no-store'});
      if (!response.ok || !response.headers.get('Content-Type')?.includes('boundary=FRAME')) {
        throw new Error('Frame stream unavailable');
      }
      reader = response.body.getReader();
      const parser = new FrameParser(png => {
        run.latest = png; // At most one pending frame, even while PNG decoding is slow.
        this.draw(run);
      });
      while (this.run === run) {
        const {value, done} = await reader.read();
        if (done) break;
        if (this.run === run) parser.push(value);
      }
    } catch (error) {
      // Retry both transport and decoder failures with a fresh full snapshot.
    } finally {
      if (reader) { try { await reader.cancel(); } catch (_) {} reader.releaseLock(); }
      this.failed(run);
    }
  }
}

if (typeof module !== 'undefined') module.exports = {FrameParser, FrameStream};
if (typeof document !== 'undefined') {
  const frames = new FrameStream(document.getElementById('scr'), {
    fetch: (...args) => fetch(...args),
    decode: async png => {
      const url = URL.createObjectURL(new Blob([png], {type: 'image/png'}));
      const preview = new Image();
      try {
        preview.src = url;
        await preview.decode();
        return {url, close: () => URL.revokeObjectURL(url)};
      } catch (error) { URL.revokeObjectURL(url); throw error; }
    },
    timers: {set: (fn, ms) => setTimeout(fn, ms), clear: id => clearTimeout(id)}
  });
  window.addEventListener('viewer-reconnected', () => frames.start());
  window.addEventListener('pagehide', () => frames.stop());
  window.addEventListener('pageshow', event => { if (event.persisted) frames.start(); });
  frames.start();
}

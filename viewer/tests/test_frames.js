const {test} = require('node:test');
const assert = require('node:assert/strict');
const {FrameParser, FrameStream} = require('../static/frames.js');
const tick = () => new Promise(resolve => setImmediate(resolve));
const part = bytes => Buffer.concat([Buffer.from(`--FRAME\r\nContent-Type: image/png\r\nContent-Length: ${bytes.length}\r\n\r\n`), bytes, Buffer.from('\r\n')]);

test('PNG framing works across every byte boundary and coalesced frames', () => {
  const first = Buffer.from([0, 13, 10, 255]), second = Buffer.from('next PNG');
  const wire = Buffer.concat([part(first), part(second)]);
  for (const size of [1, 2, 7, wire.length]) {
    const frames = [], parser = new FrameParser(frame => frames.push(Buffer.from(frame)));
    for (let i = 0; i < wire.length; i += size) parser.push(wire.subarray(i, i + size));
    assert.deepEqual(frames, [first, second]);
  }
});

test('a complete PNG is delivered immediately without another boundary', () => {
  const png = Buffer.from('PNG'), frames = [], parser = new FrameParser(frame => frames.push(Buffer.from(frame)));
  const wire = part(png);
  parser.push(wire.subarray(0, wire.length - 3));
  assert.equal(frames.length, 0);
  parser.push(wire.subarray(wire.length - 3, wire.length - 2));
  assert.deepEqual(frames, [png]);
});

test('invalid headers and unbounded frames are rejected', () => {
  for (const data of [Buffer.alloc(8193, 65),
    Buffer.from('--FRAME\r\nContent-Type: image/png\r\nContent-Length: 999999999\r\n\r\n'),
    Buffer.from('--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: 3\r\n\r\n')]) {
    assert.throws(() => new FrameParser(() => {}).push(data));
  }
});

function fixture(decode) {
  const requests = [], drawn = [], tasks = new Map(); let id = 0;
  const player = new FrameStream({set src(url) {drawn.push(url);}}, {
    fetch: (url, options) => { requests.push({url, options}); return new Promise(() => {}); },
    decode: decode || (async png => ({url:png, close() {this.closed = true;}})),
    timers: {set: fn => {tasks.set(++id, fn); return id;}, clear: id => tasks.delete(id)}
  });
  return {player, requests, drawn, tasks};
}

test('slow decoding retains only the newest pending frame and releases replaced images', async () => {
  let resolve;
  const decoded = [], f = fixture(png => {decoded.push(png); return new Promise(r => {resolve = r;});});
  f.player.start(); const run = f.player.run;
  run.latest = 'first'; const drawing = f.player.draw(run);
  run.latest = 'second'; f.player.draw(run);
  run.latest = 'latest'; f.player.draw(run);
  const first = {url:'first', close() {this.closed = true;}};
  resolve(first); await tick();
  assert.deepEqual(decoded, ['first', 'latest']);
  assert.equal(first.closed, undefined); // The visible URL remains valid.
  const last = {url:'last', close() {this.closed = true;}};
  resolve(last); await drawing;
  assert.deepEqual(f.drawn, ['first', 'last']);
  assert.equal(first.closed, true);
  assert.equal(last.closed, undefined);
  f.player.stop();
});

test('an old decode cannot overwrite a reconnected stream', async () => {
  let resolve;
  const f = fixture(() => new Promise(r => {resolve = r;}));
  f.player.start(); const old = f.player.run;
  old.latest = 'old'; const drawing = f.player.draw(old);
  f.player.start();
  assert.equal(old.controller.signal.aborted, true);
  const bitmap = {close() {this.closed = true;}};
  resolve(bitmap); await drawing;
  assert.deepEqual(f.drawn, []);
  assert.equal(bitmap.closed, true);
  f.player.failed(old);
  assert.equal(f.tasks.size, 0);
  f.player.stop();
});

test('errors retry once and leaving the page cancels reconnection', () => {
  const f = fixture();
  f.player.start(); const run = f.player.run;
  f.player.failed(run); f.player.failed(run);
  assert.equal(f.tasks.size, 1);
  assert.equal(run.controller.signal.aborted, true);
  f.player.stop();
  assert.equal(f.tasks.size, 0);
  f.player.start();
  assert.equal(f.requests.length, 2);
  assert(f.requests.every(r => r.url === '/stream?raw=1'));   // plain bytes: WebKit's fetch() swallows multipart
  f.player.stop();
});

test('fetch reader presents a complete frame and cancels on shutdown', async () => {
  const f = fixture(); let reads = 0, cancelled = false, released = false, finish;
  f.player.fetch = async () => ({ok: true, headers: new Map([['Content-Type', 'application/octet-stream; boundary=FRAME']]),
    body: {getReader: () => ({
      read: async () => ++reads === 1 ? {value: part(Buffer.from('png')), done: false} : new Promise(r => {finish = r;}),
      cancel: async () => {cancelled = true;}, releaseLock: () => {released = true;}
    })}});
  f.player.start(); await tick();
  assert.equal(f.drawn.length, 1);
  f.player.stop(); finish({done: true}); await tick();
  assert.equal(cancelled, true); assert.equal(released, true);
  assert.equal(f.tasks.size, 0);
});

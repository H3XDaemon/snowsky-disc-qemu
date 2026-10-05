const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('browser routes PCM through DAC gains, updates them and stops when guest powers off', async () => {
  const elements = {}, timers = [], gains = [], sources = [];
  let splitter, info = {generation:'test', bytes:8, channels:2, sample_bytes:4,
    rate:44100, seconds:1, output_gain:[.25,.5], running:true};
  function node() {return {connections:[], connect(...args) {this.connections.push(args);}};}
  class AudioContext {
    constructor() {this.currentTime=0; this.destination=node();}
    async resume() {}
    createChannelSplitter() {splitter=node(); return splitter;}
    createChannelMerger() {return node();}
    createGain() {
      const n=node(); n.gain={value:1, setTargetAtTime(value) {this.value=value;}};
      gains.push(n);return n;
    }
    createBuffer(channels, frames) {return {getChannelData:() => new Float32Array(frames)};}
    createBufferSource() {
      const n=node(); n.start=()=>{}; n.stop=()=>{n.stopped=true;}; sources.push(n);return n;
    }
  }
  const context = vm.createContext({AudioContext, DataView, Set,
    document:{getElementById: id => elements[id] ||= {setAttribute() {},classList:{toggle() {}},querySelector:()=>({})}},
    fetch:async path => ({ok:true, json:async()=>info, arrayBuffer:async()=>new ArrayBuffer(8)}),
    setTimeout:fn=>timers.push(fn)});
  vm.runInContext(fs.readFileSync(require.resolve('../static/audio.js'),'utf8'), context);
  await new Promise(resolve=>setImmediate(resolve));
  await elements['audio-toggle'].onclick();
  await timers.shift()();
  assert.deepEqual(gains.map(n=>n.gain.value), [.25,.5]);
  assert.equal(sources[0].connections[0][0], splitter);
  info={...info, output_gain:[.1,.2]};
  await timers.shift()();
  assert.deepEqual(gains.map(n=>n.gain.value), [.1,.2]);
  info={...info, running:false};
  await timers.shift()();
  assert.equal(sources[0].stopped, true);
  assert.equal(elements['audio-status'].textContent, 'Player off');
});

function audioFixture() {
  const rate = 44100, bytesPerSecond = rate * 8;
  const nodes = {}, timers = [], requests = [], sources = [];
  let info = {generation:'one',bytes:500*bytesPerSecond,channels:2,sample_bytes:4,
    rate,seconds:500,running:true,output_gain:[1,1]};
  let audioContext, zeros = false;
  class AudioContext {
    constructor(){audioContext=this;this.currentTime=0;this.state='running';this.destination={};}
    async resume(){this.state='running';}
    createChannelSplitter(){return {connect(){}};}
    createChannelMerger(){return {connect(){}};}
    createGain(){return {connect(){},gain:{setTargetAtTime(){}}};}
    createBuffer(channels,frames){return {getChannelData:()=>new Float32Array(frames)};}
    createBufferSource(){const s={connect(){},start(){},stop(){this.stopped=true;}};sources.push(s);return s;}
  }
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/audio.js'),'utf8'),{
    AudioContext,DataView,Set,window:{},
    document:{getElementById:id=>nodes[id] ||= {setAttribute(){},classList:{toggle(){}},querySelector:()=>({})}},
    setTimeout:fn=>timers.push(fn),
    fetch:async url=>{
      requests.push(url);
      const raw=new ArrayBuffer(8);if(!zeros)new DataView(raw).setInt32(0,2**30,true);
      return {ok:true,json:async()=>({...info}),arrayBuffer:async()=>raw};
    }
  });
  return {nodes,requests,sources,bytesPerSecond,
    get context(){return audioContext;},
    update(change){Object.assign(info,change);}, silence(value){zeros=value;},
    async tick(){await new Promise(resolve=>setImmediate(resolve)); await timers.shift()();},
    offsets(){return requests.filter(u=>u.startsWith('/audio.pcm')).map(u=>Number(new URL(u,'http://test').searchParams.get('offset')));}};
}

test('Enable joins current output after a long capture; Replay alone starts at zero', async()=>{
  const f=audioFixture();
  await f.nodes['audio-toggle'].onclick();await f.tick();
  const [first]=f.offsets();
  assert.equal(first,Math.floor((500-.3)*f.bytesPerSecond));
  assert.equal(first%8,0);
  assert.match(f.nodes['audio-status'].textContent,/live/);
  assert.doesNotMatch(f.nodes['audio-status'].textContent,/silence/);
  await f.nodes['audio-replay'].onclick();await f.tick();
  assert.equal(f.offsets().at(-1),0);
  assert.match(f.nodes['audio-status'].textContent,/replay/);
  await f.nodes['audio-toggle'].onclick();
  f.update({bytes:600*f.bytesPerSecond,seconds:600});
  await f.nodes['audio-toggle'].onclick();await f.tick();
  assert.equal(f.offsets().at(-1),Math.floor((600-.3)*f.bytesPerSecond));
});

test('Live drops stale scheduled history after stalls while Replay preserves it',async()=>{
  const f=audioFixture();
  await f.nodes['audio-toggle'].onclick();await f.tick();
  f.context.currentTime=5;f.update({bytes:505*f.bytesPerSecond,seconds:505});
  await f.tick();
  assert(f.sources[0].stopped);
  assert.equal(f.offsets().at(-1),Math.floor((505-.3)*f.bytesPerSecond));
  await f.nodes['audio-replay'].onclick();await f.tick();
  f.context.currentTime+=5;await f.tick();
  assert.equal(f.offsets().at(-1),8);
});

test('Capture rollover rejoins live and zero PCM is reported as silence',async()=>{
  const f=audioFixture();
  await f.nodes['audio-toggle'].onclick();await f.tick();
  f.update({generation:'two',bytes:3*f.bytesPerSecond,seconds:3});f.silence(true);
  await f.tick();
  assert.equal(f.offsets().at(-1),Math.floor((3-.3)*f.bytesPerSecond));
  assert.match(f.nodes['audio-status'].textContent,/live · silence/);
  f.context.state='suspended';const count=f.offsets().length;
  await f.tick();assert.equal(f.offsets().length,count);
  assert.match(f.nodes['audio-status'].textContent,/Audio suspended/);
});

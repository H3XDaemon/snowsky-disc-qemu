const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const frontend = path.join(__dirname,'../frontend');
const theme = require('../frontend/theme.js');

test('saved connection is only a validated local draft; invalid or unavailable storage is ignored',async()=>{
  const {normalizeConnection,savedConnection}=await import('../frontend/connection.mjs');
  const config={host:'192.168.2.10',tcp_port:12100,http_port:12103};
  assert.deepEqual(savedConnection({getItem:()=>JSON.stringify(config)}),config);
  assert.equal(savedConnection({getItem:()=>'{broken'}),null);
  assert.equal(savedConnection({getItem:()=>{throw new Error('blocked');}}),null);
  for(const host of ['0.0.0.0','224.0.0.255','8.8.8.8','https://192.168.2.10','192.168.02.10','192.168.2.999'])
    assert.equal(normalizeConnection({...config,host}),null);
  for(const tcp_port of [true,0,65536,'12100']) assert.equal(normalizeConnection({...config,tcp_port}),null);
});

test('physical and emulator drafts stay separate; explicit server target wins over saved drafts',async()=>{
  const {savedConnection,connectionDraft}=await import('../frontend/connection.mjs');
  const player={host:'192.168.2.10',tcp_port:12100,http_port:12103};
  const emulator={host:'127.0.0.1',tcp_port:12100,http_port:12113};
  const storage={getItem:key=>JSON.stringify(key.endsWith('.emulator')?emulator:player)};
  assert.deepEqual(savedConnection(storage),player);
  assert.deepEqual(savedConnection(storage,true),emulator);
  assert.equal(savedConnection({getItem:()=>JSON.stringify(emulator)}),null);
  assert.deepEqual(connectionDraft({endpoint:'',http_port:12103},null),{...player,host:''});
  assert.deepEqual(connectionDraft({endpoint:'',http_port:12103},player),player);
  assert.deepEqual(connectionDraft({endpoint:emulator.host,tcp_port:12100,http_port:12113},player),emulator);
  assert.deepEqual(connectionDraft({demo:true},player),{...player,host:''});
});

test('theme preferences distinguish system appearance from explicit choices',()=>{
  assert.equal(theme.resolve('system',true),'dark');
  assert.equal(theme.resolve('system',false),'light');
  assert.equal(theme.resolve('light',true),'light');
  assert.equal(theme.resolve('dark',false),'dark');
  assert.equal(theme.resolve('corrupt',true),'dark');
});
test('theme survives reload, follows system only when selected, and tolerates blocked storage',()=>{
  let saved='dark', onSystem;
  const listeners={};
  const window={document:{documentElement:{dataset:{}},querySelector:()=>({setAttribute(){}})},
    matchMedia:()=>({matches:false,addEventListener:(_,fn)=>onSystem=fn}),
    localStorage:{getItem:()=>saved,setItem:(_,v)=>{saved=v;}},
    addEventListener:(name,fn)=>listeners[name]=fn,dispatchEvent(){}};
  const execute=()=>vm.runInNewContext(fs.readFileSync(path.join(frontend,'theme.js'),'utf8'),{window,CustomEvent:class {}});
  execute(); assert.equal(window.document.documentElement.dataset.theme,'dark');
  window.DiscTheme.set('light'); onSystem();
  assert.equal(window.document.documentElement.dataset.theme,'light');
  assert.equal(saved,'light'); execute(); assert.equal(window.DiscTheme.get(),'light');
  listeners.storage({key:'disc-web.appearance',newValue:'dark'});
  assert.equal(window.document.documentElement.dataset.theme,'dark');
  window.localStorage.setItem=()=>{throw new Error('blocked');};
  assert.doesNotThrow(()=>window.DiscTheme.set('system'));
});
test('RU and EN have matching messages, valid static markers and plural counts',async()=>{
  const ru=JSON.parse(fs.readFileSync(path.join(frontend,'locales/ru.json')));
  const en=JSON.parse(fs.readFileSync(path.join(frontend,'locales/en.json')));
  assert.deepEqual(Object.keys(ru).sort(),Object.keys(en).sort());
  const html=fs.readFileSync(path.join(frontend,'index.html'),'utf8');
  for (const [,key] of html.matchAll(/data-i18n(?:-[\w-]+)?="([^"]+)"/g)) assert.ok(key in en,key);
  const {message}=await import('../frontend/i18n.mjs');
  assert.equal(message(ru,'ru','track_count',{count:1}),'1 трек');
  assert.equal(message(ru,'ru','track_count',{count:2}),'2 трека');
  assert.equal(message(ru,'ru','track_count',{count:5}),'5 треков');
  assert.equal(message(en,'en','track_count',{count:1}),'1 track');
  assert.equal(message(en,'en','track_count',{count:5}),'5 tracks');
  assert.equal(message(en,'en','open_item',{name:'Тихий океан'}),'Open Тихий океан');
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'), fs=require('node:fs');

test('SSE mirrors backlight and peripherals with no extra controls or polling',()=>{
  const nodes={}, requests=[];
  function element(id) {
    return nodes[id] ||= {style:{}, attributes:{}, label:{}, classes:new Set(),
      classList:{toggle(name,on){on?nodes[id].classes.add(name):nodes[id].classes.delete(name);}},
      setAttribute(name,value){this.attributes[name]=value;}, querySelector(){return this.label;}};
  }
  const window={};
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/controls.js'),'utf8'),{
    document:{getElementById:element}, window, fetch:path=>requests.push(path)
  });
  assert(element('usb-toggle').disabled);
  const state={running:true,screen_on:true,brightness:40,sd_available:true,sd_inserted:true,usb_connected:false};
  window.viewerControls.update(state);
  assert.equal(element('scr').style.filter,'brightness(1)');
  assert.equal(element('sd-toggle').attributes['aria-label'],'Eject SD card');
  window.viewerControls.update({...state,brightness:5,sd_inserted:false,usb_connected:true});
  assert(Math.abs(Number(element('scr').style.filter.match(/[\d.]+/)[0]) - .3) < 1e-9);
  assert(element('sd-toggle').classes.has('is-ejected'));
  assert(element('usb-toggle').classes.has('is-connected'));
  assert.equal(element('usb-toggle').attributes['aria-pressed'],'true');
  window.viewerControls.update({...state,peripheral_transition:'Ejecting SD card…'});
  assert(element('usb-toggle').disabled);assert(element('sd-toggle').disabled);
  window.viewerControls.unavailable();
  assert(element('usb-toggle').disabled);
  assert.deepEqual(requests,[]);
  assert(!Object.hasOwn(nodes,'volume'));assert(!Object.hasOwn(nodes,'brightness'));
});

test('Ejecting takes a second click within 3 s; inserting does not',async()=>{
  const nodes={}, posts=[], timers=new Map();
  let next=1;
  function element(id) {
    return nodes[id] ||= {style:{}, attributes:{}, label:{}, classes:new Set(), textContent:'',
      classList:{toggle(name,on){on?nodes[id].classes.add(name):nodes[id].classes.delete(name);}},
      setAttribute(name,value){this.attributes[name]=value;}, querySelector(){return this.label;}};
  }
  const window={}, settle=()=>new Promise(resolve=>setImmediate(resolve));
  const fetch=async(path,init)=>{posts.push(JSON.parse(init.body));return {ok:true,json:async()=>state};};
  const expire=()=>{const [id,fn]=[...timers][0];timers.delete(id);fn();};
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/controls.js'),'utf8'),{
    document:{getElementById:element}, window, fetch,
    setTimeout:(fn,ms)=>{assert.equal(ms,3000);timers.set(next,fn);return next++;},
    clearTimeout:id=>timers.delete(id)
  });
  let state={sd_available:true,sd_inserted:true,usb_connected:true};
  window.viewerControls.update(state);
  const click=async()=>{element('sd-toggle').onclick();await settle();};
  await click();
  assert.deepEqual(posts,[]);
  assert.equal(element('control-error').textContent,'Click the card again to eject');
  expire();                                             // window closed: hint gone, nothing ejected
  assert.equal(element('control-error').textContent,'');
  await click();await click();                          // within the window
  assert.deepEqual(posts,[{name:'sd',inserted:false}]);
  assert.equal(timers.size,0);
  state={...state,sd_inserted:false};window.viewerControls.update(state);
  await click();                                        // inserting needs no confirmation
  assert.deepEqual(posts.at(-1),{name:'sd',inserted:true});
  assert.equal(timers.size,0);
});

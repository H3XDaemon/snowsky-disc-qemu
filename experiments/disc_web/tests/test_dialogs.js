const {test}=require('node:test');
const assert=require('node:assert/strict');

async function fixture() {
  const {setupDialogs}=await import('../frontend/dialogs.mjs');
  let notify;
  const classes=new Set(),styles=new Map(),scrolls=[];
  const root={classList:{add:name=>classes.add(name),remove:name=>classes.delete(name)},
    style:{setProperty:(key,value)=>styles.set(key,value),removeProperty:key=>styles.delete(key)}};
  function dialog() {
    const listeners={};
    const item={open:false,addEventListener:(name,fn)=>listeners[name]=fn,
      getBoundingClientRect:()=>({left:100,right:400,top:100,bottom:400}),
      close(){this.open=false;listeners.close();},
      emit(name,extra={}){listeners[name]({target:item,clientX:50,clientY:50,button:0,isPrimary:true,...extra});}};
    return item;
  }
  const first=dialog(),second=dialog();
  const win={scrollX:0,scrollY:640,location:{href:'#view=tracks'},scrollTo:value=>scrolls.push(value),
    MutationObserver:class {constructor(callback){notify=callback;} observe(){}}};
  setupDialogs({documentElement:root,querySelectorAll:()=>[first,second]},win);
  return {first,second,classes,styles,scrolls,win,notify:()=>notify()};
}

test('backdrop dismissal excludes padding, inside-to-outside drags and cancelled pointers',async()=>{
  const {first,notify}=await fixture();
  first.open=true;notify();
  const click=(down,up)=>{first.emit('pointerdown',down);first.emit('click',up);};
  click({clientX:120,clientY:120},{clientX:120,clientY:120});
  assert.equal(first.open,true);
  click({target:{}},{clientX:50,clientY:50});
  assert.equal(first.open,true);
  click({}, {clientX:20,clientY:20});
  assert.equal(first.open,true);
  first.emit('pointerdown');first.emit('pointercancel');first.emit('click');
  assert.equal(first.open,true);
  click({button:2},{});
  assert.equal(first.open,true);
  click({},{});
  assert.equal(first.open,false);
});

test('scroll position survives stacked dialogs and unlocks only after the last closes',async()=>{
  const {first,second,notify,classes,styles,scrolls,win}=await fixture();
  first.open=true;notify();
  assert.equal(classes.has('modal-open'),true);
  assert.equal(styles.get('--dialog-scroll-y'),'-640px');
  win.scrollY=0;
  second.open=true;notify();first.close();
  assert.equal(classes.has('modal-open'),true);
  assert.equal(scrolls.length,0);
  second.close();
  assert.equal(classes.has('modal-open'),false);
  assert.equal(styles.has('--dialog-scroll-y'),false);
  assert.deepEqual(scrolls,[{left:0,top:640,behavior:'instant'}]);
  first.open=true;notify();win.location.href='#view=albums';first.close();
  assert.equal(scrolls.at(-1).top,0);
});

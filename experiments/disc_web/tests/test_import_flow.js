const {test} = require('node:test');
const assert = require('node:assert/strict');
const flow = import('../frontend/import-flow.mjs');
const ready={connection:'ready',generation:5,catalogue:{available:true,phase:'done',stale:true}};
const scan={id:'scan',kind:'scan',generation:5,phase:'done'};

test('upload, scan and sync have distinct completion evidence, including partial batches',async()=>{
  const {importFlow}=await flow;
  const selected={files:[{id:'one',phase:'done'},{id:null,phase:'waiting'}],batchGeneration:5};
  assert.equal(importFlow(ready,selected).step,0);
  assert.deepEqual(importFlow(ready,selected).counts,{total:2,done:1,waiting:1});
  selected.files[1]={id:'two',phase:'done'};
  assert.equal(importFlow(ready,selected).step,1);
  assert.equal(importFlow(ready,selected).canSync,false);
  const scanned={...ready,job:scan};
  assert.equal(importFlow(scanned,selected).canSync,true);
  assert.equal(importFlow(scanned,selected).complete,false); // old snapshot is stale
  assert.equal(importFlow({...scanned,catalogue:{...ready.catalogue,phase:'syncing'}},selected).canSync,false);
  assert.equal(importFlow({...scanned,catalogue:{...ready.catalogue,phase:'failed'}},selected).message,'import_flow_sync_failed');
  const synced={...scanned,catalogue:{...ready.catalogue,stale:false}};
  assert.equal(importFlow(synced,selected).complete,true);
  selected.files[1].phase='uncertain';
  assert.equal(importFlow(synced,selected).message,'import_flow_partial_saved');
});

test('uncertain jobs, demo, changed connection and new selections never imply completed import',async()=>{
  const {importFlow}=await flow;
  for(const phase of ['scanning','uncertain','not_sent']) {
    const result=importFlow({...ready,job:{...scan,phase}});
    assert.equal(result.canSync,false); assert.equal(result.complete,false);
  }
  const demo=importFlow({...ready,demo:true,job:scan});
  assert.equal(demo.canSync,false); assert.equal(demo.complete,false);
  assert.equal(demo.message,'import_flow_demo');
  const switched=importFlow({...ready,generation:6,job:scan},{files:[{phase:'waiting'}],batchGeneration:5});
  assert.equal(switched.changed,true); assert.equal(switched.canSync,false);
  const newSelection=importFlow({...ready,generation:6,job:scan},{files:[{phase:'waiting'}],selectionJob:'scan'});
  assert.equal(newSelection.changed,false); assert.equal(newSelection.step,0);
  const stopped=importFlow({...ready,job:{id:'two',kind:'upload',generation:5,phase:'uncertain'}},
    {files:[{id:'one',phase:'done'},{id:'two',phase:'receiving'},{phase:'waiting'}]});
  assert.equal(stopped.message,'import_flow_check');
  assert.deepEqual(stopped.counts,{total:3,done:1,waiting:1});
});

test('reload exposes only the latest observed file or scan, not a fabricated restored batch',async()=>{
  const {importFlow}=await flow;
  const latest=importFlow({...ready,job:{id:'last',kind:'upload',generation:5,phase:'done'}});
  assert.equal(latest.step,1); assert.equal(latest.counts.total,0);
  assert.equal(latest.canSync,false);
  assert.equal(importFlow({...ready,job:scan}).canSync,true);
});

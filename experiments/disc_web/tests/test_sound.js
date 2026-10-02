const {test}=require('node:test');
const assert=require('node:assert/strict');
test('sound values require observed bounded integers; no defaults from incomplete or failed reads',async()=>{
  const {soundValues,balanceLabel}=await import('../frontend/sound.mjs');
  const settings={gain:1,balance:-20,filter:5,dre:0};
  const observed={status:'observed',confirmation:{settings}};
  assert.deepEqual(soundValues(observed),settings);
  for(const patch of [{gain:true},{filter:6},{balance:21},{dre:null}])
    assert.equal(soundValues({...observed,confirmation:{settings:{...settings,...patch}}}),null);
  for(const value of [null,{}, {...observed,status:'not_sent'}, {status:'observed',confirmation:{settings:{gain:0}}}])
    assert.equal(soundValues(value),null);
  assert.equal(balanceLabel(-20),'L20');assert.equal(balanceLabel(0),'0');assert.equal(balanceLabel(20),'R20');
});

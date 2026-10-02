const {test} = require('node:test');
const assert = require('node:assert/strict');
const core = import('../frontend/core.mjs');

test('request IDs work on HTTP LAN origins without randomUUID and retain random entropy', async () => {
  const {requestId}=await import('../frontend/request.mjs');
  let calls=0;
  const httpCrypto={getRandomValues(bytes) {
    assert.equal(bytes.length,16);
    bytes.set(Array.from({length:16},(_,i)=>i+calls++));
    return bytes;
  }};
  const first=requestId(httpCrypto), second=requestId(httpCrypto);
  assert.match(first,/^[0-9a-f]{32}$/);
  assert.match(second,/^[0-9a-f]{32}$/);
  assert.notEqual(first,second);
  assert.throws(()=>requestId({})); // No weak or constant fallback.
});

test('saved artwork is local and cover identity distinguishes paths, duplicate positions and reconnects', async () => {
  const {coverIdentity,artworkSource}=await core;
  const track={title:'Same',artist:'Artist',album:'Album',path:'/tmp/sdcard/one.flac',queue_position:0,duration_ms:5000};
  const state={generation:1,playback:{track}};
  for(const change of [{path:'/tmp/sdcard/two.flac'},{queue_position:1},{duration_ms:6000}]) {
    assert.notEqual(coverIdentity(state),coverIdentity({...state,playback:{track:{...track,...change}}}));
  }
  assert.notEqual(coverIdentity(state),coverIdentity({...state,generation:2}));
  assert.equal(artworkSource('/api/artwork/'+'a'.repeat(64)),'/api/artwork/'+'a'.repeat(64));
  for(const src of ['https://example.com/cover.jpg','data:image/svg+xml,x','/api/artwork/../state','/api/artwork/not-a-hash']) {
    assert.equal(artworkSource(src),null);
  }
});

test('import rejects unsafe paths, duplicate names and oversized batches before transmission', async () => {
  const {validFiles,jobActive}=await import('../frontend/imports.mjs');
  const file={name:'Музыка — test.wav',size:500};
  assert.equal(validFiles([file]),true);
  assert.equal(validFiles([{...file,size:1024**3}]),true);
  assert.equal(validFiles([{...file,webkitRelativePath:'Album/Disc 1/Track.wav'},{...file,webkitRelativePath:'Album/Disc 2/Track.wav'}]),true);
  assert.equal(validFiles([{name:'Album.cue',size:120,webkitRelativePath:'Album/Album.cue'}]),false);
  assert.equal(validFiles([{...file,webkitRelativePath:'Album/../Track.wav'}]),false);
  assert.equal(validFiles([{...file,webkitRelativePath:'/Album/Track.wav'}]),false);
  for(const files of [[],Array(31).fill(file),[file,{...file,name:file.name.toUpperCase()}],
    [{...file,name:'../Music.wav'}],[{...file,name:'Music.exe'}],[{...file,size:0}],
    [{...file,size:2**31}],[{...file,name:'x'.repeat(241)+'.wav'}]]) assert.equal(validFiles(files),false);
  assert.equal(jobActive({phase:'verifying'}),true);
  assert.equal(jobActive({phase:'scanning'}),true);
  for(const phase of ['done','uncertain','not_sent']) assert.equal(jobActive({phase}),false);
});

test('catalog metadata is escaped before HTML insertion', async () => {
  const {escapeHTML} = await core;
  assert.equal(escapeHTML('<img src=x onerror="alert(1)"> &'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp;');
});
test('missing timing stays unknown and elapsed time uses whole seconds', async () => {
  const {timeLabel} = await core;
  assert.equal(timeLabel(null), '—:—');
  assert.equal(timeLabel(NaN), '—:—');
  assert.equal(timeLabel(-1), '—:—');
  assert.equal(timeLabel(125.9), '2:05');
});
test('search combines case-insensitive title and artist without changing identities', async () => {
  const {filterItems,searchKind} = await core;
  const items = [{id:'1',title:'Тихий океан',artist:'Берег'}, {id:'2',title:'Океан',artist:'Другой'}];
  assert.deepEqual(filterItems(items, '  ОКЕАН берег '), [items[0]]);
  assert.deepEqual(filterItems(items, ''), items);
  assert.deepEqual(filterItems(items, '<script>'), []);
  const albums=[{type:'album',title:'Коллекция',artists:['Первый','Второй']},
    {type:'album',title:'Второй альбом',artist:'Другой'}];
  assert.deepEqual(filterItems(albums,'коллекция второй'),[albums[0]]);
  assert.strictEqual(filterItems(albums,'коллекция')[0],albums[0]);
  assert.deepEqual(filterItems([{type:'artist',title:'Исполнитель',album:'Другой'}],'другой'),[]);
  assert.deepEqual(filterItems([{type:'playlist',title:'Мой микс'}],'МИКС'),[{type:'playlist',title:'Мой микс'}]);
  for(const view of ['home','albums','artist']) assert.equal(searchKind(view),'albums');
  for(const view of ['tracks','album','favorites','playlist']) assert.equal(searchKind(view),'tracks');
  assert.equal(searchKind('artists'),'artists');
  assert.equal(searchKind('playlists'),'playlists');
});
test('navigation preserves literal names and artist scope through deep links', async () => {
  const {routeHash,parseRoute} = await core;
  const route = {view:'album',name:'A & B / Тихий океан',artist:'Artist + Guest'};
  assert.deepEqual(parseRoute(routeHash(route)), route);
  assert.equal(parseRoute('#view=raw-command').view, 'home');
});
test('seek uses observed duration and invalidates a draft on track/source/reconnect changes', async () => {
  const {trackDuration,seekAllowed,playbackIdentity} = await core;
  const state={connection:'ready',generation:2,playback:{state:'paused',source:3,track:{title:'Track',duration_ms:120000}}};
  assert.equal(trackDuration(state.playback.track),120);
  assert.equal(seekAllowed(state),true);
  for(const altered of [
    {...state,connection:'reconnecting'},
    {...state,playback:{...state.playback,state:'loading'}},
    {...state,playback:{...state.playback,track:{title:'Unknown duration'}}}
  ]) assert.equal(seekAllowed(altered),false);
  for(const altered of [
    {...state,generation:3},
    {...state,playback:{...state.playback,source:0}},
    {...state,playback:{...state.playback,track:{...state.playback.track,title:'Other'}}}
  ]) assert.notEqual(playbackIdentity(altered),playbackIdentity(state));
  assert.equal(playbackIdentity({...state,playback:{...state.playback,position_ms:20000}}),playbackIdentity(state));
});

test('catalog columns require observed metadata, not fabricated album or duration values', async () => {
  const {trackColumns} = await core;
  assert.deepEqual(trackColumns([{title:'Track',album:null,duration:null}]),{album:false,duration:false});
  assert.deepEqual(trackColumns([{album:'Collection',duration:null}]),{album:true,duration:false});
  assert.deepEqual(trackColumns([{duration:0},{duration:123}]),{album:false,duration:true});
  assert.deepEqual(trackColumns([{duration:NaN},{duration:-1}]),{album:false,duration:false});
});

test('busy reads wait within a bound; mutations and transport failures are never replayed', async () => {
  const {requestJSON}=await import('../frontend/request.mjs');
  let calls=0;
  const busy=async()=>{calls++;return {status:409,ok:false,json:async()=>({})};};
  const pause=async()=>{};
  await assert.rejects(requestJSON('/api/library',{},busy,pause));
  assert.equal(calls,7);
  calls=0;
  await assert.rejects(requestJSON('/api/action',{body:{action:'next'}},busy,pause));
  assert.equal(calls,1);
  calls=0;
  await assert.rejects(requestJSON('/api/library',{},async()=>{calls++;throw new Error('lost');},pause));
  assert.equal(calls,1);
  calls=0;
  const result=await requestJSON('/api/library',{},async()=>{
    if(calls++===0) return {status:409,ok:false,json:async()=>({})};
    return {status:200,ok:true,json:async()=>({items:[]})};
  },pause);
  assert.deepEqual(result,{items:[]});
  assert.equal(calls,2);
});

test('queue highlighting requires position and metadata; formats never imply audio quality', async () => {
  const {queueTrackMatches,mediaFormat}=await core;
  const track={title:'Same title',artist:'Artist',queue_position:1,path:'/tmp/sdcard/Album/Track.FLAC'};
  assert.equal(queueTrackMatches({position:1,title:'Same title',artist:'Artist'},track),true);
  for(const item of [{position:0,title:'Same title',artist:'Artist'},{position:1,title:'Replaced',artist:'Artist'},{position:1,title:'Same title',artist:'Other'}]) assert.equal(queueTrackMatches(item,track),false);
  assert.equal(queueTrackMatches({position:null,title:'Same title',artist:'Artist'},{...track,queue_position:null}),false);
  assert.equal(mediaFormat(track),'FLAC');
  assert.equal(mediaFormat({path:'/tmp/sdcard/Album/Track.m4a'}),'M4A');
  for(const value of [null,{}, {title:'Track.flac'}, {path:'/tmp/sdcard/Track'}, {path:'/tmp/sdcard/Track.xyz'}]) assert.equal(mediaFormat(value),null);
});

test('album navigation keeps the artist from cards, track menus and playback metadata', async () => {
  const {navigationRoute,albumScope,routeHash,parseRoute}=await core;
  const title='Greatest Hits & More', artist='Артист + Guest';
  for(const item of [{title,artist},{title,scope_artist:artist},{title,artists:[artist]}]) {
    assert.deepEqual(parseRoute(routeHash(navigationRoute('album',item))),{view:'album',name:title,artist});
  }
  assert.equal(albumScope({artist:'Other',scope_artist:artist}),artist);
  assert.equal(albumScope({artists:[artist,'Other'],artist}), '');
  assert.deepEqual(navigationRoute('album',{title}),{view:'album',name:title,artist:''});
  assert.deepEqual(navigationRoute('artist',{title:artist,artist:'Unrelated'}),{view:'artist',name:artist,artist:''});
});

test('metadata shows observed values in both locales without invented quality or DSD bit depth', async () => {
  const {trackMetadata}=await core;
  const data={sample_rate_hz:44100,bit_depth:24,channels:2,genre:'Literal genre',track_number:3,reported_bit_rate:1411,is_cue:true};
  const en=trackMetadata(data,'en');
  assert.deepEqual(en,[['metadata_sample_rate','44.1'],['metadata_bit_depth',24],['metadata_channels',2],['metadata_genre','Literal genre'],['metadata_track_number',3],['metadata_source','CUE']]);
  assert.equal(trackMetadata({metadata:data},'ru')[0][1],'44,1');
  assert.equal(trackMetadata({...data,is_dsd:true}).some(([key])=>key==='metadata_bit_depth'),false);
  assert.deepEqual(trackMetadata({}),[]);
  assert.deepEqual(trackMetadata({sample_rate_hz:0,channels:true,bit_depth:'24',is_dsd:1}),[]);
});

test('genre album links never inherit an artist scope and retain literal genre in URL', async () => {
  const {navigationRoute,routeHash,parseRoute}=await core;
  const route=navigationRoute('album',{title:'Shared',artist:'A',scope_genre:'Rock & Jazz'});
  assert.deepEqual(route,{view:'album',name:'Shared',artist:'',genre:'Rock & Jazz'});
  assert.deepEqual(parseRoute(routeHash(route)),route);
  assert.equal(navigationRoute('artist',{title:'A',scope_genre:'Jazz'}).genre,undefined);
  assert.equal(parseRoute('#view=home&genre=Rock').genre,undefined);
});

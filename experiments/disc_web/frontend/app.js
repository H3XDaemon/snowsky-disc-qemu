import {createAlbumInfo} from './album-info.mjs';
import {setupDialogs} from './dialogs.mjs';
import {requestJSON, requestId} from './request.mjs';
import {createConnection} from './connection.mjs';
import {createImporter} from './imports.mjs';
import {createSound} from './sound.mjs';
import {t, initLocale, setLocale, getLocale} from './i18n.mjs';
await initLocale();
import {escapeHTML as esc, timeLabel, trackColumns, trackMetadata, mediaFormat, queueTrackMatches, filterItems, searchKind, routeHash, parseRoute, navigationRoute, albumScope, trackDuration, playbackIdentity, seekAllowed, coverIdentity, artworkSource} from './core.mjs';

const paths = {
 moon:'M20.8 13.3A9 9 0 0 1 10.7 3.2a9 9 0 1 0 10.1 10.1Z',
 home:'M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z',
 album:'M4 3h16v18H4Z M8 8h8v8H8Z M10 12h4',
 artist:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2',
 music:'M9 18V5l11-2v13 M9 7l11-2 M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3ZM20 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3Z',
 heart:'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z',
 playlist:'M4 5h13M4 10h13M4 15h7M17 14v7M13.5 17.5h7',
 queue:'M3 5h18M3 10h18M3 15h10M17 15l4 3-4 3Z',
 search:'M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0ZM15 15l6 6',
 upload:'M12 16V3m-5 5 5-5 5 5M4 14v6h16v-6',
 refresh:'M20 7a9 9 0 1 0 1 8M20 3v5h-5',
 device:'M5 2h14v20H5Z M8 5h8v8H8Z M14 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z',
 play:'m9 5 11 7-11 7Z',pause:'M8 5v14M16 5v14',
 previous:'M5 5v14M19 5 8 12l11 7Z',next:'M19 5v14M5 5l11 7L5 19Z',
 shuffle:'M3 6h3c5 0 7 12 12 12h3M17 14l4 4-4 4M3 18h3c2 0 4-3 6-6s4-6 6-6h3M17 2l4 4-4 4',
 repeat:'m17 2 4 4-4 4M3 11V8a2 2 0 0 1 2-2h16M7 22l-4-4 4-4M21 13v3a2 2 0 0 1-2 2H3',
 volume:'M11 4 6 8H2v8h4l5 4ZM15 8a6 6 0 0 1 0 8M18 4a11 11 0 0 1 0 16',
 close:'M6 6l12 12M6 18 18 6',arrow:'M5 12h14m-5-5 5 5-5 5',back:'M19 12H5m5-5-5 5 5 5',
 clock:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2',info:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 11v6M12 7h.01',
 sliders:'M5 3v6m0 4v8M12 3v10m0 4v4M19 3v2m0 4v12M2 9h6M9 13h6M16 5h6'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.music}"/></svg>`;
for (const node of document.querySelectorAll('[data-icon]')) node.innerHTML = icon(node.dataset.icon);
const $ = id => document.getElementById(id);
setupDialogs();
function updateThemeChoice() {
  const preference=window.DiscTheme.get();
  for (const choice of document.querySelectorAll('[data-theme-choice]')) choice.setAttribute('aria-pressed',choice.dataset.themeChoice===preference);
  $('theme-button').title=t('appearance_label')+({light:t('light_label'),dark:t('dark_label'),system:t('system_label')}[preference]);
}
$('theme-button').onclick=()=>$('theme-dialog').showModal();
$('close-theme').onclick=()=>$('theme-dialog').close();
for (const choice of document.querySelectorAll('[data-theme-choice]')) choice.onclick=()=>window.DiscTheme.set(choice.dataset.themeChoice);
window.addEventListener('disc-theme-change', updateThemeChoice);
updateThemeChoice();
document.querySelector('.skip-link').onclick = event => {event.preventDefault(); $('main').focus();};
const titleKeys = {home:'home',albums:'albums',artists:'artists',tracks:'tracks',favorites:'favorites',playlists:'playlists',album:'album',artist:'artist',playlist:'playlist'};
let state = null, route = parseRoute(location.hash), currentItems = [], homeTracks = [], activeItem = null;
let requestSequence = 0, busy = false, genres = null, genreSelection = null, toastTimer, pollTimer, lastTrack = '', libraryLoading = false;
let displayedSnapshot=null;
let lastCoverRequest='';
let queueItems=null, queueGeneration=null, queueRequest=0, queueLoading=false, queueError='';
const cachedViews=new Set(['home','albums','artists','tracks','album','artist']);
const canBrowse=()=>state?.connection==='ready'||(state?.catalogue?.available&&cachedViews.has(route.view));
const albumInfo=createAlbumInfo({api,getState:()=>state,isBusy:()=>busy||libraryLoading,caption:cardCaption});
const importer = createImporter({getState:()=>state, isBusy:()=>busy||libraryLoading, refreshState, loadView, api, toast,
  syncCatalogue:startCatalogueSync, showLibrary:()=>navigate('albums')});
const connection = createConnection({getState:()=>state, isBusy:()=>busy||libraryLoading||state?.busy, refreshState, api, command, setBusy:value=>{busy=value;updatePlayer();}});
const sound = createSound({getState:()=>state,isBusy:()=>busy||libraryLoading,api,refreshState});
let editContext = null, menuContext = null, seekDraft = null, seekFeedback = '', seekIdentity = '', pendingSeek = null, seekRequested = null;


function editLabels() {
  if (!editContext) return;
  const keys={create:'new_playlist',rename:'rename',add:'add_to_playlist',remove:'remove_from_playlist'};
  $('playlist-dialog-title').textContent=t(keys[editContext.action]);
  $('playlist-submit').textContent=t(editContext.action==='create'?'create':editContext.action==='rename'?'save':keys[editContext.action]);
}
async function openPlaylistEditor(action, item=null, origin=route) {
  if (busy || libraryLoading) return toast(t('please_wait_for_the_current_request'));
  editContext={action,item,name:origin.name,generation:state.generation};
  editLabels();
  $('playlist-track-label').textContent=item?.title || '';
  $('playlist-name').value=action==='rename' ? route.name : '';
  $('playlist-name').required=['create','rename'].includes(action);
  $('playlist-name-label').hidden=!['create','rename'].includes(action);
  $('playlist-select-label').hidden=action!=='add';
  $('playlist-feedback').textContent='';
  $('playlist-submit').disabled=false;
  if (action==='add') {
    try {
      const data=await api('/api/library?kind=playlists');
      $('playlist-select').replaceChildren(...data.items.map(item=>new Option(item.title,item.title)));
      if (!data.items.length) {$('playlist-feedback').textContent=t('playlist_empty'); $('playlist-submit').disabled=true;}
    } catch {return toast(t('request_failed'),true);}
  }
  $('playlist-dialog').showModal();
  if (['create','rename'].includes(action)) $('playlist-name').focus();
}
$('close-playlist').onclick=()=>$('playlist-dialog').close();
$('playlist-form').onsubmit=async event=>{
  event.preventDefault();
  if (!editContext || busy) return;
  if (state.generation!==editContext.generation) {
    $('playlist-feedback').textContent=t('request_failed'); $('playlist-submit').disabled=true; return;
  }
  const {action,item,name}=editContext;
  const newName=$('playlist-name').value.trim();
  const extras=action==='create' ? {name:newName} : action==='rename' ? {name,new_name:newName}
    : {name:action==='add' ? $('playlist-select').value : name, ...(state.demo ? {track:item.id} : {selection:item.selection})};
  $('playlist-submit').disabled=true;
  const success=await command('playlist_'+action,extras);
  if (success) {
    $('playlist-dialog').close();
    if (action==='rename') navigate('playlist',{title:newName});
    else await loadView();
  } else $('playlist-feedback').textContent=t('result_unconfirmed_the_command_was_not_retried');
};

function toast(message, error=false) {
  clearTimeout(toastTimer); $('toast').textContent = message; $('toast').hidden = false;
  $('toast').classList.toggle('error', error);
  toastTimer = setTimeout(() => $('toast').hidden = true, error ? 11000 : 4500);
}
async function api(path, body) {
  try {return await requestJSON(path,{body,token:state?.token});}
  catch {throw new Error(t('request_failed'));}
}
function renderCatalogue() {
  const saved=state?.catalogue;
  const demo=state?.demo;
  $('sync-catalogue').disabled=demo||!saved||state.connection!=='ready'||busy||state.busy||libraryLoading||saved.phase==='syncing';
  $('reload-catalogue-view').disabled=busy||libraryLoading||state?.busy;
  if(!saved||demo) {
    $('catalogue-status').textContent=t(demo?'demo_mode':'disconnected');
    $('catalogue-description').textContent=t(demo?'catalogue_demo':'catalogue_intro');
    $('catalogue-activity').textContent=t(demo?'demo_collection_no_audio':'catalogue_connect_first');
    for(const id of ['catalogue-coverage','catalogue-error','catalogue-progress','catalogue-metadata-error']) $(id).hidden=true;
    $('sync-caption').textContent=t('catalogue_sync');
    return;
  }
  const syncing=saved.phase==='syncing';
  const failed=['failed','storage_error'].includes(saved.phase);
  const status=syncing?'active':failed?'failed':state.connection!=='ready'?'offline':!saved.available?'empty':saved.stale?'stale':'ready';
  const date=saved.observed_at?new Date(saved.observed_at).toLocaleString(getLocale()==='ru'?'ru-RU':'en-US',{dateStyle:'medium',timeStyle:'short'}):'';
  $('catalogue-description').textContent=saved.available?t('catalogue_observed',{date,count:saved.track_count}):t('catalogue_intro');
  $('catalogue-status').textContent=t('catalogue_status_'+status);
  $('catalogue-dialog').dataset.status=status;
  $('refresh').dataset.status=status;
  $('refresh').title=t('catalogue_dialog_title')+' · '+t('catalogue_status_'+status);
  const stages=['identity','catalog','enrichment','verification'];
  const stage=stages.includes(saved.stage)?saved.stage:'identity';
  $('catalogue-progress').hidden=!syncing;
  $('catalogue-activity').textContent=syncing?t('catalogue_activity_'+stage,{count:saved.pages||0})
    :t(status==='ready'?'catalogue_complete':status==='offline'?'catalogue_connect_first':failed?'catalogue_retry_note':'catalogue_waiting');
  $('catalogue-error').hidden=!failed;
  const errorKey='catalogue_error_'+saved.error;
  const knownErrors=['membership','changed','ambiguous','invalid','limit','connection','unavailable','identity_timeout'];
  $('catalogue-error').textContent=failed?[t(saved.phase==='storage_error'?'catalogue_storage_error':'catalogue_sync_failed'),
    ...(knownErrors.includes(saved.error)?[t(errorKey)]:[]),
    t(saved.available?'catalogue_kept':'catalogue_no_snapshot')].join(' '):'';
  for(const node of $('catalogue-stages').children) {
    if(syncing&&node.dataset.stage===stage) node.setAttribute('aria-current','step');
    else node.removeAttribute('aria-current');
    node.classList.toggle('is-complete',status==='ready'||(syncing&&stages.indexOf(node.dataset.stage)<stages.indexOf(stage)));
  }
  $('catalogue-coverage').hidden=!saved.available;
  $('catalogue-track-count').textContent=new Intl.NumberFormat(getLocale()).format(saved.track_count||0);
  for(const [field,id] of [['artwork_count','catalogue-artwork-count'],['duration_count','catalogue-duration-count']]) {
    const count=saved.enrichment?.[field];
    $(id).textContent=!saved.enrichment?.unavailable&&Number.isInteger(count)?t('catalogue_coverage',{count,total:saved.track_count}):'—';
  }
  $('catalogue-metadata-error').hidden=!saved.available||!saved.enrichment?.unavailable;
  $('sync-caption').textContent=t(syncing?'catalogue_sync_active':'catalogue_sync');
}
async function startCatalogueSync() {
  if(state?.demo||state?.connection!=='ready'||busy||state.busy||libraryLoading||state.catalogue?.phase==='syncing') return;
  busy=true;updatePlayer();renderCatalogue();
  try {await api('/api/sync',{generation:state.generation,request_id:requestId()});}
  catch {toast(t('catalogue_failed'),true);}
  finally {busy=false;await refreshState();renderCatalogue();}
}
$('sync-catalogue').onclick=startCatalogueSync;
$('close-catalogue').onclick=()=>$('catalogue-dialog').close();
$('reload-catalogue-view').onclick=()=>{
  if(busy||libraryLoading||state?.busy) return;
  $('catalogue-dialog').close();lastCoverRequest='';loadView();
};
function art(item, css='art') {
  const src = artworkSource(item?.art);
  const title=item?.title?.trim()||'♪';
  let hash=0;
  for(const char of title) hash=(Math.imul(hash,31)+char.codePointAt(0))>>>0;
  const letters=esc(Array.from(title.trim()).slice(0,2).join('').toUpperCase());
  return src
    ? `<img class="${css}" src="${src}" alt="" loading="lazy">`
    : `<div class="card-placeholder sleeve-${hash%6} ${item?.type==='artist'?'artist-placeholder':''}" aria-hidden="true"><span class="sleeve-orbit"></span><span class="sleeve-type">${letters}</span></div>`;
}
function navigate(view, item=null) {
  activeItem = item;
  const next = navigationRoute(view,item);
  if (location.hash === routeHash(next)) {route=next; loadView();}
  else location.hash = routeHash(next);
}
window.addEventListener('hashchange', () => {
  route = parseRoute(location.hash);
  $('search').value = ''; window.scrollTo(0,0); loadView();
});
for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => navigate(button.dataset.view));
function updateNav() {
  $('breadcrumb').textContent = route.name || t(titleKeys[route.view]);
  for (const button of document.querySelectorAll('[data-view]')) {
    const active = button.dataset.view === route.view || `${button.dataset.view}` === `${route.view}s`;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  }
  const kind=searchKind(route.view);
  const label=route.name ? t('search_scoped_'+kind,{name:route.name}) : t('search_'+kind);
  $('search').placeholder = label;
  $('search').setAttribute('aria-label',label);
}
async function loadView() {
  albumInfo.clear();
  updateNav();
  const sequence = ++requestSequence;
  if ($('track-dialog').open) $('track-dialog').close();
  if (!canBrowse()) {
    currentItems=[]; renderDisconnected(); return;
  }
  libraryLoading = true;
  $('main').innerHTML = `<div class="loading-shell" role="status">${t('gathering_your_collection')}</div>`;
  try {
    const params = new URLSearchParams({kind:route.view === 'home' ? 'albums' : route.view, name:route.name,artist:route.artist,genre:route.genre||''});
    const data = await api(`/api/library?${params}`);
    if (sequence !== requestSequence) return;
    currentItems = data.items; displayedSnapshot=data.snapshot||null;
    genres=data.genres??null; genreSelection=data.genre_selection||null;
    if (route.view === 'home') {
      const tracks = await api('/api/library?kind=tracks');
      if (sequence !== requestSequence) return;
      homeTracks = tracks.items;
    }
    renderView();
  } catch (error) {
    if (sequence !== requestSequence) return;
    $('main').innerHTML = `<div class="empty-state">${icon('info')}<h2>${t('collection_unavailable')}</h2><p>${esc(error.message)}</p><button class="secondary-button" id="retry-library">${t('refresh')}</button></div>`;
    $('retry-library').onclick = () => loadView();
  } finally { if (sequence === requestSequence) {libraryLoading=false;updatePlayer();renderCatalogue();} }
}
function renderDisconnected() {
  $('main').innerHTML = `<div class="intro"><div><span class="eyebrow">${t('your_music_your_space')}</span><h1>${t('welcome_back')}</h1></div></div><div class="empty-state">${icon('device')}<h2>${t('it_starts_with_your_disc')}</h2><p>${t('connect_your_player_to_explore_your_collection_choose_an_album_and_take_control_of_your_music')}</p><button id="empty-connect" class="connect-card" aria-label="${t('connect_your_player')}"><span class="device-glyph">${icon('device')}</span><span><strong>SNOWSKY DISC</strong><small>${t('connect_your_player')}</small></span><span class="connect-arrow">${icon('arrow')}</span></button></div>`;
  $('empty-connect').onclick = showDevice;
}
function cardCaption(item) {
  if(item.type==='artist') return '';
  const artist=item.artists?.length>1?t('various_artists'):item.artist;
  const count=Number.isInteger(item.count)&&item.count>=0?t('track_count',{count:item.count}):'';
  return [artist,count].filter(Boolean).join('\n') || t(item.type==='playlist'?'playlist_on_disc':'album_on_disc');
}
function cards(items, extra='') {
  return `<div class="album-grid ${extra}">${items.map((item, i) => `<article class="album-card ${item.type === 'artist' ? 'artist-card' : ''}"><button class="album-cover-button" data-card="${i}" aria-label="${esc(t('open_item',{name:item.title}))}">${art(item)}</button><h3>${esc(item.title)}</h3>${cardCaption(item)?`<p><span>${esc(cardCaption(item)).replaceAll('\n','</span><span>')}</span></p>`:''}${item.genre ? `<div class="album-sub"><span>${esc(item.genre)}</span><span>${esc(item.year)}</span></div>` : ''}</article>`).join('')}</div>`;
}
function rows(items, queue=false) {
  const columns=trackColumns(items);
  return `<div class="track-list">${items.map((item,i) => {
    const selected = queue ? queueTrackMatches(item,state?.playback?.track) : item.id === state?.playback?.track?.id && state?.demo;
    return `<div data-track-row="${i}" class="track-row ${!columns.album ? 'no-album' : ''} ${!columns.duration ? 'no-duration' : ''} ${selected ? 'is-current' : ''}" ${queue ? `data-queue-position="${item.position}"` : ''} ${state?.demo && !queue ? `data-track-id="${esc(item.id)}"` : ''}><span class="track-number">${state?.demo || item.playable ? `<button data-track="${i}" aria-label="${queue ? t('select_in_queue') : t('play_label')} ${esc(item.title)}">${selected ? icon('music') : icon('play')}</button>` : i+1}</span><span class="track-thumb">${art(item)}</span><div class="track-meta"><strong>${esc(item.title)}</strong><small>${esc(item.artist || '—')}</small></div><span class="track-album">${esc(item.album || '—')}</span><span class="track-duration">${timeLabel(item.duration)}</span>${!queue ? `<button class="icon-button track-edit" data-track-menu="${i}" aria-label="${t('track_actions')}: ${esc(item.title)}" aria-haspopup="menu">⋯</button>` : ''}</div>`;
  }).join('')}</div>`;
}
function bindCards(items) {
  albumInfo.observe($('main'),items);
  for (const button of $('main').querySelectorAll('[data-card]')) button.onclick = () => {
    const item = items[Number(button.dataset.card)];
    navigate(item.type, item);
  };
}
function playItem(item, origin, queue=false) {
  if (origin.generation!==state?.generation) return toast(t('track_changed'),true);
  const extras=state.demo ? (queue ? {index:item.position} : {name:item.id,source_view:origin.view==='home'?'tracks':origin.view,source_name:origin.name,source_artist:origin.artist,source_genre:origin.genre||''}) : {selection:item.selection};
  return command(queue ? 'queue' : 'track',extras);
}
function bindTracks(root, items, queue=false) {
  const origin={...route,generation:state.generation};
  if(!queue) for(const row of root.querySelectorAll('[data-track-row]')) row.oncontextmenu=event=>{
    event.preventDefault(); openTrackMenu(items[Number(row.dataset.trackRow)],origin,row.querySelector('[data-track-menu]'));
  };
  for (const button of root.querySelectorAll('[data-track-menu]')) button.onclick=()=>openTrackMenu(items[Number(button.dataset.trackMenu)],origin,button);
  for (const button of root.querySelectorAll('[data-track]')) button.onclick=()=>playItem(items[Number(button.dataset.track)],origin,queue);
}
function renderMetadata(id, track) {
  const rows=trackMetadata(track,getLocale());
  $(id).hidden=!rows.length;
  $(id).innerHTML=rows.map(([key,value])=>`<div><dt>${esc(t(key))}</dt><dd>${esc(value)}</dd></div>`).join('');
}
function openTrackMenu(item, origin, anchor) {
  menuContext={item,origin};
  $('menu-title').textContent=item.title; $('menu-artist').textContent=item.artist || '';
  $('menu-art').innerHTML=art(item);
  renderMetadata('menu-metadata',item);
  const connected=state.connection==='ready'&&!state.busy;
  const enabled={play:connected&&(state.demo||item.playable),add:connected&&(state.demo||(item.editable&&origin.view!=='playlist')),album:!!item.album,artist:!!item.artist,remove:connected&&origin.view==='playlist'&&(state.demo||item.editable)};
  for (const button of $('track-menu').querySelectorAll('button')) {
    const action=button.dataset.trackAction;
    button.disabled=!enabled[action]; button.hidden=action==='remove'&&!enabled.remove;
    button.title=button.disabled?t(action==='album'?'album_unavailable':'source_action_unavailable'):'';
  }
  const rect=anchor.getBoundingClientRect(), dialog=$('track-dialog');
  dialog.style.setProperty('--menu-x',`${Math.max(12,Math.min(innerWidth-332,rect.right-320))}px`);
  dialog.style.setProperty('--menu-y',`${Math.max(12,Math.min(innerHeight-370,rect.bottom+6))}px`);
  dialog.showModal();
  dialog.style.setProperty('--menu-y',`${Math.max(12,Math.min(innerHeight-dialog.getBoundingClientRect().height-12,rect.bottom+6))}px`);
  $('track-menu').querySelector('button:not(:disabled)').focus();
}
$('close-track-menu').onclick=()=>$('track-dialog').close();
$('track-menu').onkeydown=event=>{
  const keys=['ArrowDown','ArrowUp','Home','End']; if(!keys.includes(event.key)) return;
  event.preventDefault();
  const buttons=[...$('track-menu').querySelectorAll('button:not(:disabled):not([hidden])')], index=buttons.indexOf(document.activeElement);
  buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();
};
for (const button of $('track-menu').querySelectorAll('button')) button.onclick=()=>{
  const {item,origin}=menuContext, action=button.dataset.trackAction;
  $('track-dialog').close();
  if(origin.generation!==state.generation) return toast(t('track_changed'),true);
  if(action==='play') playItem(item,origin);
  if(action==='add'||action==='remove') openPlaylistEditor(action,item,origin);
  if(action==='album') navigate('album',{title:item.album,art:item.art,scope_artist:origin.artist||item.artist||'',scope_genre:origin.genre||item.scope_genre||''});
  if(action==='artist') navigate('artist',{title:item.artist});
};
function renderView() {
  const query = $('search').value;
  let items = filterItems(currentItems, query);
  if (route.view === 'home' && !query) return renderHome(items);
  const detail = ['album','artist','playlist'].includes(route.view);
  const isTracks = ['tracks','favorites','album','playlist'].includes(route.view);
  const count = items.length;
  const columns=trackColumns(items);
  const empty = `<div class="empty-state">${icon(query ? 'search' : 'music')}<h2>${query ? t('no_matches_yet') : t('a_little_quiet_here')}</h2><p>${query ? t('search_empty_'+searchKind(route.view)) : t('your_collection_will_appear_here_after_adding_music_to_your_player')}</p></div>`;
  let heading;
  if (detail) {
    const item = activeItem?.title === route.name ? {...activeItem} : {title:route.name,art:items[0]?.art};
    if(route.view==='album') item.art=currentItems.find(track=>track.art)?.art||null;
    const artists=route.view==='album' ? (route.artist ? [route.artist] : [...new Set(currentItems.map(track=>track.artist).filter(Boolean))]) : [];
    const artistLinks=artists.map(name=>`<a class="detail-artist-link" href="${esc(routeHash({view:'artist',name}))}">${esc(name)}</a>`).join(' · ');
    const canPlay = state.connection==='ready'&&!state.busy&&!busy&&(!route.genre || !!genreSelection);
    heading = `<button class="text-button" id="back">${icon('back')} ${route.view === 'album' && route.artist ? esc(route.artist) : t('back_to_collection')}</button><div class="detail-heading"><div class="detail-art">${art(item)}</div><div class="detail-copy"><span class="eyebrow">${esc(t(titleKeys[route.view]))}</span><h1>${esc(route.name)}</h1><p>${artistLinks}${artistLinks ? ' · ' : ''}${t(isTracks ? 'track_count' : 'album_count',{count:currentItems.length})}${route.genre ? ' · '+esc(route.genre) : ''}${state.demo ? ' · DISC Sessions' : ''}</p><div class="detail-actions"><button id="play-collection" class="primary-button" ${!canPlay || !currentItems.length ? 'disabled' : ''}>${icon('play')} ${route.view === 'album' ? t('play_album') : t('listen')}</button></div></div></div>`;
    if(route.view==='album' && !route.artist && !route.genre && artists.length>1) {
      heading+=`<div class="album-scope"><p>${t('album_scope_note')}</p><div class="filter-chips">${artists.map(artist=>`<a class="chip" href="${esc(routeHash({view:'album',name:route.name,artist}))}">${esc(artist)}</a>`).join('')}</div></div>`;
    }

  } else {
    heading = `<div class="view-heading"><div><span class="eyebrow">${t('my_collection')}</span><h1>${esc(t(titleKeys[route.view]))}</h1><p>${query ? t('found') : t('in_this_section')}: ${count}${state.demo ? t('demo_collection') : ''}</p></div></div>`;
    if (['albums','tracks'].includes(route.view)) {
      if(genres?.length) heading += `<div class="filter-chips genre-filters" role="group" aria-label="${t('genre_filter')}"><button class="chip ${!route.genre?'active':''}" data-genre="" aria-pressed="${!route.genre}">${t('all_genres')}</button>${genres.map(g=>`<button class="chip ${route.genre===g.name?'active':''}" data-genre="${esc(g.name)}" aria-pressed="${route.genre===g.name}" ${!g.available?'disabled':''} title="${esc(g.available?g.name:t('genre_unavailable'))}">${esc(g.name)}</button>`).join('')}</div>`;
      else if(genres===null&&!state.demo) heading += `<p class="scope-note">${t('genres_need_sync')}</p>`;
      if(route.genre) heading += `<div class="genre-heading"><span>${esc(route.genre)}</span><button id="play-genre" class="secondary-button" ${!genreSelection||state.connection!=='ready'||state.busy||busy?'disabled':''}>${icon('play')} ${t('play_genre')}</button><button id="genre-view" class="text-button">${t(route.view==='albums'?'all_tracks':'all_albums')} ${icon('arrow')}</button></div>`;
    }

  }
  if (route.view==='playlists') heading+=`<button id="create-playlist" class="secondary-button playlist-create">+ ${t('new_playlist')}</button>`;
  if (route.view==='playlist') heading+=`<button id="rename-playlist" class="secondary-button playlist-create">${t('rename')}</button>`;
  $('main').innerHTML = heading + (!count ? empty : isTracks ? `<div class="track-row track-header ${!columns.album ? 'no-album' : ''} ${!columns.duration ? 'no-duration' : ''}"><span>#</span><span></span><span>${t('title')}</span><span class="track-album">${t('album_label')}</span><span class="track-duration">${icon('clock')}</span></div>${rows(items)}` : cards(items));
  bindCards(items); bindTracks($('main'), items);
  if ($('create-playlist')) $('create-playlist').onclick=()=>openPlaylistEditor('create');
  if ($('rename-playlist')) $('rename-playlist').onclick=()=>openPlaylistEditor('rename');
  for (const chip of $('main').querySelectorAll('[data-genre]')) chip.onclick = () => {location.hash=routeHash({...route,genre:chip.dataset.genre});};
  if($('play-genre')) $('play-genre').onclick=()=>command('genre',{selection:genreSelection,genre:route.genre});
  if($('genre-view')) $('genre-view').onclick=()=>navigate(route.view==='albums'?'tracks':'albums',{scope_genre:route.genre});
  if ($('back')) $('back').onclick = () => route.genre ? navigate('albums',{scope_genre:route.genre}) : route.artist ? navigate('artist',{title:route.artist}) : navigate(`${route.view}s`);
  if ($('play-collection')) $('play-collection').onclick = () => route.genre ? command('genre',{selection:genreSelection,genre:route.genre,album:route.name}) : command(route.view, {name:route.name,...(route.artist ? {artist:route.artist} : {}),...(route.view==='playlist'&&!state.demo?{selection:currentItems[0]?.selection}:{})});
}
function renderHome(items) {
  const albumItems = items.slice(0,4), tracks = homeTracks.slice(0,3), featured = items[0];
  $('main').innerHTML = `<div class="intro"><div><span class="eyebrow">${t('a_good_day_for_music')}</span><h1>${t('on_your_wavelength')}</h1></div><span class="intro-note">${icon('music')} ${t('just_your_collection')}</span></div>
    <section class="hero" aria-label="${t('album_from_your_collection')}">${featured?.art ? `<img class="hero-art" src="${esc(featured.art)}" alt="">` : ''}<div class="hero-content"><span class="eyebrow">${state.demo ? t('disc_sessions_in_focus') : t('your_personal_collection')}</span><h2>${t('your_collection')}<br>${t('your_rhythm')}</h2><p>${featured ? `${esc(featured.title)}${featured.artist ? ` — ${esc(featured.artist)}` : ''}.<br>${t('press_play_everything_else_can_wait')}` : `${t('your_favorite_records_all_in_one_place')}<br>${t('let_music_into_your_day')}`}</p><button class="primary-button" id="hero-play" ${!featured ? 'disabled' : ''}>${icon('play')} ${t('play_album')}</button></div><span class="hero-caption">MADE FOR LISTENING</span></section>
    <section><div class="section-heading"><h2>${t('your_albums')}<small>${t('the_music_you_always_come_back_to')}</small></h2><button class="text-button" id="all-albums">${t('all_albums')} ${icon('arrow')}</button></div>${albumItems.length ? cards(albumItems,'home-albums') : `<p class="scope-note">${t('no_albums_in_your_library_yet')}</p>`}</section>
    <div class="home-bottom"><section><div class="section-heading"><h2>${t('from_your_collection')}</h2><button class="text-button" id="all-tracks">${t('all_tracks')} ${icon('arrow')}</button></div>${rows(tracks)}</section><section><div class="section-heading"><h2>${t('room_for_music')}</h2></div><div class="listening-note"><span class="eyebrow">${t('just_listen')}</span><h3>${t('less_noise')}<br>${t('more_music')}</h3><p>${t('your_player_your_records')}<br>${t('everything_that_matters_right_here')}</p><span class="note-ring"></span></div></section></div>`;
  bindCards(albumItems); bindTracks($('main'),tracks);
  $('all-albums').onclick = () => navigate('albums'); $('all-tracks').onclick = () => navigate('tracks');
  $('hero-play').onclick = () => command('album',{name:featured.title,...(albumScope(featured)?{artist:albumScope(featured)}:{})});
}
async function refreshState() {
  try {
    const previous = state;
    state = await api('/api/state');
    updatePlayer(); importer.render(); connection.render(); sound.render(); renderCatalogue();
    if(previous?.catalogue?.phase==='syncing'&&previous.generation===state.generation&&!$('catalogue-dialog').open) {
      if(state.catalogue?.phase==='done') toast(t('catalogue_complete'));
      else if(state.catalogue?.phase==='failed') toast(t('catalogue_sync_failed'),true);
    }
    $('mode-banner').hidden = !state.demo;
    $('output-label').textContent = state.demo ? t('demo_no_audio') : t('on_disc');
    $('connection-label').textContent = state.demo ? t('demo_mode') : ({ready:t('connected'),connecting:t('connecting'),reconnecting:t('reconnecting'),disconnected:t('disconnected')}[state.connection] || state.connection);
    $('status-light').classList.toggle('ready',state.connection==='ready');
    if (previous && (previous.connection !== state.connection || previous.generation !== state.generation || previous.catalogue?.generation!==state.catalogue?.generation || previous.catalogue?.enrichment?.revision!==state.catalogue?.enrichment?.revision)) {
      albumInfo.clear();
      if (canBrowse()) loadView();
      else {++requestSequence; libraryLoading=false; renderDisconnected(); closeListeningPanel(false);}
    }
    return true;
  } catch {
    if (state) state = {...state,connection:'disconnected',playback:{state:'unknown'}};
    updatePlayer(); importer.render(); connection.render(); sound.render(); renderCatalogue(); $('connection-label').textContent=t('server_unavailable'); $('status-light').classList.remove('ready');
    return false;
  }
}
function updatePlayer() {
  const p = state?.playback || {}, track = p.track, ready = state?.connection === 'ready';
  for(const button of document.querySelectorAll('main [data-track],#play-collection,#hero-play')) button.disabled=!ready||busy||state?.busy||libraryLoading||!currentItems.length;
  for (const row of document.querySelectorAll('[data-track-id]')) {
    const selected = state?.demo && row.dataset.trackId === track?.id;
    if (row.classList.contains('is-current') !== selected) {
      row.classList.toggle('is-current', selected);
      const button = row.querySelector('[data-track]');
      if (button) button.innerHTML = icon(selected ? 'music' : 'play');
    }
  }
  const key = coverIdentity(state);
  if (key !== lastTrack) {
    lastTrack=key;
    $('now-art').innerHTML = art(track);
    $('large-art').innerHTML = art(track);
  }
  const coverRequest=JSON.stringify([key,state?.catalogue?.generation]);
  if (track && !state.demo && ready && !busy && !state.busy && coverRequest!==lastCoverRequest) {
      lastCoverRequest=coverRequest;
      const img = new Image(); img.alt='';
      img.onload = () => {if (key===lastTrack) {$('now-art').replaceChildren(img); $('large-art').replaceChildren(img.cloneNode());}};
      img.src = '/api/cover?v=' + encodeURIComponent(key);
  }
  $('now-title').textContent = track?.title || t('your_music_awaits');
  $('now-artist').textContent = track?.artist || (ready ? t('choose_an_album') : t('connect_your_disc'));
  $('play').innerHTML = icon(p.state === 'playing' ? 'pause' : 'play');
  $('play').setAttribute('aria-label',p.state === 'playing' ? t('pause') : t('play'));
  $('favorite').setAttribute('aria-pressed',p.favorite === true);
  $('favorite').setAttribute('aria-label',p.favorite ? t('unfavorite_the_current_track') : t('favorite_the_current_track'));
  $('shuffle').setAttribute('aria-pressed',p.mode==='random');
  $('repeat').setAttribute('aria-pressed',p.mode==='repeat_list');
  for (const id of ['play','next','previous','favorite','shuffle','repeat','volume']) $(id).disabled = !ready || busy || state?.busy || (['play','next','previous','favorite'].includes(id) && !track);
  $('queue-button').disabled = !ready;
  for(const id of ['play-genre','play-collection']) if($(id)) $(id).disabled=!ready||busy||state?.busy||libraryLoading||!currentItems.length||Boolean(route.genre&&!genreSelection);
  $('position').textContent = timeLabel(Number.isFinite(p.position_ms) ? p.position_ms/1000 : null);
  $('duration').textContent = timeLabel(trackDuration(track));
  updateSeek();
  if (Number.isFinite(state?.volume) && document.activeElement !== $('volume')) $('volume').value=state.volume;
  $('volume-value').textContent = state?.volume ?? '—';
  $('volume').title = Number.isFinite(state?.volume) ? t('volume_value',{value:state.volume}) : t('current_volume_is_unknown_choose_a_value_from_0_120');
  $('large-title').textContent = $('now-title').textContent;
  $('large-artist').textContent = track?.artist || '';
  $('large-artist').disabled = !track?.artist;
  $('large-album').textContent = track?.album || '';
  $('large-album').disabled = !track?.album;
  $('large-album').hidden = !track?.album;
  $('large-status').textContent = !ready ? t('disconnected') : t('playback_'+(['playing','paused','stopped','loading'].includes(p.state)?p.state:'unknown'));
  renderMetadata('large-metadata',track);
  const format=mediaFormat(track);
  $('large-format').hidden=!format;
  $('large-format').textContent=format || '';
  $('large-format').title=t('format_from_filename');
  $('large-position').textContent = $('position').textContent;
  $('large-duration').textContent = $('duration').textContent;
  $('large-output').textContent = state?.demo ? t('demo_mode_no_audio') : t('audio_plays_on_your_disc');
  for (const id of ['play','next','previous','favorite','shuffle','repeat']) {
    const large=$('large-'+id), small=$(id);
    large.disabled=small.disabled;
    if (id==='play') {large.innerHTML=small.innerHTML; large.setAttribute('aria-label',small.getAttribute('aria-label'));}
    if (small.hasAttribute('aria-pressed')) large.setAttribute('aria-pressed',small.getAttribute('aria-pressed'));
  }
  $('large-volume').disabled=$('volume').disabled;
  if (document.activeElement!==$('large-volume')) $('large-volume').value=$('volume').value;
  $('large-volume-value').textContent=$('volume-value').textContent;
  updateQueueControls();
}
function updateSeek() {
  const identity=playbackIdentity(state);
  if (seekIdentity && seekIdentity!==identity) {seekFeedback=''; pendingSeek=null; seekRequested=null;}
  if (pendingSeek && state?.playback?.state==='playing') {
    pendingSeek.resumedAt ??= Date.now();
    const elapsed=Date.now()-pendingSeek.resumedAt, position=state.playback.position_ms;
    if(Number.isFinite(position) && position>=pendingSeek.target && position<=pendingSeek.target+elapsed+2000) {
      seekFeedback='seek_confirmed'; pendingSeek=null;
    } else if(elapsed>8000) {seekFeedback='seek_unconfirmed'; pendingSeek=null;}
  }
  seekIdentity=identity;
  const duration=trackDuration(state?.playback?.track);
  for (const id of ['progress','large-progress']) {
    const slider=$(id);
    slider.max=Number.isFinite(duration)?Math.max(0,Math.ceil(duration)-1):100;
    slider.disabled=!seekAllowed(state)||busy||state?.busy||libraryLoading;
    if(!seekDraft) slider.value=Math.min(Number(slider.max),Math.max(0,(state?.playback?.position_ms||0)/1000));
    slider.style.setProperty('--seek-fill',`${100*Number(slider.value)/Math.max(1,Number(slider.max))}%`);
    slider.setAttribute('aria-valuetext',timeLabel(Number(slider.value))+' / '+timeLabel(duration));
  }
  if(seekDraft) $('position').textContent=timeLabel(seekDraft.seconds);
  $('seek-feedback').textContent=seekFeedback?t(seekFeedback,{position:timeLabel(seekRequested)}):'';
}
function captureSeek() {
  if(!seekDraft) seekDraft={identity:playbackIdentity(state),expected:structuredClone(state.playback.track),source:state.playback.source,seconds:Math.floor((state.playback.position_ms||0)/1000),moved:false};
}
for (const id of ['progress','large-progress']) {
  const slider=$(id);
  slider.onpointerdown=()=>{if(!slider.disabled) captureSeek();};
  slider.oninput=()=>{
    captureSeek(); seekDraft.moved=true; seekDraft.seconds=Number(slider.value);
    $('position').textContent=$('large-position').textContent=timeLabel(seekDraft.seconds);
    for(const other of ['progress','large-progress']) {
      $(other).value=slider.value;
      $(other).style.setProperty('--seek-fill',`${100*Number(slider.value)/Math.max(1,Number(slider.max))}%`);
    }
  };
  slider.onchange=async()=>{
    const draft=seekDraft; seekDraft=null;
    if(!draft||draft.identity!==playbackIdentity(state)) {updateSeek();return toast(t('track_changed'),true);}
    if(busy||state?.busy||libraryLoading) {updateSeek();return toast(t('please_wait_for_the_current_request'));}
    pendingSeek=null; seekRequested=Number(slider.value); seekFeedback='seek_sending';
    await command('seek',{position_ms:Math.round(Number(slider.value)*1000),expected:draft.expected,source:draft.source});
  };
  slider.onpointerup=()=>{if(seekDraft&&!seekDraft.moved){seekDraft=null;updateSeek();}};
  slider.onpointercancel=()=>{seekDraft=null;updateSeek();};
  slider.onblur=()=>{if(seekDraft){seekDraft=null;updateSeek();}};
}
async function command(action, extras={}) {
  if (busy || state?.busy || libraryLoading) return toast(t('please_wait_for_the_current_request'));
  busy = true; updatePlayer();
  let success=false;
  try {
    const result = await api('/api/action',{action,...extras,...(action==='album'&&displayedSnapshot?{snapshot:displayedSnapshot}:{}),generation:state?.generation,request_id:requestId()});
    if (action==='seek') {
      if(result.outcome==='seek_waiting_for_playback') pendingSeek={target:result.confirmation.rounded_ms,resumedAt:null};
      seekFeedback=result.outcome==='seek_waiting_for_playback'?'seek_paused':result.status==='confirmed'?'seek_confirmed':'seek_unconfirmed';
      toast(t(seekFeedback,{position:timeLabel(seekRequested)}),result.status!=='confirmed');
    } else if (['uncertain','not_sent','unavailable'].includes(result.status)) toast(t('result_unconfirmed_the_command_was_not_retried'),true);
    else if (state?.demo) toast(t('demo_updated_no_device_playback_was_changed'));
    else if (action==='connect') toast(t('connecting_to_disc'));
    else if (action==='disconnect') toast(t('disconnected_label'));
    else toast(result.status==='already_satisfied' ? t('already_set') : t('done_verified_on_disc'));
    success=!['uncertain','not_sent','unavailable'].includes(result.status);
    await refreshState();
    if (route.view==='favorites' && action==='favorite') await loadView();
    if (queueVisible()) await loadQueue();
  } catch (error) {
    if(action==='seek') seekFeedback='seek_unconfirmed';
    toast(`${error.message || t('connection_lost')}. ${t('the_request_is_not_automatically_retried')}`,true);
    await refreshState();
  } finally {busy=false; updatePlayer();}
  return success;
}
function queueVisible() {return !$('now-panel').hidden;}
function updateQueueControls() {
  if (queueGeneration!==state?.generation || state?.connection!=='ready') {
    if (queueItems || queueLoading) {++queueRequest; queueLoading=false; queueItems=null; queueError=''; renderQueue();}
    queueGeneration=state?.generation;
  }
  const blocked=state?.connection!=='ready'||busy||state?.busy||queueLoading;
  $('large-refresh-queue').disabled=blocked;
  const root=$('large-queue-content');
  for(const row of root.querySelectorAll('[data-queue-position]')) {
    const item=queueItems?.find(item=>item.position===Number(row.dataset.queuePosition));
    const selected=Boolean(item && queueTrackMatches(item,state?.playback?.track));
    row.classList.toggle('is-current',selected);
    const button=row.querySelector('[data-track]');
    if(button) {
      button.disabled=blocked||libraryLoading;
      button.setAttribute('aria-current',selected?'true':'false');
      const glyph=selected?'music':'play';
      if(button.dataset.glyph!==glyph) {button.innerHTML=icon(glyph);button.dataset.glyph=glyph;}
    }
  }
}
function renderQueue() {
  let html;
  if(state?.connection!=='ready') html=`<p class="queue-hint">${t('connect_your_disc')}</p>`;
  else if(queueLoading) html=`<p class="queue-hint" role="status">${t('reading_the_queue')}</p>`;
  else if(queueError) html=`<p class="queue-hint" role="status">${esc(queueError)}</p>`;
  else if(queueItems) html=`<p class="queue-hint">${t('track_count',{count:queueItems.length})} · ${state.demo?t('demo_with_no_audio'):t('fresh_disc_queue_snapshot')}</p>${queueItems.length?rows(queueItems,true):`<p class="queue-hint">${t('choose_an_album_to_get_started')}</p>`}<p class="queue-hint queue-footnote">${t('queue_snapshot_note')}</p>`;
  else html=`<p class="queue-hint">${t('refresh_queue')}</p>`;
  const root=$('large-queue-content');
  root.innerHTML=html;
  if(queueItems && !queueLoading && !queueError && state?.connection==='ready') bindTracks(root,queueItems,true);
}
async function loadQueue() {
  const request=++queueRequest, generation=state?.generation;
  queueGeneration=generation; queueItems=null;queueError='';
  queueLoading=state?.connection==='ready';renderQueue();updateQueueControls();
  if(!queueLoading) return;
  try {
    const data=await api('/api/queue');
    if(request!==queueRequest || generation!==state?.generation || state?.connection!=='ready') return;
    if (!data.queue) throw new Error(t('queue_unavailable'));
    queueItems=data.queue.items;
  } catch(error) {if(request===queueRequest) queueError=error.message;}
  finally {if(request===queueRequest) {queueLoading=false;renderQueue();updateQueueControls();}}
}
let listeningOpener=null;
function listeningView(queue=false) {
  $('listening-main').hidden=queue;
  $('listening-queue').hidden=!queue;
  $('listening-tab').setAttribute('aria-pressed',!queue);
  $('listening-queue-tab').setAttribute('aria-pressed',queue);
  $('now-open').setAttribute('aria-expanded',!$('now-panel').hidden && !queue);
  $('queue-button').setAttribute('aria-expanded',!$('now-panel').hidden && queue);
}
function closeListeningPanel(restoreFocus=true) {
  $('now-panel').hidden=true;
  document.body.classList.remove('listening-open');
  $('now-open').setAttribute('aria-expanded','false');
  $('queue-button').setAttribute('aria-expanded','false');
  if(restoreFocus) listeningOpener?.focus({preventScroll:true});
}
function toggleListeningPanel(queue,opener) {
  if(!$('now-panel').hidden && $('listening-main').hidden===queue) {
    closeListeningPanel(); return;
  }
  listeningOpener=opener;
  $('now-panel').hidden=false;
  document.body.classList.add('listening-open');
  listeningView(queue);
  $('close-now').focus({preventScroll:true});
  loadQueue();
}
$('listening-tab').onclick=()=>listeningView(false);
$('listening-queue-tab').onclick=()=>listeningView(true);
$('large-refresh-queue').onclick=()=>loadQueue();
for(const kind of ['artist','album']) $('large-'+kind).onclick=()=>{
  const name=state?.playback?.track?.[kind];
  if(name) {
    if(window.matchMedia('(max-width:1199px)').matches) closeListeningPanel(false);
    navigate(kind,{title:name,artist:state?.playback?.track?.artist});
  }
};
function showDevice() {connection.open();}
$('device-button').onclick=showDevice; $('about-demo').onclick=showDevice;
$('mobile-device').onclick=showDevice;
$('play').onclick=()=>command(state?.playback?.state==='playing'?'pause':'resume');
$('next').onclick=()=>command('next'); $('previous').onclick=()=>command('previous');
$('favorite').onclick=()=>command('favorite',{value:!state?.playback?.favorite});
$('shuffle').onclick=()=>command('mode',{value:state?.playback?.mode==='random'?'list_once':'random'});
$('repeat').onclick=()=>command('mode',{value:state?.playback?.mode==='repeat_list'?'list_once':'repeat_list'});
$('volume').oninput=()=>$('volume-value').textContent=$('volume').value;
$('volume').onchange=()=>command('volume',{value:Number($('volume').value)});
$('now-open').onclick=()=>toggleListeningPanel(false,$('now-open'));
$('close-now').onclick=()=>closeListeningPanel();
for (const id of ['play','next','previous','favorite','shuffle','repeat']) $('large-'+id).onclick=()=>$(id).click();
$('large-volume').oninput=()=>$('large-volume-value').textContent=$('large-volume').value;
$('large-volume').onchange=()=>command('volume',{value:Number($('large-volume').value)});
$('queue-button').onclick=()=>toggleListeningPanel(true,$('queue-button'));
$('refresh').onclick=()=>{renderCatalogue();$('catalogue-dialog').showModal();};
$('search').oninput=()=>{
  if(canBrowse() && !libraryLoading) {renderView();updatePlayer();}
};
document.addEventListener('keydown',event=>{
  if(event.key==='Escape' && !$('now-panel').hidden && !document.querySelector('dialog[open]')) closeListeningPanel();
  if(event.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName) && !document.querySelector('dialog[open]')) {event.preventDefault(); $('search').focus();}
});
async function poll() {await refreshState(); pollTimer=setTimeout(poll,1500);}
window.addEventListener('pagehide',()=>clearTimeout(pollTimer));
window.addEventListener('pageshow',event=>{if(event.persisted) poll();});
$('language').value=getLocale();
$('language').onchange=()=>setLocale($('language').value);
window.addEventListener('disc-language-change',()=>{
  $('language').value=getLocale();
  updateThemeChoice(); updateNav(); updatePlayer(); editLabels(); importer.render(); sound.render();
  if (state) {
    $('connection-label').textContent = state.demo ? t('demo_mode') : ({ready:t('connected'),connecting:t('connecting'),reconnecting:t('reconnecting'),disconnected:t('disconnected')}[state.connection] || state.connection);
    $('output-label').textContent = state.demo ? t('demo_no_audio') : t('on_disc');
  }
  if (!libraryLoading && canBrowse()) renderView(); else if(!libraryLoading) renderDisconnected();
  renderCatalogue(); updatePlayer();
  renderQueue();updateQueueControls();
  if ($('device-dialog').open) showDevice();
});
await refreshState(); await loadView(); pollTimer=setTimeout(poll,1500);

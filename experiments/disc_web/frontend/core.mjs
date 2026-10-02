export function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
export function timeLabel(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '—:—';
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}
export function trackColumns(items) {
  return {album:items.some(item=>Boolean(item.album)),
    duration:items.some(item=>Number.isFinite(item.duration)&&item.duration>=0)};
}
export function filterItems(items, query) {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return items.filter(item => {
    const fields = ['artist','playlist'].includes(item.type) ? [item.title]
      : item.type==='album' ? [item.title,item.artist,...(item.artists||[])]
      : [item.title,item.artist,item.album];
    const text=fields.filter(Boolean).join(' ').toLocaleLowerCase();
    return words.every(word=>text.includes(word));
  });
}
export function searchKind(view) {
  return ({home:'albums',albums:'albums',artist:'albums',artists:'artists',playlists:'playlists'})[view] || 'tracks';
}
// A track artist scopes a selection; it is not an inferred album-artist tag.
export function albumScope(item) {
  if(item?.scope_genre) return '';
  if(item?.scope_artist) return item.scope_artist;
  if(item?.artists?.length>1) return '';
  return item?.artist || item?.artists?.[0] || '';
}
export function navigationRoute(view,item=null) {
  return {view,name:item?.title || '',artist:view==='album'?albumScope(item):'',
    ...(['album','albums','tracks'].includes(view)&&item?.scope_genre?{genre:item.scope_genre}:{})};
}
export function routeHash(route) {
  return '#' + new URLSearchParams({view:route.view, ...(route.name ? {name:route.name} : {}), ...(route.artist ? {artist:route.artist} : {}), ...(route.genre ? {genre:route.genre} : {})});
}
export function parseRoute(hash) {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const view = params.get('view') || 'home';
  return {view:['home','albums','artists','tracks','favorites','playlists','album','artist','playlist'].includes(view) ? view : 'home', name:params.get('name') || '', artist:params.get('artist') || '', ...(['albums','album','tracks'].includes(view)&&params.get('genre')?{genre:params.get('genre')}:{})};
}

export function trackDuration(track) {
  return Number.isFinite(track?.duration_ms) ? track.duration_ms / 1000
    : Number.isFinite(track?.duration) ? track.duration : null;
}
export function playbackIdentity(state) {
  return JSON.stringify([state?.generation, state?.playback?.source, state?.playback?.track]);
}
export function coverIdentity(state) {
  const track=state?.playback?.track;
  return JSON.stringify([track?.title,track?.artist,track?.album,track?.path,
    track?.queue_position,track?.duration_ms,state?.generation]);
}
export function artworkSource(value) {
  return typeof value==='string' && (/^\/art\/cover-[0-7]\.svg$/.test(value)
    || /^\/api\/artwork\/[0-9a-f]{64}$/.test(value)) ? value : null;
}
export function seekAllowed(state) {
  const duration = trackDuration(state?.playback?.track);
  return state?.connection === 'ready' && ['playing','paused'].includes(state.playback.state)
    && Number.isFinite(duration) && duration >= 1;
}

export function mediaFormat(track) {
  const extension = track?.path?.split('.').pop()?.toLowerCase();
  return ['flac','wav','aiff','aif','alac','mp3','aac','m4a','ogg','opus','dsf','dff','iso','ape','wma'].includes(extension)
    ? extension.toUpperCase() : null;
}
export function queueTrackMatches(item, track) {
  return Number.isInteger(track?.queue_position) && item.position === track.queue_position
    && item.title === track.title && (item.artist || '') === (track.artist || '');
}

// Optional observations only: no quality tier, output route or compressed-bitrate inference.
export function trackMetadata(track, language='en') {
  const data=track?.metadata || track || {}, rows=[];
  const positive=value=>Number.isInteger(value)&&value>0;
  if(positive(data.sample_rate_hz)) rows.push(['metadata_sample_rate',
    new Intl.NumberFormat(language,{maximumFractionDigits:3}).format(data.sample_rate_hz/1000)]);
  if(positive(data.bit_depth) && data.is_dsd!==true) rows.push(['metadata_bit_depth',data.bit_depth]);
  if(positive(data.channels)) rows.push(['metadata_channels',data.channels]);
  if(typeof data.genre==='string' && data.genre.trim()) rows.push(['metadata_genre',data.genre]);
  if(positive(data.track_number)) rows.push(['metadata_track_number',data.track_number]);
  const flags=['dsd','sacd','cue','m3u'].filter(key=>data['is_'+key]===true).map(key=>key.toUpperCase());
  if(flags.length) rows.push(['metadata_source',flags.join(' · ')]);
  return rows;
}

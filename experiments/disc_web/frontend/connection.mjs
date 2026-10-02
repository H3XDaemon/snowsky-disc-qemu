import {requestId} from './request.mjs';
import {t} from './i18n.mjs';
import {escapeHTML as esc} from './core.mjs';

const storageKey='disc-web.connection';
export function normalizeConnection(value) {
  if(!value || typeof value.host!=='string') return null;
  const host=value.host.trim()==='localhost'?'127.0.0.1':value.host.trim();
  const parts=host.split('.');
  if(parts.length!==4 || parts.some(part=>!/^\d{1,3}$/.test(part)||String(Number(part))!==part||Number(part)>255)) return null;
  const [a,b]=parts.map(Number);
  if(!(a===10||a===127||(a===172&&b>=16&&b<=31)||(a===192&&b===168)||(a===169&&b===254))) return null;
  if(![value.tcp_port,value.http_port].every(port=>Number.isInteger(port)&&port>=1&&port<=65535)) return null;
  return {host,tcp_port:value.tcp_port,http_port:value.http_port};
}
const connectionKey=emulator=>storageKey+(emulator?'.emulator':'');
export function savedConnection(storage, emulator=false) {
  try {
    const config=normalizeConnection(JSON.parse(storage.getItem(connectionKey(emulator))));
    return !emulator&&config?.host.startsWith('127.')?null:config;
  } catch {return null;}
}
export function connectionDraft(state, saved) {
  if(state?.demo) return {host:'',tcp_port:12100,http_port:12103};
  if(!state?.endpoint&&saved) return saved;
  return {host:state?.endpoint||'',tcp_port:state?.tcp_port||12100,http_port:state?.http_port||12103};
}

export function createConnection({getState,isBusy,refreshState,api,command,setBusy}) {
  const $=id=>document.getElementById(id);
  let generation=null, pending=false, searching=false, feedback='', searchFeedback='', candidates=[], requestVersion=0;
  let connectionAttempt=null;
  const values=()=>({host:$('connection-host').value,tcp_port:Number($('connection-tcp').value),http_port:Number($('connection-http').value)});
  function fill(value) {
    $('connection-host').value=value.host;
    $('connection-tcp').value=value.tcp_port;
    $('connection-http').value=value.http_port;
  }
  function render() {
    if(!$('device-dialog').open) return;
    const state=getState(), demo=state?.demo, locked=pending||isBusy();
    if(connectionAttempt?.accepted) {
      const target=connectionAttempt.config;
      const matches=state?.endpoint===target.host&&state?.tcp_port===target.tcp_port&&state?.http_port===target.http_port;
      if(!matches||!state?.enabled) connectionAttempt=null;
      else if(state.connection==='ready') {
        connectionAttempt=null;
        $('device-dialog').close();
        return;
      }
    }
    $('device-description').textContent=t(demo?'connection_demo':'control_your_music_over_a_local_connection_audio_stays_on_your_player');
    $('connection-presets').hidden=!state?.emulator;
    const statusKey={ready:'connected',disconnected:'disconnected',connecting:'connecting',reconnecting:'reconnecting'}[state?.connection]||'disconnected';
    $('device-endpoint').textContent=demo?t('demo_mode'):t(statusKey)+(state?.endpoint?' · '+state.endpoint:'');
    $('device-endpoint').classList.toggle('is-connected',!demo&&state?.connection==='ready');
    for(const id of ['connection-host','connection-tcp','connection-http','preset-player','preset-emulator','connect']) $(id).disabled=demo||locked;
    $('disconnect-player').hidden=demo||!state?.enabled;
    $('disconnect-player').disabled=locked;
    $('discover-player').disabled=demo||searching||!$('discovery-interface').options.length;
    $('discovery-interface').disabled=demo||searching;
    $('connect').textContent=t(pending?'connection_starting':'connect');
    $('connection-feedback').textContent=feedback?t(feedback):state?.last_error&&state?.enabled?t('connection_failed'):'';
    $('discovery-feedback').textContent=searchFeedback?t(searchFeedback,{count:candidates.length}):'';
    $('discovery-results').innerHTML=candidates.map((item,index)=>`<button class="discovered-player" data-candidate="${index}"><span><strong>SNOWSKY DISC</strong><small>${esc(item.host)}</small></span><span>${t('connection_choose')} ↗</span></button>`).join('');
    for(const button of $('discovery-results').querySelectorAll('[data-candidate]')) button.onclick=()=>{
      connectionAttempt=null;
      fill(candidates[Number(button.dataset.candidate)]); feedback=''; generation=getState()?.generation;
      $('connection-host').focus(); render();
    };
  }
  async function open() {
    if($('device-dialog').open) {render();return;}
    connectionAttempt=null;
    const state=getState();
    let saved=null;
    try {saved=savedConnection(localStorage,state?.emulator);} catch { /* Storage may be unavailable. */ }
    fill(connectionDraft(state,saved));
    generation=state?.generation; feedback=''; searchFeedback=''; candidates=[];
    $('device-dialog').showModal(); render();
    const version=++requestVersion;
    try {
      const data=await api('/api/interfaces');
      if(version!==requestVersion) return;
      $('discovery-interface').replaceChildren(...data.interfaces.map(row=>new Option(`${row.name} · ${row.address}`,row.address)));
      if(!data.interfaces.length&&!state?.demo) searchFeedback='connection_no_interface';
    } catch {searchFeedback='connection_no_interface';}
    render();
  }
  $('close-dialog').onclick=()=>$('device-dialog').close();
  $('device-dialog').addEventListener('close',()=>{connectionAttempt=null;});
  $('connection-form').addEventListener('input',()=>{connectionAttempt=null;});
  $('preset-player').onclick=()=>{connectionAttempt=null;fill({host:'',tcp_port:12100,http_port:12103});$('connection-host').focus();};
  $('preset-emulator').onclick=()=>{connectionAttempt=null;fill({host:'127.0.0.1',tcp_port:12100,http_port:12113});};
  $('disconnect-player').onclick=async()=>{
    connectionAttempt=null;
    await command('disconnect'); generation=getState()?.generation; feedback='';render();
  };
  $('connection-form').onsubmit=async event=>{
    event.preventDefault();
    if(pending||isBusy()||getState()?.demo) return;
    const config=normalizeConnection(values());
    if(!config) {feedback='connection_invalid';render();return;}
    if(generation!==getState()?.generation) {generation=getState()?.generation;feedback='connection_changed';render();return;}
    const attempt={config,accepted:false};
    connectionAttempt=attempt;
    pending=true;feedback='connection_starting';setBusy(true);render();
    try {
      await api('/api/connection',{...config,generation,request_id:requestId()});
      attempt.accepted=true;
      try {localStorage.setItem(connectionKey(getState()?.emulator),JSON.stringify(config));} catch { /* Session-only connection still works. */ }
      feedback='';
    } catch {if(connectionAttempt===attempt) connectionAttempt=null;feedback='connection_changed';}
    finally {pending=false;setBusy(false);await refreshState();generation=getState()?.generation;render();}
  };
  $('discover-player').onclick=async()=>{
    if(searching||getState()?.demo||!$('discovery-interface').value) return;
    searching=true;searchFeedback='connection_searching';candidates=[];render();
    try {
      const data=await api('/api/discover',{interface:$('discovery-interface').value,request_id:requestId()});
      candidates=data.devices.map(normalizeConnection).filter(Boolean);
      searchFeedback=candidates.length?'connection_found':'connection_none';
    } catch {searchFeedback='connection_search_failed';}
    finally {searching=false;render();}
  };
  return {open,render};
}

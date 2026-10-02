import {requestId} from './request.mjs';
import {t} from './i18n.mjs';

const names=['gain','balance','filter','dre'];
export const balanceLabel=value=>value===0?'0':`${value<0?'L':'R'}${Math.abs(value)}`;
export function soundValues(result) {
  const values=result?.confirmation?.settings;
  if(result?.status!=='observed'||!values) return null;
  const bounds={gain:[0,1],balance:[-20,20],filter:[0,5],dre:[0,1]};
  return names.every(name=>Number.isInteger(values[name])&&values[name]>=bounds[name][0]&&values[name]<=bounds[name][1])?{...values}:null;
}

export function createSound({getState,isBusy,api,refreshState}) {
  const $=id=>document.getElementById(id);
  let values=null, generation=null, pending=false, sequence=0, feedback='sound_intro';
  function render() {
    const state=getState();
    if(generation!==null&&(generation!==state?.generation||state?.connection!=='ready'||state?.demo)) {
      ++sequence; values=null; generation=null; pending=false; feedback='sound_connection_changed';
    }
    const locked=pending||isBusy()||state?.busy||state?.connection!=='ready'||state?.demo;
    $('sound-notice').textContent=t(state?.demo?'sound_demo':state?.connection!=='ready'?'sound_connect':feedback);
    $('sound-refresh').disabled=locked;
    $('sound-fields').hidden=!values;
    for(const name of names) {
      const input=$('sound-'+name);
      input.disabled=locked||!values;
      $('sound-apply-'+name).disabled=locked||!values||Number(input.value)===values[name];
    }
    $('sound-balance-value').textContent=balanceLabel(Number($('sound-balance').value));
    $('sound-balance').setAttribute('aria-valuetext',$('sound-balance-value').textContent);
  }
  function fill() {for(const name of names) $('sound-'+name).value=String(values[name]);}
  async function read() {
    if(pending||isBusy()||getState()?.busy||getState()?.demo||getState()?.connection!=='ready') return render();
    const current=++sequence;
    generation=getState().generation; pending=true; values=null; feedback='sound_loading';render();
    try {
      const result=await api('/api/sound');
      if(current!==sequence||getState().generation!==generation||result.generation!==generation) return;
      values=soundValues(result);
      feedback=values?'sound_ready':'sound_unavailable';
      if(values) fill();
    } catch {if(current===sequence) feedback='sound_unavailable';}
    finally {if(current===sequence) {pending=false;render();}}
  }
  for(const name of names) {
    $('sound-'+name).oninput=()=>{feedback='sound_draft';render();};
    $('sound-apply-'+name).onclick=async()=>{
      if($('sound-apply-'+name).disabled||!values) return;
      const current=++sequence, target=Number($('sound-'+name).value), expected=values[name];
      pending=true;feedback='sound_applying';render();
      try {
        const result=await api('/api/action',{action:'sound_setting',name,value:target,expected,
          generation,request_id:requestId()});
        if(current!==sequence||getState().generation!==generation) return;
        if(['confirmed','already_satisfied'].includes(result.status)&&result.confirmation?.name===name&&result.confirmation.value===target) {
          values[name]=target;feedback='sound_confirmed';
        } else {
          values=null;
          feedback=result.outcome==='sound_changed'?'sound_stale':result.status==='not_sent'?'sound_not_sent':'sound_uncertain';
        }
      } catch {if(current===sequence) {values=null;feedback='sound_uncertain';}}
      finally {if(current===sequence) {pending=false;render();await refreshState();}}
    };
  }
  $('sound-refresh').onclick=read;
  $('close-sound').onclick=()=>$('sound-dialog').close();
  $('open-sound').onclick=()=>{$('sound-dialog').showModal();render();read();};
  return {render};
}

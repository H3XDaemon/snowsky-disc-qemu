import {requestId} from './request.mjs';
import {t, getLocale} from './i18n.mjs';
import {escapeHTML as esc} from './core.mjs';
import {importFlow} from './import-flow.mjs';

const activePhases = new Set(['receiving','sending','verifying','scanning']);
export const jobActive = job => Boolean(job && activePhases.has(job.phase));
export const filePath = file => file.webkitRelativePath || file.name;
export const isMusicFile = file => /\.(flac|wav|mp3|m4a|aac|ogg|ape|wma|dsf|dff)$/i.test(file.name);
export function validFiles(files) {
  return files.length > 0 && files.length <= 1000 &&
    new Set(files.map(file=>filePath(file).toLowerCase())).size === files.length &&
    files.every(file=>file.size > 0 && file.size <= 2**31-1 &&
      !/[\\\x00-\x1f\x7f:*?"<>|]/.test(filePath(file)) &&
      new TextEncoder().encode('/tmp/sdcard/'+filePath(file)).length <= 1023 &&
      filePath(file).split('/').every(part=>part && !['.','..'].includes(part) &&
        part===part.trim() && !part.endsWith('.') && new TextEncoder().encode(part).length <= 240) &&
      isMusicFile(file));
}
const sizeLabel = size => {
  const power=size>=1024**3?3:size>=1024**2?2:size>=1024?1:0;
  return new Intl.NumberFormat(getLocale(),{style:'unit',unit:['byte','kilobyte','megabyte','gigabyte'][power],maximumFractionDigits:1}).format(size/1024**power);
};

export function createImporter({getState,isBusy,refreshState,loadView,api,toast,syncCatalogue,showLibrary}) {
  const $=id=>document.getElementById(id);
  let files=[], transferring=false, feedback='', refreshedJob=null, dismissedJob=null, folderName='', skipped=0;
  let batchGeneration=null, selectionJob=null;
  function render() {
    const state=getState(), job=state?.job, active=jobActive(job), locked=transferring||active||state?.busy||isBusy();
    const flow=importFlow(state,{files,batchGeneration,selectionJob,transferring});
    $('import-active').hidden=!active&&!transferring;
    $('open-import').title=active?t(job.kind==='scan'?'import_scanning':'import_in_progress'):t('import_music');
    $('import-notice').textContent=state?.demo?t('import_demo_notice'):state?.connection!=='ready'?t('import_connect'):'';
    $('import-notice').hidden=!$('import-notice').textContent;
    $('choose-import').disabled=locked; $('choose-folder').disabled=locked;
    $('import-folder-summary').textContent=folderName?folderName+' · '+t('import_file_count',{count:files.length})+' · '+sizeLabel(files.reduce((sum,item)=>sum+item.size,0))+(skipped?' · '+t('import_skipped',{count:skipped}):''):'';
    $('clear-import').disabled=locked||(!files.length && (job?.kind!=='upload'||job.id===dismissedJob));
    $('send-import').disabled=locked||flow.changed||state?.connection!=='ready'||!files.some(item=>item.phase==='waiting');
    $('scan-import').disabled=locked||state?.connection!=='ready';
    $('sync-import').disabled=locked||!flow.canSync||state?.connection!=='ready'||state?.demo;
    $('sync-import').textContent=t(state?.catalogue?.phase==='syncing'?'catalogue_sync_active':'catalogue_sync');
    $('import-open-library').hidden=!flow.complete;
    $('import-flow-message').textContent=t(flow.message);
    $('import-batch-count').textContent=files.length?t('import_batch_count',flow.counts):'';
    $('import-restored').hidden=Boolean(files.length)||!job||job.kind!=='upload'||job.id===dismissedJob;
    for(const [index,node] of [...$('import-steps').children].entries()) {
      if(index===flow.step) node.setAttribute('aria-current','step');
      else node.removeAttribute('aria-current');
    }
    $('import-sync-status').textContent=flow.complete?t('import_sync_saved',{count:state.catalogue.track_count}):
      state?.demo?t('import_sync_demo'):state?.catalogue?.phase==='syncing'?t('import_flow_syncing'):'';
    $('import-feedback').textContent=feedback?t(feedback):'';
    const displayed=files.length?files:(job?.kind==='upload'&&job.id!==dismissedJob?[{name:job.name,size:job.total,phase:job.phase,id:job.id}]:[]);
    $('import-list').innerHTML=displayed.map(item=>{
      const current=job?.id===item.id?job:null, phase=current?.phase||item.phase;
      const percent=current?Math.min(100,Math.round(100*current.bytes/Math.max(1,current.total))):phase==='done'?100:0;
      const label=(current?.result?.outcome||item.outcome)==='destination_exists'?'import_exists':phase==='done'&&state?.demo?'import_demo_done':'import_'+(phase==='confirmed'?'done':phase);
      return `<div class="import-file ${phase==='done'?'complete':''}"><span class="file-note" aria-hidden="true">♪</span><div class="file-info"><strong title="${esc(item.name)}">${esc(item.name.split('/').at(-1))}</strong>${item.name.includes('/')?`<span class="file-path">${esc(item.name.slice(0,item.name.lastIndexOf('/')))}</span>`:''}<small>${esc(sizeLabel(item.size))} · ${esc(t(label))}</small>${['receiving','sending','verifying'].includes(phase)?`<progress max="100" value="${percent}" aria-label="${esc(t(label))}"></progress>`:''}</div><span class="file-state">${phase==='done'?'✓':current&&jobActive(current)?percent+'%':''}</span></div>`;
    }).join('');
    $('import-drop').classList.toggle('compact',Boolean(displayed.length));
    const scan=job?.kind==='scan'&&job.generation===state?.generation&&job.id!==selectionJob?job:null;
    $('scan-status').innerHTML=scan?`${jobActive(scan)?'<span class="scan-pulse" aria-hidden="true"></span>':''}<strong>${t(scan.phase==='done'?(state?.demo?'import_demo_done':'import_scan_done'):scan.phase==='scanning'?'import_scanning':scan.phase==='not_sent'?'import_scan_not_sent':'import_scan_uncertain')}</strong><small>${t('import_discovered',{count:scan.discovered})}</small>`:'';
    if(scan?.phase==='done'&&refreshedJob!==scan.id&&!locked) {refreshedJob=scan.id;loadView();}
  }
  function choose(selected, folder=false) {
    if(transferring||jobActive(getState()?.job)||getState()?.busy||isBusy()) return;
    const all=[...selected];
    const incoming=folder?all.filter(isMusicFile):all;
    if(!all.length) return;
    if(!validFiles(incoming)) {toast(t('import_invalid'),true);return;}
    folderName=folder?filePath(incoming[0]).split('/')[0]:''; skipped=all.length-incoming.length;
    incoming.sort((a,b)=>filePath(a).localeCompare(filePath(b)));
    files=incoming.map(file=>({file,name:filePath(file),size:file.size,phase:'waiting',id:null}));
    batchGeneration=null; selectionJob=getState()?.job?.id??null;
    feedback=''; render();
  }
  $('open-import').onclick=()=>{render();$('import-dialog').showModal();};
  $('close-import').onclick=()=>$('import-dialog').close();
  $('choose-import').onclick=()=>$('import-files').click();
  $('choose-folder').onclick=()=>$('import-folder').click();
  $('import-folder').onchange=()=>{choose($('import-folder').files,true);$('import-folder').value='';};
  $('import-files').onchange=()=>{choose($('import-files').files);$('import-files').value='';};
  $('clear-import').onclick=()=>{files=[];feedback='';folderName='';skipped=0;batchGeneration=null;selectionJob=getState()?.job?.id??null;dismissedJob=selectionJob;render();};
  for(const name of ['dragenter','dragover']) $('import-drop').addEventListener(name,event=>{
    event.preventDefault(); $('import-drop').classList.add('dragging');
  });
  $('import-drop').ondragleave=()=>$('import-drop').classList.remove('dragging');
  $('import-drop').ondrop=event=>{
    event.preventDefault();$('import-drop').classList.remove('dragging');
    if([...event.dataTransfer.items].some(item=>item.webkitGetAsEntry?.()?.isDirectory)) return toast(t('import_folder_drop'));
    choose(event.dataTransfer.files);
  };
  async function observe(id) {
    while(true) {
      const ok=await refreshState(), job=getState()?.job;
      if(!ok||job?.id!==id) throw new Error('Job observation unavailable');
      if(!jobActive(job)) return job;
      await new Promise(resolve=>setTimeout(resolve,650));
    }
  }
  function send(item, state) {
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open('POST','/api/upload?name='+encodeURIComponent(item.name));
      xhr.setRequestHeader('Content-Type','application/octet-stream');
      xhr.setRequestHeader('X-Disc-Token',state.token);
      xhr.setRequestHeader('X-Disc-Generation',String(state.generation));
      xhr.setRequestHeader('X-Request-ID',item.id);
      xhr.timeout=330000;
      xhr.onload=()=>xhr.status===202?resolve():reject(new Error('Upload was not accepted'));
      xhr.onerror=xhr.ontimeout=()=>reject(new Error('Upload result unavailable'));
      xhr.send(item.file);
    });
  }
  $('send-import').onclick=async()=>{
    if($('send-import').disabled) return;
    transferring=true; feedback='';
    const original=getState();
    batchGeneration=original.generation;
    try {
      for(const item of files.filter(item=>item.phase==='waiting')) {
        if(getState()?.generation!==original.generation||getState()?.connection!=='ready') throw new Error('Connection changed');
        item.id=requestId(); item.phase='receiving'; render();
        try {
          await send(item,original);
          const job=await observe(item.id);
          item.phase=job.phase; item.outcome=job.result?.outcome;
          if(job.phase!=='done') throw new Error('Unconfirmed result');
        } catch(error) {if(activePhases.has(item.phase)) item.phase='uncertain'; throw error;}
      }
      feedback=original.demo?'import_demo_done':'import_scan_ready';
    } catch {feedback='import_stop_batch';await refreshState();}
    finally {transferring=false;render();}
  };
  $('scan-import').onclick=async()=>{
    if($('scan-import').disabled) return;
    transferring=true; feedback='';render();
    try {
      await api('/api/scan',{generation:getState().generation,request_id:requestId()});
    } catch {toast(t('import_scan_uncertain'),true);}
    finally {transferring=false;await refreshState();render();}
  };
  $('sync-import').onclick=async()=>{
    if($('sync-import').disabled) return;
    await syncCatalogue(); render();
  };
  $('import-open-library').onclick=()=>{$('import-dialog').close();showLibrary();};
  return {render};
}

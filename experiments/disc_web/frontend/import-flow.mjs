// Presentation from observed jobs only. This module never dispatches operations.
export function importFlow(state, {files=[], batchGeneration=null, selectionJob=null, transferring=false}={}) {
  const job=state?.job?.id!==selectionJob?state?.job:null, catalogue=state?.catalogue;
  const changed=(batchGeneration!==null&&batchGeneration!==state?.generation)||
    (job&&job.generation!==state?.generation);
  const observed=files.map(file=>job&&job.id===file.id&&!changed?{...file,phase:job.phase}:file);
  const counts={total:files.length,done:observed.filter(f=>f.phase==='done').length,
    waiting:observed.filter(f=>f.phase==='waiting').length};
  const result=(step,message,canSync=false,complete=false)=>({step,message,canSync,complete,changed:Boolean(changed),counts});
  if(changed) return result(0,'import_flow_changed');
  const scan=job?.kind==='scan'&&job.id!==selectionJob?job:null;
  if(scan?.phase==='scanning') return result(1,'import_flow_scanning');
  if(transferring||['receiving','sending','verifying'].includes(job?.phase)) return result(0,'import_flow_transferring');
  if(catalogue?.phase==='syncing') return result(2,'import_flow_syncing');
  if(scan) {
    if(scan.phase!=='done') return result(1,scan.phase==='not_sent'?'import_scan_not_sent':'import_scan_uncertain');
    if(state.demo) return result(2,'import_flow_demo');
    if(catalogue?.available&&!catalogue.stale&&catalogue.phase==='done') return result(3,
      observed.some(file=>file.phase!=='done')?'import_flow_partial_saved':'import_flow_complete',false,true);
    return result(2,catalogue?.phase==='failed'?'import_flow_sync_failed':'import_flow_sync_ready',true);
  }
  if(observed.some(file=>['uncertain','not_sent'].includes(file.phase))||
    (!files.length&&job?.kind==='upload'&&['uncertain','not_sent'].includes(job.phase))) return result(0,'import_flow_check');
  if(counts.waiting) return result(0,'import_flow_selected');
  if(counts.done||(!files.length&&job?.kind==='upload'&&job.phase==='done')) return result(1,'import_flow_scan_ready');
  return result(0,'import_flow_choose');
}

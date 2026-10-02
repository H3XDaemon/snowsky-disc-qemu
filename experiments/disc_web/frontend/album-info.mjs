// Read presentation metadata only for visible album cards, without changing playback.
export function createAlbumInfo({api,getState,isBusy,caption}) {
  let observer, version=0, queue=[], running=false;
  const cache=new Map();
  async function drain() {
    if(running) return;
    running=true;
    try {
      while(queue.length) {
        const job=queue.shift();
        if(job.version!==version || isBusy() || getState()?.generation!==job.generation) continue;
        try {
          const params=new URLSearchParams({kind:'album_info',name:job.item.title,artist:job.item.scope_artist||''});
          const data=await api(`/api/library?${params}`);
          if(data.generation!==job.generation || getState()?.generation!==job.generation) continue;
          cache.set(job.key,{data,at:Date.now()});
          if(cache.size>256) cache.delete(cache.keys().next().value);
          if(job.version===version) apply(job.node,job.item,data);
        } catch { /* Keep the known count when optional metadata is unavailable. */ }
      }
    } finally {running=false;}
  }
  function apply(node,item,data) {
    item.count=data.count;
    item.artists=data.artists;
    // Multiple track artists do not establish a single album artist.
    item.artist=data.artists.length===1?data.artists[0]:'';
    node.querySelector('p').replaceChildren(...caption(item).split('\n').map(text=>{
      const span=document.createElement('span');span.textContent=text;span.title=text;return span;
    }));
  }
  function observe(root,items) {
    observer?.disconnect(); queue=[]; version++;
    if(getState()?.demo || getState()?.catalogue?.available) return;
    const generation=getState()?.generation, current=version;
    observer=new IntersectionObserver(entries=>{
      for(const entry of entries) {
        if(!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        const item=items[Number(entry.target.querySelector('[data-card]').dataset.card)];
        if(item?.type!=='album') continue;
        const key=JSON.stringify([generation,item.title,item.scope_artist||'']), saved=cache.get(key);
        if(saved && Date.now()-saved.at<60000) apply(entry.target,item,saved.data);
        else queue.push({node:entry.target,item,key,generation,version:current});
      }
      drain();
    });
    for(const node of root.querySelectorAll('.album-card')) observer.observe(node);
  }
  function clear() {observer?.disconnect();queue=[];version++;cache.clear();}
  return {observe,clear};
}

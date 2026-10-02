// getRandomValues also works on HTTP LAN origins where randomUUID is unavailable.
export function requestId(random=globalThis.crypto) {
  return Array.from(random.getRandomValues(new Uint8Array(16)), byte=>byte.toString(16).padStart(2,'0')).join('');
}

// Only a busy read may be retried. Mutations and transport failures are never replayed.
export async function requestJSON(path, options={}, fetcher=fetch, pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))) {
  const write=options.body!==undefined;
  for(let attempt=0;;attempt++) {
    const response=await fetcher(path,write?{method:'POST',headers:{'Content-Type':'application/json','X-Disc-Token':options.token||''},body:JSON.stringify(options.body)}:{});
    const data=await response.json();
    if(!write && response.status===409 && attempt<6) {
      await pause(Math.min(250*2**attempt,2000));
      continue;
    }
    if(!response.ok) throw new Error('Request failed');
    return data;
  }
}

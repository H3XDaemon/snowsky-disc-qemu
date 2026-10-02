// Shared dismissal and scroll ownership for every native modal, including menus.
export function setupDialogs(doc=document, win=window) {
  const dialogs=[...doc.querySelectorAll('dialog')];
  const root=doc.documentElement;
  let saved=null;
  const sync=()=>{
    const open=dialogs.some(dialog=>dialog.open);
    if(open&&!saved) {
      saved={x:win.scrollX,y:win.scrollY,url:win.location.href};
      root.style.setProperty('--dialog-scroll-y',`${-saved.y}px`);
      root.classList.add('modal-open');
    } else if(!open&&saved) {
      const previous=saved;
      saved=null;
      root.classList.remove('modal-open');
      root.style.removeProperty('--dialog-scroll-y');
      const samePage=previous.url===win.location.href;
      win.scrollTo({left:samePage?previous.x:0,top:samePage?previous.y:0,behavior:'instant'});
    }
  };
  const observer=new win.MutationObserver(sync);
  for(const dialog of dialogs) {
    let press=null;
    const outside=event=>{
      const rect=dialog.getBoundingClientRect();
      return event.target===dialog&&(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom);
    };
    dialog.addEventListener('pointerdown',event=>{
      press=event.button===0&&event.isPrimary&&outside(event)?{x:event.clientX,y:event.clientY}:null;
    });
    dialog.addEventListener('pointercancel',()=>{press=null;});
    dialog.addEventListener('click',event=>{
      const start=press;
      press=null;
      if(start&&outside(event)&&Math.hypot(event.clientX-start.x,event.clientY-start.y)<=8) dialog.close();
    });
    dialog.addEventListener('close',()=>{press=null;sync();});
    observer.observe(dialog,{attributes:true,attributeFilter:['open']});
  }
  sync();
}

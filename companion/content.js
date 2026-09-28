if(location.origin===globalThis.LP_APP_ORIGIN) {
  const send=(type,extra={})=>window.postMessage({source:'lp-companion',type,...extra},location.origin);
  window.addEventListener('message',event=>{
    if(event.source!==window||event.origin!==location.origin||event.data?.source!=='lp-optimizer')return;
    if(event.data.type==='PING'){send('READY',{preview:true});chrome.runtime.sendMessage({type:'WAKE'}).catch(()=>{});}
    if(['PREVIEW_CONNECT','PREVIEW_RESTORE','PREVIEW_TASK','PREVIEW_DISCONNECT'].includes(event.data.type) && typeof event.data.id==='string'){
      const {type,id,task}=event.data;
      chrome.runtime.sendMessage({type,task}).then(result=>send('PREVIEW_REPLY',{id,result})).catch(()=>send('PREVIEW_REPLY',{id,result:{status:'browser_required'}}));
    }
    if(event.data.type==='PAIR'&&typeof event.data.token==='string')chrome.runtime.sendMessage({type:'PAIR',token:event.data.token}).then(result=>send('PAIRED',result)).catch(()=>send('PAIRED',{ok:false,message:'Reload this tab after updating the companion.'}));
    if(event.data.type==='DISCONNECT')chrome.runtime.sendMessage({type:'DISCONNECT'}).catch(()=>{});
  });
  send('READY',{preview:true});
  // Only the visible app tab accelerates wake-ups; the alarm handles restarts.
  setInterval(()=>{if(document.visibilityState==='visible')chrome.runtime.sendMessage({type:'WAKE'}).catch(()=>{});},10000);
}

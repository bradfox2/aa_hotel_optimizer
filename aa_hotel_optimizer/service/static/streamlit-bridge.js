// Use Streamlit's session-scoped widget channel, with no private HTTP server.
export default function(component) {
  const root=component.parentElement;
  let runtime=root.lpRuntime;
  if(!runtime){
    const queue=[];
    let active=null;
    runtime={send:component.setTriggerValue,queue};
    root.lpRuntime=runtime;
    const pump=()=>{
      if(active||!queue.length)return;
      active=queue.shift();
      runtime.send('request',active.event);
      // Retain only the correlation ID after handing a request to Streamlit.
      active.event={id:active.event.id};
    };
    runtime.receive=response=>{
      if(!response||response.id!==active?.event.id)return;
      const item=active;active=null;
      if(response.status>=400){
        const error=new Error(response.data.detail?.message||'Please try again.');
        error.status=response.status;error.code=response.data.detail?.code;item.reject(error);
      }else item.resolve(response.data);
      queueMicrotask(pump);
    };
    const transport=(path,{method='GET',body}={})=>new Promise((resolve,reject)=>{
      queue.push({event:{id:crypto.randomUUID(),path,method,body},resolve,reject});
      queueMicrotask(pump);
    });
    runtime.cleanup=mountApp(root,transport);
    const host=root.host||root;
    const observer=new MutationObserver(()=>{
      if(!host.isConnected){runtime.cleanup();observer.disconnect();}
    });
    observer.observe(document.body,{childList:true,subtree:true});
  }
  runtime.send=component.setTriggerValue;
  runtime.receive(component.data?.response);
}

import './config.js';
import {providerRequest} from './provider.js';

const APP=globalThis.LP_APP_ORIGIN;
const PROVIDER='https://www.aadvantagehotels.com/*';
let working=false;
chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});
chrome.storage.session.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});
const previewBusy=new Set();
let previewGeneration=0;

async function previewRequest(message,sender){
  const key='preview:'+sender.tab.id+':'+sender.frameId;
  if(message.type==='PREVIEW_DISCONNECT'){
    previewGeneration++;
    await chrome.storage.session.remove(key);
    await chrome.storage.local.remove('previewAccount');
    await chrome.storage.local.set({connectionState:'not_connected'});
    return {status:'ok'};
  }
  if(previewBusy.has(key))return {status:'rate_limited'};
  previewBusy.add(key);
  const generation=previewGeneration;
  try{
    if(['PREVIEW_CONNECT','PREVIEW_RESTORE'].includes(message.type)){
      const {previewAccount}=await chrome.storage.local.get('previewAccount');
      if(message.type==='PREVIEW_RESTORE'&&!previewAccount)return {status:'not_connected'};
      const result=await inProvider({kind:'session',...(message.type==='PREVIEW_RESTORE'?{account_fingerprint:previewAccount.fingerprint}:{})},true);
      if(generation!==previewGeneration)return {status:'browser_required'};
      if(result.status==='ok'){
        await chrome.storage.session.set({[key]:{fingerprint:result.account_fingerprint,next:0}});
        await chrome.storage.local.set({previewAccount:{fingerprint:result.account_fingerprint,label:result.account_label}});
      }
      else await chrome.storage.session.remove(key);
      await chrome.storage.local.set({connectionState:result.status==='ok'?'connected':result.status});
      return result;
    }
    const saved=(await chrome.storage.session.get(key))[key];
    const {previewAccount}=await chrome.storage.local.get('previewAccount');
    if(!saved||!previewAccount||saved.fingerprint!==previewAccount.fingerprint)return {status:'browser_required'};
    if(Date.now()<saved.next)return {status:'rate_limited'};
    const task=message.task;
    if(!task||!['places','start','results'].includes(task.kind)||JSON.stringify(task).length>10000)return {status:'provider_error'};
    await chrome.storage.session.set({[key]:{...saved,next:Date.now()+2000}});
    const result=await inProvider({...task,account_fingerprint:saved.fingerprint},true);
    if(result.status==='account_changed'){
      await chrome.storage.session.remove(key);
      await chrome.storage.local.set({connectionState:'reauth_required'});
    }
    return result;
  }finally{previewBusy.delete(key);}
}

async function call(path,body,key) {
  const response=await fetch(APP+path,{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json',...(key?{Authorization:'Bearer '+key}:{})},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
  const data=await response.json();
  if(!response.ok){const error=new Error(data.detail?.message||'Open LP Optimizer and reconnect.');error.status=response.status;error.code=data.detail?.code;throw error;}
  return data;
}
async function inProvider(task,openIfNeeded=false) {
  const tabs=await chrome.tabs.query({url:PROVIDER});
  let tab=tabs.find(t=>t.active)||tabs[0];
  if(!tab?.id && openIfNeeded){
    tab=await chrome.tabs.create({url:'https://www.aadvantagehotels.com/',active:false});
    await new Promise(resolve=>{
      const timer=setTimeout(done,15000);
      function done(){clearTimeout(timer);chrome.tabs.onUpdated.removeListener(listener);resolve();}
      function listener(id,change){if(id===tab.id&&change.status==='complete')done();}
      chrome.tabs.onUpdated.addListener(listener);
      chrome.tabs.get(tab.id).then(current=>{if(current.status==='complete')done();}).catch(done);
    });
  }
  if(!tab?.id)return {status:'browser_required'};
  try {const results=await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',func:providerRequest,args:[task]});return results[0]?.result||{status:'provider_error'};}
  catch{return {status:'browser_required'};}
}
async function heartbeat(key,result) {
  const state=result.status==='ok'?'connected':result.status==='reauth_required'?'reauth_required':'browser_required';
  await call('/v1/bridge/heartbeat',{state,...(result.status==='ok'?{account_fingerprint:result.account_fingerprint,account_label:result.account_label}:{})},key);
  await chrome.storage.local.set({connectionState:state});
  return state;
}
async function tick(force=false) {
  if(working)return;
  working=true;
  try {
    const {bridgeKey,account,connectionState}=await chrome.storage.local.get(['bridgeKey','account','connectionState']);
    if(!bridgeKey)return;
    if(connectionState==='reauth_required' && !force)return;
    // A short batch avoids relying on service-worker timers for durability.
    // The alarm restarts progress if Chrome suspends this worker between batches.
    const until=Date.now()+20000;
    const tabs=await chrome.tabs.query({url:PROVIDER});
    // Idle tabs heartbeat to our service only. Do not poll AA continuously when
    // there is no search. Every actual task checks the current AA session.
    let session=!tabs.length?{status:'browser_required'}:account?{status:'ok',...account}:await inProvider({kind:'session'});
    if(await heartbeat(bridgeKey,session)!=='connected')return;
    while(Date.now()<until) {
      const {task}=await call('/v1/bridge/tasks/claim',{},bridgeKey);
      if(!task)break;
      const result=await inProvider(task);
      if(result.status==='ok'){
        await heartbeat(bridgeKey,result);
        await chrome.storage.local.set({account:{account_fingerprint:result.account_fingerprint,account_label:result.account_label}});
      } else if(result.status==='reauth_required'){
        await chrome.storage.local.remove('account');
        await chrome.storage.local.set({connectionState:'reauth_required'});
      }
      await call('/v1/bridge/tasks/'+encodeURIComponent(task.id)+'/result',{
        lease_token:task.lease_token,status:result.status,data:result.data||{}
      },bridgeKey);
      if(result.status!=='ok')break;
      await new Promise(resolve=>setTimeout(resolve,2200));
    }
  } catch(error) {
    if(error.status===401){await chrome.storage.local.remove('bridgeKey');await chrome.storage.local.set({connectionState:'not_connected'});}
    else if(error.code==='account_changed'){
      await chrome.storage.local.remove('account');
      await chrome.storage.local.set({connectionState:'reauth_required'});
    }
    // Never log API bodies, provider responses, session details or keys.
  } finally {working=false;}
}
if(chrome.alarms){
  chrome.alarms.create('lp-work',{periodInMinutes:0.5});
  chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='lp-work')tick();});
}
chrome.runtime.onStartup.addListener(()=>tick());
chrome.tabs.onUpdated.addListener((_id,change,tab)=>{
  if(change.status==='complete' && tab.url?.startsWith('https://www.aadvantagehotels.com/'))tick(true);
});
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  let origin;
  try{origin=new URL(sender.url).origin;}catch{return;}
  if(origin!==APP && !sender.url?.startsWith(chrome.runtime.getURL('')))return;
  if(['PREVIEW_CONNECT','PREVIEW_RESTORE','PREVIEW_TASK','PREVIEW_DISCONNECT'].includes(message.type)){
    if(origin!==APP||!sender.tab?.id)return;
    previewRequest(message,sender).then(reply).catch(()=>reply({status:'provider_error'}));
    return true;
  }
  if(message.type==='PAIR') {
    if(origin!==APP||typeof message.token!=='string'||message.token.length>100)return;
    (async()=>{
      try {
        const paired=await call('/v1/bridge/pair',{token:message.token},'pair_'+message.token);
        await chrome.storage.local.remove('account');
        await chrome.storage.local.set({bridgeKey:paired.bridge_key,connectionId:paired.connection_id});
        const result=await inProvider({kind:'session'});
        const state=await heartbeat(paired.bridge_key,result);
        if(state==='connected')await chrome.storage.local.set({account:{account_fingerprint:result.account_fingerprint,account_label:result.account_label}});
        reply({ok:state==='connected',message:state==='connected'?'Connected.':'Open AA Hotels, sign in, and keep the tab open.'});
        tick();
      } catch(error){reply({ok:false,message:error.message});}
    })();return true;
  }
  if(message.type==='DISCONNECT'){chrome.storage.local.remove(['bridgeKey','connectionId','account']).then(()=>chrome.storage.local.set({connectionState:'not_connected'}));reply({ok:true});}
  if(message.type==='WAKE'){tick(Boolean(message.force));reply({ok:true});}
});

import './config.js';
import {providerRequest} from './provider.js';

const APP=globalThis.LP_APP_ORIGIN;
const PROVIDER='https://www.aadvantagehotels.com/*';
let working=false;
chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});

async function call(path,body,key) {
  const response=await fetch(APP+path,{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json',...(key?{Authorization:'Bearer '+key}:{})},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
  const data=await response.json();
  if(!response.ok){const error=new Error(data.detail?.message||'Open LP Optimizer and reconnect.');error.status=response.status;error.code=data.detail?.code;throw error;}
  return data;
}
async function inProvider(task) {
  const tabs=await chrome.tabs.query({url:PROVIDER});
  const tab=tabs.find(t=>t.active)||tabs[0];
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
chrome.alarms.create('lp-work',{periodInMinutes:0.5});
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='lp-work')tick();});
chrome.runtime.onStartup.addListener(()=>tick());
chrome.tabs.onUpdated.addListener((_id,change,tab)=>{
  if(change.status==='complete' && tab.url?.startsWith('https://www.aadvantagehotels.com/'))tick(true);
});
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  let origin;
  try{origin=new URL(sender.url).origin;}catch{return;}
  if(origin!==APP && !sender.url?.startsWith(chrome.runtime.getURL('')))return;
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

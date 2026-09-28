export function mountApp(root=document, transport=null) {
const $ = (id) => root.querySelector('#'+id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => new Intl.NumberFormat('en-US').format(value);
const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:cents % 100 ? 2 : 0}).format(cents/100);
const day = value => new Date(value+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'});
const iso = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const state = {mode:'trip',config:{},me:null,result:null,companion:false,poll:null,busy:false};
let toastTimer, accountTimer;
const listeners = new AbortController();
const preview = () => state.config.deployment==='streamlit';

async function api(path, {method='GET',body,headers={}}={}) {
  if(transport)return transport(path,{method,body,headers});
  const response = await fetch(path, {method,credentials:'same-origin',headers:{...(body !== undefined ? {'Content-Type':'application/json'} : {}),...headers}, ...(body !== undefined ? {body:JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail || {};
    const error = new Error(detail.issues?.[0]?.message || detail.message || 'Please try again.');
    error.code = detail.code; error.status = response.status; throw error;
  }
  return data;
}
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,5000); }
function notice(message) { $('notice').textContent=message; $('notice').hidden=!message; }
function modal(html, label='LP OPTIMIZER') { $('dialog-content').innerHTML=html; $('dialog-eyebrow').textContent=label; if (!$('dialog').open) $('dialog').showModal(); }
function modalError(error) { let element=$('dialog-error'); if (!element) {element=document.createElement('p');element.id='dialog-error';element.className='form-error';element.setAttribute('role','alert');$('dialog-content').append(element);}element.textContent=error.message; }
$('close-dialog').onclick=()=>$('dialog').close();
$('dialog').addEventListener('click',event=>{if(event.target===$('dialog')){const r=$('dialog').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('dialog').close();}});

function formRequest() {
  const bonus=Number($('partner-bonus').value);
  const policy={card_lp_per_dollar:$('card-lp').checked?1:0,card_miles_per_dollar:Number($('card-miles').value),partner_bonus_percent:bonus};
  if(bonus) Object.assign(policy,{bonus_start:$('bonus-start').value,bonus_end:$('bonus-end').value,bonus_remaining:Number($('bonus-remaining').value)});
  return {mode:state.mode,cities:state.mode==='trip'?[$('city').value.trim()]:$('cities').value.split('\n').map(x=>x.trim()).filter(Boolean),
    check_in:$('check-in').value,check_out:$('check-out').value,adults:Number($('adults').value),rooms:Number($('rooms').value),
    budget_cents:$('budget').value?Math.round(Number($('budget').value)*100):null,
    objective:$('objective').value,split_bookings:$('split').checked,include_multi_night:true,
    max_hotel_changes:Number($('hotel-changes').value),max_bookings:state.mode==='trip'?14:Number($('max-bookings').value),max_overlaps:state.mode==='status'?Number($('max-overlaps').value):1,
    starting_lp:state.mode==='status'?Number($('current-lp').value):0,target_lp:state.mode==='status'?Number($('target-lp').value):200000,
    refundable_only:$('refundable').checked,min_stars:Number($('min-stars').value),policy};
}
function setMode(mode) {
  state.mode=mode;
  for(const button of root.querySelectorAll('[data-mode]'))button.setAttribute('aria-selected',String(button.dataset.mode===mode));
  $('city-field').hidden=mode!=='trip';$('city').required=mode==='trip';$('cities-field').hidden=mode!=='status';
  $('status-fields').hidden=mode!=='status';$('trip-options').hidden=mode!=='trip';
  $('form-title').textContent=mode==='trip'?'Where are you staying?':'How far from your next status?';
  $('form-description').textContent=mode==='trip'?"We'll compare whole stays and split bookings.":'Compare cities and dates to close your LP gap.';
  $('check-in-label').textContent=mode==='trip'?'Check-in':'Earliest check-in';$('check-out-label').textContent=mode==='trip'?'Check-out':'Last check-out';
  $('search-button').innerHTML=mode==='trip'?'Compare my stay <span aria-hidden="true">→</span>':'Find stays for my goal <span aria-hidden="true">→</span>';
  const fastest=$('objective').querySelector('[value="fastest"]');fastest.hidden=mode!=='status';
  if(mode==='trip' && $('objective').value==='fastest')$('objective').value='value';
}
root.querySelectorAll('[data-mode]').forEach(button=>button.onclick=()=>setMode(button.dataset.mode));
$('popular-cities').onclick=()=>{$('cities').value=state.config.popular_cities.join('\n');};
$('partner-bonus').onchange=()=>{$('bonus-remaining').max=$('partner-bonus').value==='25'?'25000':'500000';$('bonus-fields').hidden=$('partner-bonus').value==='0';$('bonus-start').required=$('bonus-end').required=$('partner-bonus').value!=='0';};

async function loadMe() {
  try {state.me=await api('/v1/me');} catch(error) {if(error.status!==401)throw error;state.me=null;}
  $('account-button').textContent=preview()?'Preview status':state.me?'My account':'Sign in';
  const connection=state.me?.connection;
  const connected=connection?.state==='connected';
  $('connection-dot').classList.toggle('connected',connected);
  $('connection-title').textContent=connected?'AA Hotels connected':connection?.state==='reauth_required'?'Sign in to AA Hotels again':connection?.state==='browser_required'?'Open your AA Hotels tab':'Connect AA Hotels';
  $('connection-subtitle').textContent=connected?(connection.account_label || 'Your personal offers are ready'):'Use your personal hotel offers';
}
function signIn(reason='Save your searches and compare your personal AA Hotels offers.') {
  if(!state.config.local_preview&&!state.config.email_enabled){modal('<h2>Sign-in is being set up.</h2><p>You can explore the example while email delivery is connected.</p>');return;}
  modal(`<h2>Your next good booking starts here.</h2><p>${esc(reason)}</p><form id="login-form"><label>Email address<input id="email" type="email" autocomplete="email" placeholder="you@example.com" required maxlength="254"></label><button class="button primary full" id="email-button">Send me a sign-in link</button></form><p class="dialog-note">No password to remember. Your AA Hotels connection is handled separately in your browser.</p>`,'SIGN IN OR CREATE AN ACCOUNT');
  $('login-form').onsubmit=async event=>{
    event.preventDefault();$('email-button').disabled=true;
    try {const result=await api('/v1/auth/link',{method:'POST',body:{email:$('email').value}});
      if(result.development_link) {
        modal(`<h2>Local preview sign-in</h2><p>Email delivery isn't configured on this laptop. This development link lets you try the account flow.</p><a id="dev-login" class="button primary full" href="${esc(result.development_link)}">Continue to the app →</a><p class="dialog-note">This shortcut is disabled in production. Customers receive their link by email.</p>`);
        $('dev-login').onclick=async event=>{event.preventDefault();const raw=new URL(result.development_link).hash.slice(7);await consumeLogin(raw);};
      } else modal(`<h2>Check your inbox.</h2><p>${esc(result.message)}</p><button class="button outline full" id="done-login">Got it</button>`,'SIGN-IN LINK SENT');
      if($('done-login'))$('done-login').onclick=()=>$('dialog').close();
    }catch(error){modalError(error);if($('email-button'))$('email-button').disabled=false;}
  };
}
async function consumeLogin(raw) {
  try {await api('/v1/auth/consume',{method:'POST',body:{token:raw}});await loadMe();$('dialog').close();toast('You’re signed in. Your searches will be saved here.');}
  catch(error){signIn(error.message);}
}

const previewReplies=new Map();
function askCompanion(type,task){
  return new Promise((resolve,reject)=>{
    const id=crypto.randomUUID();
    const timeout=setTimeout(()=>{previewReplies.delete(id);reject(new Error('The browser companion did not respond. Reload this tab and reconnect.'));},45000);
    previewReplies.set(id,result=>{clearTimeout(timeout);resolve(result);});
    window.postMessage({source:'lp-optimizer',type,id,task},location.origin);
  });
}
async function workPreview(){
  if(!preview()||state.previewWorking||!state.previewCompanion||!['queued','running'].includes(state.result?.status))return;
  state.previewWorking=true;
  try{
    while(['queued','running'].includes(state.result?.status)){
      const {task}=await api('/v1/session/tasks/claim',{method:'POST',body:{}});
      if(!task)break;
      const result=await askCompanion('PREVIEW_TASK',task);
      const updated=await api('/v1/session/tasks/'+task.id+'/result',{method:'POST',body:{...result,lease_token:task.lease_token}});
      showResult(updated);schedulePoll(updated);
      if(result.status!=='ok'){await loadMe();break;}
      if(['queued','running'].includes(updated.status))await new Promise(resolve=>setTimeout(resolve,2200));
    }
  }catch(error){notice(error.message);await loadMe().catch(()=>{});}
  finally{state.previewWorking=false;}
}
async function restorePreview(){
  if(!preview()||!state.previewCompanion||state.previewRestoring||state.previewRestored)return;
  state.previewRestoring=true;
  try{
    const result=await askCompanion('PREVIEW_RESTORE');
    if(result.status!=='not_connected'){
      await api('/v1/session/connection',{method:'POST',body:result}).catch(()=>{});
      await loadMe();
    }
    state.previewRestored=true;
  }catch{/* A manual Connect remains available if the companion is updating. */}
  finally{state.previewRestoring=false;}
}
function previewStatus() {
  modal('<h2>The new planner is here.</h2><p>Connect the Chrome companion, sign in normally on AA Hotels, and compare your personal offers. Your AA login stays in your browser.</p><p>This preview is free. Email accounts and purchases are still being connected. Searches are kept for this session only.</p><button id="preview-connect" class="button primary full">Connect AA Hotels</button><button id="preview-pricing" class="button quiet full">See planned pricing</button>','PUBLIC PREVIEW');
  $('preview-connect').onclick=previewConnection;
  $('preview-pricing').onclick=()=>pricing();
}
function previewConnection() {
  const installed=state.previewCompanion;
  const connected=state.me?.connection.state==='connected';
  modal(`<h2>Your rates. Your browser.</h2><p>Connect once. The companion remembers this browser and reuses your AA Hotels sign-in for future searches. No commands or tokens to copy.</p><ol class="steps"><li><strong>Add the Chrome companion</strong><small>${installed?'Companion detected. You’re ready to connect.':'Chrome Web Store publication is pending. The private beta uses a one-time manual install.'}</small>${installed?'':`<button id="download-companion" class="button outline small">Download beta companion</button><details class="install-help"><summary>One-time beta install</summary><p>1. Download and unzip the companion.<br>2. Open <strong>chrome://extensions</strong> in Chrome and turn on Developer mode.<br>3. Click <strong>Load unpacked</strong>, choose the unzipped folder, then reload this planner.</p><p>The published version will install directly from the Chrome Web Store.</p></details>`}</li><li><strong>Sign in to AA Hotels</strong><small>Sign in once during setup. We reuse that session and open the hotel tab when needed. AA may occasionally require you to sign in again.</small><a class="button outline small" href="https://www.aadvantagehotels.com" target="_blank" rel="noopener noreferrer">Open AA Hotels ↗</a></li><li><strong>Connect this browser</strong><small>We’ll check that your personal offers are available.</small><button id="pair-button" class="button primary small" ${installed?'':'disabled'}>Connect AA Hotels →</button></li></ol><p id="pair-status" class="dialog-note">${installed?'Ready when you are.':'Install the companion once, then reload this page.'}</p>${connected?'<button id="session-disconnect" class="button quiet full">Disconnect AA Hotels</button>':''}`,'CONNECT AA HOTELS');
  if($('download-companion'))$('download-companion').onclick=async()=>{
    $('download-companion').disabled=true;
    try{
      const file=await api('/v1/companion/download');
      const bytes=Uint8Array.from(atob(file.base64),c=>c.charCodeAt(0));
      const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));
      const a=document.createElement('a');a.href=url;a.download=file.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      root.querySelector('.install-help').open=true;
    }catch(error){modalError(error);}
    finally{if($('download-companion'))$('download-companion').disabled=false;}
  };
  $('pair-button').onclick=async()=>{
    $('pair-button').disabled=true;$('pair-status').textContent='Checking your AA Hotels tab…';
    try{
      const result=await askCompanion('PREVIEW_CONNECT');
      await api('/v1/session/connection',{method:'POST',body:result});
      await loadMe();$('dialog').close();toast('Connected. This browser will remember your AA Hotels connection.');
    }catch(error){modalError(error);if($('pair-button'))$('pair-button').disabled=false;}
  };
  if($('session-disconnect'))$('session-disconnect').onclick=async()=>{
    await api('/v1/session/connection',{method:'DELETE'});
    askCompanion('PREVIEW_DISCONNECT').catch(()=>{});
    await loadMe();$('dialog').close();toast('AA Hotels disconnected.');
  };
}
function connectionModal() {
  if(preview())return previewConnection();
  if(!state.me)return signIn('Sign in to connect your personal AA Hotels offers.');
  const installed=state.companion;
  const store=state.config.companion_url;
  modal(`<h2>Your rates. Your browser.</h2><p>Sign in on AA Hotels as usual. The companion compares offers in that tab, without copying your AA cookies into this app.</p><ol class="steps"><li><strong>Add the browser companion</strong><small>${installed?'Companion detected. You’re ready to connect.':store?'Install it once. No developer tools or cURL commands.':'The Chrome Web Store release is being prepared. This local preview can use the companion included with the source code.'}</small>${!installed&&store?`<a class="button outline small" href="${esc(store)}" target="_blank" rel="noopener noreferrer">Get the companion ↗</a>`:''}</li><li><strong>Sign in to AA Hotels</strong><small>Keep the signed-in tab open while we compare your dates.</small><a class="button outline small" href="https://www.aadvantagehotels.com" target="_blank" rel="noopener noreferrer">Open AA Hotels ↗</a></li><li><strong>Connect this browser</strong><small>We'll check that your personal offers are available.</small><button id="pair-button" class="button primary small" ${installed?'':'disabled'}>Connect AA Hotels →</button></li></ol><p id="pair-status" class="dialog-note">${installed?'Ready when you are.':'You can explore the example without connecting.'}</p>`,'CONNECT AA HOTELS');
  $('pair-button').onclick=async()=>{
    $('pair-button').disabled=true;
    try {const result=await api('/v1/connections',{method:'POST',body:{}});window.postMessage({source:'lp-optimizer',type:'PAIR',token:result.pairing_token},location.origin);$('pair-status').textContent='Checking your AA Hotels tab…';}
    catch(error){modalError(error);$('pair-button').disabled=false;}
  };
}
$('connect-button').onclick=connectionModal;
window.addEventListener('message',async event=>{
  if(event.source!==window || event.origin!==location.origin || event.data?.source!=='lp-companion')return;
  if(event.data.type==='PREVIEW_REPLY'){const resolve=previewReplies.get(event.data.id);if(resolve){previewReplies.delete(event.data.id);resolve(event.data.result);}return;}
  if(event.data.type==='READY'){state.companion=true;state.previewCompanion=Boolean(event.data.preview);restorePreview();if($('pair-button')){$('pair-button').disabled=preview()&&!state.previewCompanion;$('pair-status').textContent=preview()&&!state.previewCompanion?'Update the beta companion, then reload this tab.':'Companion detected. Ready to connect.';}}
  if(event.data.type==='PAIRED'){
    await loadMe();
    if($('pair-status'))$('pair-status').textContent=event.data.ok?'Browser connected. Keep your AA Hotels tab open.':(event.data.message || 'Open AA Hotels, sign in, and try again.');
    if($('pair-button'))$('pair-button').disabled=false;
    if(state.me?.connection.state==='connected'){toast('AA Hotels connected.');$('dialog').close();}
  }
},{signal:listeners.signal});

async function account() {
  if(preview())return previewStatus();
  if(!state.me)return signIn();
  await loadMe();
  const user=state.me, usage=user.usage;
  modal(`<h2>Your account</h2><p>${esc(user.email)}</p><h3>${number(usage.remaining)} searches remaining</h3><p>${number(usage.free_remaining)} free · ${number(usage.trip_pass_remaining)} trip-pass${user.paid?` · ${number(usage.monthly_remaining)} this month`:''}</p>${user.cancel_at_period_end?'<p class="dialog-note">Your membership is set to cancel at the end of the current billing period. Trip-pass searches stay available.</p>':''}${user.billing_action==='portal'?'<button id="billing-button" class="button outline full">Manage or cancel membership ↗</button>':''}<button id="view-plans" class="button primary full">View passes & membership</button><hr><div class="dialog-actions"><button id="account-agents" class="button outline">Agent access</button>${user.connection.id?'<button id="disconnect-button" class="button outline">Disconnect AA Hotels</button>':''}<button id="logout-button" class="button quiet">Sign out</button></div><hr><div class="dialog-actions"><button id="export-account" class="button quiet">Export my data</button><button id="delete-account" class="button quiet">Delete account</button></div>`,'ACCOUNT & MEMBERSHIP');
  $('view-plans').onclick=()=>pricing();
  if($('billing-button'))$('billing-button').onclick=async()=>{
    $('billing-button').disabled=true;
    try {const result=await api('/v1/billing/'+(user.billing_action==='portal'?'portal':'checkout'),{method:'POST',body:{}});const url=new URL(result.url);if(url.protocol!=='https:'||!['checkout.stripe.com','billing.stripe.com'].includes(url.hostname))throw new Error('Unable to open billing. Please try again.');location.assign(url.href);}
    catch(error){modalError(error);$('billing-button').disabled=false;}
  };
  $('export-account').onclick=async()=>{try{const data=await api('/v1/me/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='lp-optimizer-account.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){modalError(error);}};
  $('delete-account').onclick=()=>{
    modal('<h2>Delete your account?</h2><p>Your saved searches, connections, and agent keys will be removed. Any active membership will be cancelled immediately. Billing records may remain with the payment provider.</p><form id="delete-form"><label>Type “delete my account” to confirm<input id="delete-confirm" required autocomplete="off"></label><button class="button danger full" id="delete-confirm-button">Delete my account</button></form>','DELETE ACCOUNT');
    $('delete-form').onsubmit=async event=>{event.preventDefault();$('delete-confirm-button').disabled=true;try{await api('/v1/me',{method:'DELETE',body:{confirmation:$('delete-confirm').value}});state.me=null;state.result=null;clearTimeout(state.poll);window.postMessage({source:'lp-optimizer',type:'DISCONNECT'},location.origin);$('dialog').close();await loadMe();await runSearch(true);toast('Your account has been deleted.');}catch(error){modalError(error);$('delete-confirm-button').disabled=false;}};
  };
  $('account-agents').onclick=agents;
  $('logout-button').onclick=async()=>{await api('/v1/auth/logout',{method:'POST',body:{}});state.me=null;state.result=null;clearTimeout(state.poll);$('dialog').close();await loadMe();await runSearch(true);toast('Signed out.');};
  if($('disconnect-button'))$('disconnect-button').onclick=async()=>{await api('/v1/connections/'+user.connection.id,{method:'DELETE',body:{}});window.postMessage({source:'lp-optimizer',type:'DISCONNECT'},location.origin);await loadMe();$('dialog').close();toast('AA Hotels disconnected.');};
}
$('account-button').onclick=()=>account().catch(modalError);

function pricing(exhausted=false) {
  const config=state.config;
  modal(`<h2>${exhausted?'Keep comparing your options.':'A pass for a trip. A plan for more.'}</h2><p>${exhausted?'You’ve used your included searches. Your saved results are still yours.':`${number(config.free_searches)} free searches. No card required. Both options include trip planning, status searches, and agent access.`}</p><div class="price-option"><div><h3>Trip pass</h3><strong>${esc(config.trip_pass_price_label)} <small>once</small></strong></div><p>${number(config.trip_pass_searches)} extra searches. No expiry. No subscription.</p><button id="buy-pass" class="button primary full" ${config.billing_enabled?'':'disabled'}>Get a trip pass →</button></div><div class="price-option"><div><h3>Monthly membership</h3><strong>${esc(config.plan_price_label)}</strong></div><p>${number(config.paid_searches_per_month)} searches per calendar month. Renews monthly until you cancel. Cancel in My account.</p><button id="buy-membership" class="button outline full" ${config.billing_enabled?'':'disabled'}>${state.me?.billing_action==='portal'?'Manage membership':'Start membership →'}</button></div><p class="dialog-note">${config.billing_enabled?(config.billing_test_mode?'Test checkout — no real charges.':'Secure checkout with Stripe. Prices in USD.'):'Checkout is being set up. You can explore the example now.'} Failed provider searches return your allowance. Monthly searches reset on the first of each month (UTC); trip-pass searches carry over.</p>`,'PASSES & MEMBERSHIP');
  $('buy-pass').onclick=()=>startCheckout('trip_pass','buy-pass');
  $('buy-membership').onclick=()=>startCheckout('membership','buy-membership');
  if(preview()){
    $('dialog-eyebrow').textContent='PLANNED PRICING';
    $('dialog-content').querySelector('p').textContent='This preview is free. At launch: 2 free searches, then a trip pass or monthly membership. Prices in USD.';
    $('dialog-content').querySelector('.dialog-note').textContent='Purchases are unavailable in this preview. Email accounts and payments are still being connected; the companion is awaiting Chrome Web Store publication.';
  }
}
async function startCheckout(product,buttonId) {
  if(!state.me)return signIn('Sign in to save your purchase to your account.');
  const button=$(buttonId);button.disabled=true;
  try {
    saveDraft();
    const portal=product==='membership'&&state.me.billing_action==='portal';
    const result=await api('/v1/billing/'+(portal?'portal':'checkout'),{method:'POST',body:portal?{}:{product}});
    const url=new URL(result.url);
    if(url.protocol!=='https:'||!['checkout.stripe.com','billing.stripe.com'].includes(url.hostname))throw new Error('Unable to open checkout. Please try again.');
    location.assign(url.href);
  } catch(error){modalError(error);button.disabled=false;}
}
$('pricing-button').onclick=()=>pricing();
function saveDraft(){
  try{sessionStorage.setItem('lp-checkout-draft',JSON.stringify({at:Date.now(),request:formRequest()}));}catch{/* Search still works when browser storage is unavailable. */}
}
function restoreDraft(){
  try{
    const draft=JSON.parse(sessionStorage.getItem('lp-checkout-draft')||'null');
    if(!draft||Date.now()-draft.at>86400000)return;
    const r=draft.request;setMode(r.mode);
    $('city').value=r.cities[0];$('cities').value=r.cities.join('\n');
    for(const [id,value] of Object.entries({'check-in':r.check_in,'check-out':r.check_out,budget:r.budget_cents?r.budget_cents/100:'',objective:r.objective,adults:r.adults,rooms:r.rooms,'hotel-changes':r.max_hotel_changes,'max-bookings':r.max_bookings,'max-overlaps':r.max_overlaps,'current-lp':r.starting_lp,'target-lp':r.target_lp,'min-stars':r.min_stars,'card-miles':r.policy.card_miles_per_dollar,'partner-bonus':r.policy.partner_bonus_percent,'bonus-start':r.policy.bonus_start||'','bonus-end':r.policy.bonus_end||'','bonus-remaining':r.policy.bonus_remaining||0}))$(id).value=value;
    $('split').checked=r.split_bookings;$('refundable').checked=r.refundable_only;$('card-lp').checked=Boolean(r.policy.card_lp_per_dollar);$('partner-bonus').onchange();
    sessionStorage.removeItem('lp-checkout-draft');
  }catch{/* Ignore an obsolete draft. */}
}
async function agents() {
  if(preview()){modal('<h2>Plans your agent can read.</h2><p>Download any booking plan as JSON. Hosted search endpoints and scoped agent keys are part of the upcoming service.</p><p class="dialog-note">Agent API access is not available at this Streamlit address.</p>','FOR AGENTS');return;}
  if(!state.me)return signIn('Create a scoped key so your agent can search, check progress, and read saved booking plans.');
  const keys=await api('/v1/keys');
  modal(`<h2>Let your agent do the comparing.</h2><p>Keys can create searches and read your plans. Your connected browser supplies your personal offers.</p><a class="button outline" href="/static/agents.html" target="_blank" rel="noopener">Read the API guide ↗</a><form id="key-form"><label>Key name<input id="key-name" required value="My travel agent" maxlength="80"></label><label>Access<select id="key-scope"><option value="write">Create searches and read results</option><option value="read">Read results only</option></select></label><button class="button primary full">Create a key</button></form><div id="new-key"></div><div id="key-list">${keys.map(k=>`<div class="key-row"><div><strong>${esc(k.label)}</strong><p>Expires ${esc(day(k.expires_at.slice(0,10)))}</p></div><button class="text-button" data-revoke="${esc(k.id)}">Revoke</button></div>`).join('')}</div><p class="dialog-note">Keys expire after 90 days. They cannot change billing, manage connections, or make hotel reservations.</p>`,'FOR AGENTS');
  $('key-form').onsubmit=async event=>{event.preventDefault();try{const result=await api('/v1/keys',{method:'POST',body:{label:$('key-name').value,scopes:$('key-scope').value==='read'?['search:read']:['search:read','search:write']}});$('key-form').hidden=true;$('new-key').innerHTML=`<p class="dialog-note">Copy this key now. We won't show it again.</p><pre class="key-output">${esc(result.key)}</pre><button id="copy-key" class="button outline full">Copy key</button>`;$('copy-key').onclick=()=>copy(result.key,'Key copied.');}catch(error){modalError(error);}};
  root.querySelectorAll('[data-revoke]').forEach(button=>button.onclick=async()=>{await api('/v1/keys/'+button.dataset.revoke,{method:'DELETE',body:{}});button.closest('.key-row').remove();toast('Key revoked.');});
}
$('agents-button').onclick=()=>agents().catch(modalError);
async function history() {
  if(!state.me)return signIn('Your saved searches will be waiting here when you sign in.');
  const searches=await api('/v1/searches');
  modal(`<h2>Your saved searches</h2>${searches.length?'':'<p>Compare your next stay and the results will appear here. Examples are not saved.</p>'}${searches.map(s=>`<div class="history-row"><button class="text-button" data-search="${esc(s.id)}"><strong>${esc(s.request.cities.join(' · '))}</strong><p>${esc(day(s.request.check_in))} – ${esc(day(s.request.check_out))} · ${esc(s.status.replaceAll('_',' '))}</p></button><span aria-hidden="true">↗</span></div>`).join('')}`,'SAVED SEARCHES');
  if(preview()){
    $('dialog-content').querySelector('h2').textContent='Searches in this session';
    $('dialog-eyebrow').textContent='SESSION SEARCHES';
    const note=document.createElement('p');note.className='dialog-note';note.textContent='Keeps your last 10 searches while this session is open. Download a plan to keep it after reloading or closing this tab.';$('dialog-content').append(note);
  }
  root.querySelectorAll('[data-search]').forEach(button=>button.onclick=async()=>{try{const result=await api('/v1/searches/'+button.dataset.search);$('dialog').close();showResult(result);schedulePoll(result);$('results').scrollIntoView({behavior:'smooth',block:'start'});}catch(error){modalError(error);}});
}
$('history-button').onclick=()=>history().catch(modalError);

function emptyResult(title,message,actions='') { $('results').innerHTML=`<div class="result-placeholder"><span class="eyebrow">YOUR BOOKING PLAN</span><h2>${esc(title)}</h2><p>${esc(message)}</p>${actions}</div>`; }
const errors={location_ambiguous:'The city name matched more than one location. Add its state or country and try again.',location_not_found:'We couldn’t find that city. Check the spelling or try a nearby city.',provider_limit:'This search reached its request limit. Try fewer dates or cities.',provider_unavailable:'AA Hotels could not return offers. Open its tab and try again.',provider_schema_changed:'AA Hotels returned a response we couldn’t read. The connection needs an update.',pagination_limit:'We couldn’t verify all result pages. Try narrowing the search.',provider_search_pending:'AA Hotels is taking longer than expected. Please try again.',search_too_complex:'There are too many combinations to compare. Try fewer nights, one hotel, or a lower budget.',search_expired:'This search expired. Start a fresh search for current offers.',connection_replaced:'The browser connection changed. Start a fresh search.',connection_removed:'AA Hotels was disconnected. Connect again to start a fresh search.'};
function showResult(result, selected=0) {
  state.result=result;
  if(['queued','running','browser_required','reauth_required','pairing'].includes(result.status)){
    const needsBrowser=!['queued','running'].includes(result.status);
    emptyResult(needsBrowser?'Your browser is needed.':'Comparing your dates…',needsBrowser?'Open AA Hotels and sign in. The comparison continues while that tab is available.':'We’re comparing whole stays and separate reservations using your personal offers.',`${needsBrowser?'<button id="resume-connection" class="button primary">Check AA Hotels connection</button>':'<div class="progress"><span></span></div>'}<p class="progress-label">${number(result.progress?.done||0)} of ${number(result.progress?.total||0)} comparisons complete</p><button id="cancel-search" class="button quiet">Cancel search</button>`);
    if($('resume-connection'))$('resume-connection').onclick=connectionModal;
    $('cancel-search').onclick=async()=>{const cancelled=await api('/v1/searches/'+result.id+'/cancel',{method:'POST',body:{}});clearTimeout(state.poll);showResult(cancelled);};return;
  }
  if(result.status==='cancelled'){emptyResult('Search cancelled.','Change your dates or preferences and compare again.');return;}
  if(result.status==='failed'){emptyResult('Let’s adjust this search.',result.error_message||errors[result.error_code]||'We couldn’t complete the comparison. Please try again.');return;}
  if(!result.plans?.length){emptyResult('No complete plan found.','Try increasing your budget, relaxing your filters, or allowing a hotel change.');return;}
  const plan=result.plans[selected], req=result.request, sample=Boolean(result.sample);
  const sameHotel=new Set(plan.offers.map(q=>q.property_id)).size===1;
  const title=plan.offers.length?(sameHotel?plan.offers[0].name:`${new Set(plan.offers.map(q=>q.property_id)).size} hotels, one plan`):'You’ve already reached your goal';
  const baseline=result.baseline;
  const uplift=baseline && plan.hotel_changes===0 && baseline.offers[0]?.property_id===plan.offers[0]?.property_id?plan.earned_lp-baseline.earned_lp:null;
  const observations=plan.offers.map(q=>Date.parse(q.observed_at));
  const stale=!sample && observations.some(t=>Date.now()-t>15*60*1000);
  const options=result.plans.map((p,i)=>({p,i})).filter(x=>x.i!==selected).slice(0,3);
  $('results').innerHTML=`<div class="result-heading"><h2>${req.mode==='trip'?'Your stay, optimized':'Your status plan'}</h2><span class="tag ${sample?'sample':''}">${sample?'EXAMPLE · FICTIONAL QUOTES':stale?'SAVED QUOTES · REFRESH BEFORE BOOKING':'LIVE QUOTE COMPARISON'}</span></div>
    <article class="result-card"><div class="result-top"><div><span class="recommendation">${req.objective==='cost'?'LOWEST COST FOUND':req.objective==='points'?'MOST LP FOUND':req.objective==='fastest'?'EARLIEST FINISH FOUND':'BEST VALUE FOUND'}</span><h2>${esc(title)}</h2><p>${esc(req.cities.join(' · '))} &nbsp;·&nbsp; ${esc(day(req.check_in))} – ${esc(day(req.check_out))}</p></div><div class="rate-badge"><strong>${number(plan.lp_per_dollar)}</strong><span>LP per dollar</span></div></div>
    <div class="metrics"><dl class="metric"><dt>Estimated Loyalty Points</dt><dd>${number(plan.earned_lp)} <small>LP</small></dd></dl><dl class="metric"><dt>Total stay cost</dt><dd>${money(plan.cost_cents)}</dd></dl><dl class="metric"><dt>Reservations</dt><dd>${plan.booking_count} <small>${plan.hotel_changes===0?'one hotel':`${plan.hotel_changes} changes`}</small></dd></dl></div>
    <div class="itinerary"><div class="itinerary-title"><strong>${plan.booking_count>1?'Your separate reservations':'Your reservation'}</strong><span>${req.mode==='trip'?'Every night covered':plan.target_met?'Estimated goal reached':`${number(plan.shortfall_lp)} LP still needed`}</span></div><div class="night-strip">${plan.offers.map(q=>`<div class="night"><time datetime="${esc(q.check_in)}">${esc(day(q.check_in))}</time><strong>${number(q.base_lp)}</strong><small>hotel LP · ${Math.round((new Date(q.check_out)-new Date(q.check_in))/86400000)} night${new Date(q.check_out)-new Date(q.check_in)>86400000?'s':''}</small></div>`).join('')}</div><p class="split-note">${plan.booking_count>1?'Each segment is a separate booking. Confirm check-in and room arrangements with the hotel.':'One continuous reservation for these dates.'}</p></div>
    ${uplift>0?`<div class="comparison"><p>Compared with one continuous reservation at this hotel</p><strong>+${number(uplift)} LP${plan.cost_cents===baseline.cost_cents?' · same cost':` · ${money(Math.abs(plan.cost_cents-baseline.cost_cents))} ${plan.cost_cents>baseline.cost_cents?'more':'less'}`}</strong></div>`:req.mode==='status'?`<div class="comparison"><p>Projected balance after these stays</p><strong>${number(plan.projected_lp)} / ${number(req.target_lp)} LP</strong></div>`:''}
    <div class="booking-list"><h3>Your booking checklist</h3>${plan.offers.map((q,i)=>`<div class="booking-row"><span class="booking-number">${String(i+1).padStart(2,'0')}</span><div><h3>${esc(q.name)}</h3><p>${esc(day(q.check_in))} – ${esc(day(q.check_out))} · ${q.refundable===true?'Refundable':q.refundable===false?'Non-refundable':'Check cancellation terms'}</p></div><div class="booking-price">${money(q.price_cents)}<small>${number(q.base_lp)} hotel LP</small></div></div>`).join('')}</div>
    <div class="result-actions"><button id="copy-plan" class="button outline">Copy booking plan</button><button id="download-plan" class="button quiet">Download JSON</button>${sample?'<button id="personal-rates" class="button primary">Compare my offers →</button>':'<a class="button primary" href="https://www.aadvantagehotels.com" target="_blank" rel="noopener noreferrer">Open AA Hotels ↗</a>'}</div></article>
    <details class="details-note"><summary>LP breakdown, assumptions &amp; booking notes</summary><dl class="breakdown"><dt>Hotel LP estimate</dt><dd>${number(plan.hotel_lp)}</dd><dt>Credit card LP</dt><dd>${number(plan.card_lp)}</dd><dt>Registered partner bonus LP</dt><dd>${number(plan.partner_bonus_lp)}</dd><dt>Redeemable miles estimate</dt><dd>${number(plan.miles)}</dd></dl><ul>${result.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}<li>Partner LP bonuses do not add redeemable miles. Prices and availability can change before booking.</li></ul></details>
    ${options.length?`<div class="alternative-list"><h3>Other combinations worth a look</h3>${options.map(({p,i})=>`<button class="alternative" data-plan="${i}"><span><strong>${esc(p.offers[0]?.name||'Status reached')}</strong><small>${p.booking_count} reservation${p.booking_count===1?'':'s'} · ${number(p.lp_per_dollar)} LP/$</small></span><span><strong>${number(p.earned_lp)} LP</strong><small>${money(p.cost_cents)} total</small></span><span aria-hidden="true">→</span></button>`).join('')}</div>`:''}`;
  $('copy-plan').onclick=()=>copy(planText(plan,result),'Booking plan copied.');
  $('download-plan').onclick=()=>{const blob=new Blob([JSON.stringify({sample,request:req,plan,warnings:result.warnings},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`lp-plan-${req.check_in}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  if($('personal-rates'))$('personal-rates').onclick=()=>state.me?connectionModal():signIn();
  root.querySelectorAll('[data-plan]').forEach(button=>button.onclick=()=>showResult(result,Number(button.dataset.plan)));
}
function planText(plan,result){return `${result.sample?'EXAMPLE — fictional quotes\n':''}LP Optimizer booking plan\n${number(plan.earned_lp)} estimated LP · ${money(plan.cost_cents)} total · ${plan.lp_per_dollar} LP/$\n\n${plan.offers.map((q,i)=>`${i+1}. ${q.name}, ${q.city}\n   ${q.check_in} to ${q.check_out} · ${money(q.price_cents)} · ${number(q.base_lp)} hotel LP`).join('\n')}\n\nConfirm final prices, eligible rewards, and reservation terms on AA Hotels. No bookings have been made.`;}
async function copy(value,message){try{await navigator.clipboard.writeText(value);toast(message);}catch{toast('Clipboard access is unavailable. Use Download JSON to save this plan.');}}
function schedulePoll(result){clearTimeout(state.poll);if(['queued','running','browser_required','reauth_required','pairing'].includes(result.status))state.poll=setTimeout(async()=>{try{const fresh=await api('/v1/searches/'+result.id);showResult(fresh);schedulePoll(fresh);workPreview();}catch(error){notice(error.message);}},3000);}
async function runSearch(sample=false) {
  if(state.busy)return;
  $('form-error').hidden=true;
  if(!sample&&!state.me)return signIn();
  if(!sample&&!preview()&&state.me?.usage.remaining===0)return pricing(true);
  if(!sample&&!state.config.provider_enabled){notice('Live offers are not enabled in this local preview. You can explore the example and account flows.');return;}
  if(!sample&&state.me?.connection.state!=='connected')return connectionModal();
  state.busy=true;$('results').setAttribute('aria-busy','true');$('search-button').disabled=$('demo-button').disabled=true;
  try{const body=formRequest();const result=await api(sample?'/v1/demo':'/v1/searches',{method:'POST',body,headers:sample?{}:{'Idempotency-Key':crypto.randomUUID()}});clearTimeout(state.poll);showResult(result);schedulePoll(result);if(!sample){await loadMe();workPreview();window.postMessage({source:'lp-optimizer',type:'PING'},location.origin);}}
  catch(error){$('form-error').textContent=error.message;$('form-error').hidden=false;if(error.code==='search_limit'){await loadMe();pricing(true);}}
  finally{state.busy=false;$('results').setAttribute('aria-busy','false');$('search-button').disabled=$('demo-button').disabled=false;}
}
$('search-form').onsubmit=event=>{event.preventDefault();runSearch(false);};
$('demo-button').onclick=()=>{if($('search-form').reportValidity())runSearch(true);};
$('about-button').onclick=()=>modal('<h2>Know what goes into the estimate.</h2><p>We compare the quoted price and rewards for each date combination, then assemble plans that respect your budget, hotel changes, and booking limit.</p><p>Hotel LP, credit card LP, registered partner bonus LP, and redeemable miles are tracked separately. Bonuses are included only when you enter an active promotion and its remaining allowance.</p><p>Lowest-cost status searches use exact selection among the quotes found when stays do not overlap. Other status strategies rank offers and may not find the absolute lowest cost. All results depend on the inventory and prices returned during your search.</p><p>Separate reservations may require another check-in or a room change. No-show stays may be cancelled or earn no rewards. Always check the final price, eligible LP, and booking conditions on AA Hotels.</p><a class="button outline" href="https://www.aa.com/web/i18n/aadvantage-program/aadvantage-status/loyalty-point-rewards.html" target="_blank" rel="noopener noreferrer">AA Loyalty Point Rewards terms ↗</a>','HOW ESTIMATES WORK');
$('privacy-button').onclick=()=>modal('<h2>Your account stays yours.</h2><p>The app stores your email address, saved search details, normalized hotel quotes, and billing status. Stripe handles payment details; the app does not store card numbers.</p><p>The browser companion uses your existing AA Hotels tab. It sends hotel quotes and connection status, not your AA cookies or password. We keep a one-way account fingerprint to detect account changes and your first name to label the connection.</p><p>Application sign-in links, sessions, and agent keys are stored as hashes. You can revoke agent keys, disconnect the browser, and sign out in My account.</p><p class="dialog-note">This is a local product preview. Production privacy, retention, refund, and support policies must be finalized before the public paid launch.</p>','DATA & PRIVACY');

async function consumeLoginFragment(){
  if(location.hash.startsWith('#login=')){
    const raw=location.hash.slice(7);
    window.history.replaceState(null,'',location.pathname+location.search);
    await consumeLogin(raw);
  }
}
window.addEventListener('hashchange',consumeLoginFragment,{signal:listeners.signal});

async function initialize(){
  const start=new Date();start.setDate(start.getDate()+28);const end=new Date(start);end.setDate(end.getDate()+4);
  $('check-in').value=iso(start);$('check-out').value=iso(end);$('check-in').min=$('check-out').min=iso(new Date());
  try{state.config=await api('/v1/config');await loadMe();
    await consumeLoginFragment();
    restoreDraft();
    $('trial-note').textContent=preview()?'Free preview · no account or payment required':`${number(state.config.free_searches)} free searches. No card required.`;
    if(preview()){
      restorePreview();
      $('history-button').textContent='Session searches';
      notice('Free preview · Connect the Chrome companion for your personal AA Hotels offers. Email accounts and payments are coming next.');
      const guide=root.querySelector('a[href="/static/agents.html"]');
      guide.href='/?view=classic';guide.textContent='Original app ↗';guide.target='_top';
      root.querySelector('.brand').href='/';root.querySelector('.brand').target='_top';
      $('privacy-button').onclick=()=>modal('<h2>Your AA login stays in your browser.</h2><p>The companion performs read-only hotel searches in your AA Hotels tab. It returns normalized hotel offers, your first name, and a one-way account fingerprint. Passwords, cookies, and AA login tokens are never sent to this planner.</p><p>Searches stay in this preview session’s memory. Download a plan before reloading or closing the tab. Disconnecting stops further comparisons. This preview does not create an email account or accept payments.</p>','DATA & PRIVACY');
    }
    const params=new URLSearchParams(location.search);
    if(params.get('billing')==='success')notice('Checkout finished. Your searches unlock after payment is confirmed. Your search details are ready below.');
    if(params.get('billing')==='cancelled')notice('Checkout cancelled. Your search details are ready below.');
    await runSearch(true);window.postMessage({source:'lp-optimizer',type:'PING'},location.origin);
    if(params.has('connect'))connectionModal();
    accountTimer=setInterval(()=>{if(state.me)loadMe().catch(()=>{});},20000);
  }catch(error){emptyResult('We couldn’t load the app.',error.message);}
}
initialize();
return ()=>{listeners.abort();clearTimeout(toastTimer);clearTimeout(state.poll);clearInterval(accountTimer);};
}

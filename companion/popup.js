const labels={connected:'Connected to AA Hotels',reauth_required:'Sign in to AA Hotels again',browser_required:'Open your AA Hotels tab',not_connected:'Connect from the app'};
async function refresh(){const {connectionState}=await chrome.storage.local.get('connectionState');document.getElementById('state').textContent=labels[connectionState]||labels.not_connected;}
document.getElementById('open').onclick=()=>chrome.tabs.create({url:globalThis.LP_APP_ORIGIN});
document.getElementById('check').onclick=async()=>{await chrome.runtime.sendMessage({type:'WAKE',force:true});document.getElementById('state').textContent='Checking…';setTimeout(refresh,1500);};
refresh();

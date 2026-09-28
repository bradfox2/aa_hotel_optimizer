/* Runs in the user's AA Hotels tab. No credentials leave this function.
   Keep this self-contained: Chrome serializes it for MAIN-world execution. */
export async function providerRequest(task) {
  if (location.origin !== 'https://www.aadvantagehotels.com') return {status:'browser_required'};
  const base='/rest/aadvantage-hotels';
  const timeout=AbortSignal.timeout(22000);
  async function get(path,params={}) {
    const url=new URL(base+path,location.origin);
    for(const [key,value] of Object.entries(params))url.searchParams.set(key,String(value));
    const response=await fetch(url.href,{method:'GET',credentials:'include',redirect:'error',headers:{Accept:'application/json'},signal:timeout});
    if([401,403].includes(response.status))throw new Error('reauth_required');
    if(response.status===429)throw new Error('rate_limited');
    if(!response.ok)throw new Error('provider_error');
    if(response.status===204)return null;
    const content=response.headers.get('content-type')||'';
    if(!content.includes('json'))throw new Error('reauth_required');
    const text=await response.text();
    if(text.length>5_000_000)throw new Error('provider_error');
    return JSON.parse(text);
  }
  const safeString=(value,max=200)=>typeof value==='string'?value.slice(0,max):'';
  const dateFormat=value=>{if(!/^\d{4}-\d{2}-\d{2}$/.test(value))throw new Error('provider_error');const [y,m,d]=value.split('-');return `${m}/${d}/${y}`;};
  try {
    const session=await get('/session');
    // This UUID is hashed in the provider's tab. Member number, email, cookies,
    // session storage, raw headers and the raw session object are never returned.
    if(!session || typeof session.uuid!=='string')return {status:'reauth_required'};
    const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode('lp-optimizer:'+session.uuid));
    const account_fingerprint=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');
    const account={account_fingerprint,account_label:safeString(session.firstName,60)};
    if(task.account_fingerprint && task.account_fingerprint!==account_fingerprint)return {status:'account_changed'};
    if(task.kind==='session')return {status:'ok',...account,data:{}};
    const p=task.payload||{};
    let data;
    if(task.kind==='places') {
      const response=await get('/places',{query:safeString(p.city,100),source:'AGODA',language:'en',includeHotelNames:'false'});
      if(!Array.isArray(response))throw new Error('provider_error');
      data={places:response.slice(0,50).map(place=>({id:safeString(place.id,150),name:safeString(place.name),type:safeString(place.type,40)}))};
    } else if(task.kind==='start') {
      const response=await get('/searchRequest',{adults:Math.max(1,Math.min(8,Number(p.adults)||1)),
        checkIn:dateFormat(p.check_in),checkOut:dateFormat(p.check_out),children:0,currency:'USD',language:'en',
        locationType:'CITY',mode:'earn',numberOfChildren:0,placeId:safeString(p.place_id,150),program:'aadvantage',
        promotion:'',query:safeString(p.city,100),rooms:Math.max(1,Math.min(4,Number(p.rooms)||1)),source:'AGODA'});
      data={uuid:safeString(response?.uuid,150)};
    } else if(task.kind==='results') {
      if(typeof p.uuid!=='string'||! /^[a-zA-Z0-9_-]{1,150}$/.test(p.uuid))throw new Error('provider_error');
      const response=await get('/search/'+p.uuid,{hotelImageHeight:368,hotelImageWidth:704,pageSize:45,pageNumber:Math.max(1,Math.min(20,Number(p.page)||1))});
      if(!Array.isArray(response?.results))throw new Error('provider_error');
      data={results:response.results.slice(0,100).map(row=>({
        id:safeString(String(row.id||row.rateId||''),150),
        hotel:{id:safeString(String(row.hotel?.id||row.hotel?.hotelId||row.hotelId||''),150),
          name:safeString(row.hotel?.name),stars:row.hotel?.stars,rating:row.hotel?.rating},
        rewards:typeof row.rewards==='number'?row.rewards:null,
        grandTotalPublishedPriceInclusiveWithFees:{amount:row.grandTotalPublishedPriceInclusiveWithFees?.amount,
          currency:safeString(row.grandTotalPublishedPriceInclusiveWithFees?.currency||'USD',3)},
        refundability:safeString(row.refundability,40),description:safeString(row.description,300)
      })), ...(typeof response.complete==='boolean'?{complete:response.complete}:{})};
    } else throw new Error('provider_error');
    return {status:'ok',...account,data};
  } catch(error) {
    return {status:['reauth_required','rate_limited'].includes(error.message)?error.message:'provider_error'};
  }
}

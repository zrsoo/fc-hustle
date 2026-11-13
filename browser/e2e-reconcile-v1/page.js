/* Four explicit read-only commands. Native IDs remain only inside this page. */
(()=>{'use strict';if(window.__fcReconV1)return;
const KEY='06'.repeat(16),TRADE='trade:83105610f7508574b2e36139',ITEM='item:178f6a3fd2bc1c19690e3ffe';
const SOURCE='6097c4fd909171eb067c77ad088c8fd8bd18024f5848663774f5488becf11c2a';
const hash=async s=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))].map(v=>v.toString(16).padStart(2,'0')).join('');
const id=async(v,ns)=>{if(!(typeof v==='string'&&/^\d{1,24}$/.test(v))&&!(Number.isSafeInteger(v)&&v>=0))return null;return ns+':'+(await hash(KEY+'|'+ns+'|'+v)).slice(0,24);};
const num=v=>Number.isSafeInteger(v)&&v>=0?v:null,documentFence=crypto.randomUUID(),sent=new Set();
let fence=null,busy=false,rawTrade=null,sourceMatch=false;
async function attach(h){if(busy)return null;fence={boot:h.boot,owner:h.owner};
 const fn=services.Item?.transfersDao?.getAuctionData;sourceMatch=typeof fn==='function'&&await hash(Function.prototype.toString.call(fn))===SOURCE;
 const matches=new Set();
 for(const e of performance.getEntriesByType('resource')){try{const u=new URL(e.name);if(u.protocol!=='https:'||!/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname))continue;const m=u.pathname.match(/^\/ut\/game\/fc27\/trade\/(\d{1,24})\/bid$/);if(m&&await id(m[1],'trade')===TRADE)matches.add(m[1]);}catch{}}
 rawTrade=matches.size===1?[...matches][0]:null;
 return {document:documentFence,persona:window.__fcDiscoveryPersonaFollowupV1.inspect(),source_match:sourceMatch,original_trade_resource_match:rawTrade!==null};}
function observe(o){return new Promise((resolve,reject)=>{let done=false;const owner={},t=setTimeout(()=>{if(!done){done=true;o.unobserve?.(owner);reject(Error('service_timeout'));}},15000);o.observe(owner,(s,r)=>{if(!done){done=true;clearTimeout(t);s?.unobserve?.(owner);resolve(r);}});});}
async function project(a,i){return {trade_id:await id(a.tradeId,'trade'),item_id:await id(i.id,'item'),definition_id:num(i.definitionId??i.resourceId),current_bid:num(a.currentBid),starting_bid:num(a.startingBid),buy_now_price:num(a.buyNowPrice),expires:a.expires===-1?-1:num(a.expires),trade_state:['active','closed','expired','inactive'].includes(a.tradeState)?a.tradeState:null,bid_state:['none','highest','outbid','sold','buyNow'].includes(a.bidState)?a.bidState:null,untradeable:typeof i.tradable==='boolean'?!i.tradable:typeof i.untradeable==='boolean'?i.untradeable:null,last_sale_price:num(i.lastSalePrice)};}
async function execute(c){const out={schema:1,command_id:c?.id??null,operation:c?.operation??null,observed_at:new Date().toISOString(),success:false,error:'invalid_command',status:null,persona:null,network:[],rows:null,wire_rows:null,credits:null,caps:null,tiers:null,cache_invalidated:false,duration_ms:0};
if(!fence||busy||c.boot!==fence.boot||c.owner!==fence.owner||sent.has(c.id)||!['status','watched','unassigned','balance'].includes(c.operation)||Object.keys(c.params).length)return out;
if(location.protocol!=='https:'||!/^(www\.)?ea\.com$/.test(location.hostname)||!/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname))return out;
busy=true;sent.add(c.id);const began=performance.now(),jobs=[];let restore=()=>{};
try{out.persona=window.__fcDiscoveryPersonaFollowupV1.inspect();if(!out.persona.accepted)throw Error('persona_unverified');
 let invoke;const op=c.operation;
 if(op==='status'){
  if(!sourceMatch||!rawTrade)throw Error('exact_trade_or_source_unavailable');
  // Transport descriptor for a proven historical trade, not an observed status.
  // The reviewed DAO reads only tradeId/isValid and sets local isUpdating.
  const query={tradeId:rawTrade,isValid:()=>true,isUpdating:false};
  invoke=()=>services.Item.transfersDao.getAuctionData([{getAuctionData:()=>query}]);
 }else if(op==='watched'){repositories.Item.setDirty(ItemPile.INBOX);out.cache_invalidated=true;invoke=()=>services.Item.requestWatchedItems();}
 else if(op==='unassigned'){repositories.Item.setDirty(ItemPile.PURCHASED);out.cache_invalidated=true;invoke=()=>services.Item.requestUnassignedItems();}
 else invoke=()=>services.User.requestCurrencies();
 const proto=XMLHttpRequest.prototype,orig={open:proto.open,header:proto.setRequestHeader,send:proto.send},pending=new WeakMap();
 const open=function(method,url,...args){let m=null;try{const u=new URL(url,location.href);if(method==='GET'&&u.protocol==='https:'&&/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname)&&['/ut/game/fc27/trade/status/lite','/ut/game/fc27/watchlist','/ut/game/fc27/purchased/items','/ut/game/fc27/user/credits'].includes(u.pathname))m={method:'GET',route:u.pathname,query:{},session_header_present:false,status:null,started_at:null,ended_at:null,duration_ms:null,payload_bytes:null};}catch{}pending.set(this,m);return orig.open.call(this,method,url,...args);};
 const header=function(n,v){const m=pending.get(this);if(m&&String(n).toLowerCase()==='x-ut-sid')m.session_header_present=true;return orig.header.call(this,n,v);};
 const send=function(...args){const m=pending.get(this);if(m){m.started_at=new Date().toISOString();const t=performance.now();out.network.push(m);this.addEventListener('loadend',()=>{m.status=num(this.status);m.ended_at=new Date().toISOString();m.duration_ms=performance.now()-t;try{m.payload_bytes=new TextEncoder().encode(this.responseText).length;const data=JSON.parse(this.responseText);if(Array.isArray(data.auctionInfo)&&data.auctionInfo.length<=100)jobs.push(Promise.all(data.auctionInfo.map(a=>project(a,a.itemData??{}))).then(rows=>out.wire_rows=rows));}catch{}},{once:true});}return orig.send.apply(this,args);};
 proto.open=open;proto.setRequestHeader=header;proto.send=send;restore=()=>{if(proto.open===open)proto.open=orig.open;if(proto.setRequestHeader===header)proto.setRequestHeader=orig.header;if(proto.send===send)proto.send=orig.send;};
 const response=await observe(invoke());await new Promise(r=>setTimeout(r,0));await Promise.all(jobs);out.status=num(response?.status);if(response?.success!==true)throw Error('service_failed');
 const data=response.data??response.response;
 if(op==='balance'){const user=services.User.getUser?.();out.credits=num(data?.credits??user?.coins?.amount);if(out.credits===null)throw Error('schema_unrecognized');}
 else{const rows=data?.items;if(!Array.isArray(rows)||rows.length>100)throw Error('schema_unrecognized');out.rows=await Promise.all(rows.map(raw=>project(raw.getAuctionData?.()??raw,raw.itemData??raw)));}
 out.success=true;out.error=null;
}catch(e){out.error=['persona_unverified','exact_trade_or_source_unavailable','service_timeout','service_failed','schema_unrecognized'].includes(e?.message)?e.message:'internal_error';}
finally{restore();busy=false;out.observed_at=new Date().toISOString();out.duration_ms=performance.now()-began;}return out;}
Object.defineProperty(window,'__fcReconV1',{value:Object.freeze({attach,execute})});})();

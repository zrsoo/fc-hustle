/* Explicit bounded native commands only. Raw identifiers stay inside this page. */
(()=>{'use strict';if(window.__fcE2ELiveV2)return;
const num=v=>Number.isSafeInteger(v)&&v>=0?v:null,hex=v=>typeof v==='string'&&/^[a-f0-9]{32}$/.test(v);
const documentFence=crypto.randomUUID(),known=new Map(),sent=new Set();let fence=null,busy=false;
function attach(h){if(busy||!hex(h.owner)||!hex(h.boot))return null;if(fence&&fence.boot!==h.boot){known.clear();}fence={boot:h.boot,owner:h.owner};return {document:documentFence,persona:window.__fcDiscoveryPersonaFollowupV1.inspect()};}
async function id(v,ns,key){if(!(typeof v==='string'&&/^\d{1,24}$/.test(v))&&!(Number.isSafeInteger(v)&&v>=0))throw Error('unsafe_identity');return ns+':'+[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(key+'|'+ns+'|'+v)))].map(v=>v.toString(16).padStart(2,'0')).join('').slice(0,24);}
function observe(o){if(typeof o?.observe!=='function')throw Error('service_unavailable');return new Promise((resolve,reject)=>{const owner={};let done=false;const t=setTimeout(()=>{if(!done){done=true;o.unobserve?.(owner);reject(Error('service_timeout'));}},15000);o.observe(owner,(sender,r)=>{if(!done){done=true;clearTimeout(t);sender?.unobserve?.(owner);resolve(r);}});});}
async function project(a,i,key){return {trade_id:a.tradeId?await id(a.tradeId,'trade',key):null,item_id:await id(i.id,'item',key),definition_id:num(i.definitionId??i.resourceId),untradeable:typeof i.tradable==='boolean'?!i.tradable:typeof i.untradeable==='boolean'?i.untradeable:null,starting_bid:num(a.startingBid),current_bid:num(a.currentBid),buy_now_price:num(a.buyNowPrice),expires:a.expires===-1?-1:num(a.expires),trade_state:['active','expired','closed','inactive'].includes(a.tradeState)?a.tradeState:null,bid_state:['none','highest','outbid','buyNow','sold'].includes(a.bidState)?a.bidState:null,last_sale_price:num(i.lastSalePrice),native_is_won:typeof a.isWon==='function'?a.isWon():a.tradeState==='closed'&&a.bidState==='highest'};}
const operations=new Set(['search','caps','watched','balance','unassigned','transfer_list','bid','move','list']);
const routes={search:'/ut/game/fc27/transfermarket',caps:'/ut/game/fc27/marketdata/pricelimits',watched:'/ut/game/fc27/watchlist',balance:'/ut/game/fc27/user/credits',unassigned:'/ut/game/fc27/purchased/items',transfer_list:'/ut/game/fc27/tradepile',bid:'/ut/game/fc27/trade/:trade/bid',move:'/ut/game/fc27/item',list:'/ut/game/fc27/auctionhouse'};
async function execute(c){const start=performance.now(),out={schema:1,command_id:c?.id??null,operation:c?.operation??null,observed_at:new Date().toISOString(),success:false,error:'invalid_command',status:null,persona:null,network:[],rows:null,wire_rows:null,credits:null,caps:null,tiers:null,cache_invalidated:false,duration_ms:0};
if(!c||!hex(c.id)||!hex(c.evidence_key)||!fence||c.boot!==fence.boot||c.owner!==fence.owner||!operations.has(c.operation)||busy)return out;
if(location.protocol!=='https:'||!/^(www\.)?ea\.com$/.test(location.hostname)||!/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname))return out;
busy=true;let restore=()=>{};const jobs=[];
try{out.persona=window.__fcDiscoveryPersonaFollowupV1.inspect();if(!out.persona.accepted)throw Error('persona_unverified');
 const p=c.params,op=c.operation;let invoke;
 if(op==='search'){const q=new UTSearchCriteriaDTO();q.type='player';q.count=21;for(const [k,v]of Object.entries({max_bid:'maxBid',min_buy:'minBuy',max_buy:'maxBuy'}))if(p[k]!=null)q[v]=p[k];if(p.definition_id)q.defId=[p.definition_id];services.Item.clearTransferMarketCache();out.cache_invalidated=true;invoke=()=>services.Item.searchTransferMarket(q,p.page??1);}
 else if(op==='caps'){out.tiers=UTCurrencyInputControl.PRICE_TIERS.map(t=>({minimum:num(t.min),increment:num(t.inc)}));invoke=()=>services.Item.transfersDao.getItemMarketDataByDefId([p.definition_id]);}
 else if(op==='watched'){repositories.Item.setDirty(ItemPile.INBOX);out.cache_invalidated=true;invoke=()=>services.Item.requestWatchedItems();}
 else if(op==='balance')invoke=()=>services.User.requestCurrencies();
 else if(op==='unassigned'){repositories.Item.setDirty(ItemPile.PURCHASED);out.cache_invalidated=true;invoke=()=>services.Item.requestUnassignedItems();}
 else if(op==='transfer_list'){repositories.Item.setDirty(ItemPile.TRANSFER);out.cache_invalidated=true;invoke=()=>services.Item.requestTransferItems();}
 else {const e=known.get(p.item_id);if(!e||e.row.definition_id!==p.definition_id||Date.now()-e.at>30000||sent.has(c.id))throw Error('invalid_preconditions');
  if(op==='bid'){if(e.row.untradeable!==false)throw Error('invalid_preconditions');const a=e.row,minimum=a.current_bid===0?a.starting_bid:UTCurrencyInputControl.getIncrementAboveVal(a.current_bid);
   if(a.trade_id!==p.trade_id||e.source!=='search'&&e.source!=='watched'||a.trade_state!=='active'||a.bid_state==='highest'||a.expires<=0||Date.now()>=e.at+a.expires*1000||p.amount!==minimum||p.amount>p.cap||p.amount>=a.buy_now_price)throw Error('invalid_preconditions');
   invoke=()=>services.Item.bid(e.raw,p.amount);
  }else{if(op==='list'&&e.row.trade_state==='active')throw Error('invalid_preconditions');if((op==='move'?!((e.source==='watched'&&e.row.native_is_won===true)||e.source==='unassigned'):e.source!=='transfer_list')||e.row.untradeable!==false)throw Error('invalid_preconditions');
   invoke=op==='move'?()=>services.Item.move([e.raw],ItemPile.TRANSFER,false):()=>services.Item.list(e.raw,p.starting_bid,p.buy_now_price,3600);
  }sent.add(c.id);known.delete(p.item_id);
 }
 const proto=XMLHttpRequest.prototype,orig={open:proto.open,send:proto.send,header:proto.setRequestHeader},pending=new WeakMap();
 const open=function(method,url,...args){let m=null;try{const u=new URL(url,location.href);if(u.protocol==='https:'&&/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname)){
  const route=u.pathname.replace(/\/trade\/\d{1,24}\/bid$/,'/trade/:trade/bid');
  if(Object.values(routes).includes(route)){const query={};for(const k of ['start','num','macr','minb','maxb','definitionId','defId'])if(u.searchParams.has(k))query[k]=num(Number(u.searchParams.get(k)));m={method,route,query,bid_amount:null,session_header_present:false,status:null,started_at:null,ended_at:null,duration_ms:null,payload_bytes:null};}
 }}catch{}pending.set(this,m);return orig.open.call(this,method,url,...args);};
 const header=function(n,v){const m=pending.get(this);if(m&&String(n).toLowerCase()==='x-ut-sid')m.session_header_present=true;return orig.header.call(this,n,v);};
 const send=function(...args){const m=pending.get(this);if(m){if(m.method==='PUT'&&m.route==='/ut/game/fc27/trade/:trade/bid'){try{const body=JSON.parse(args[0]);if(Object.keys(body).join()==='bid')m.bid_amount=num(body.bid);}catch{}}const t=performance.now();m.started_at=new Date().toISOString();out.network.push(m);this.addEventListener('loadend',()=>{m.status=num(this.status);m.ended_at=new Date().toISOString();m.duration_ms=performance.now()-t;try{m.payload_bytes=new TextEncoder().encode(this.responseText).length;const v=JSON.parse(this.responseText);if(Array.isArray(v.auctionInfo)&&v.auctionInfo.length<=100)jobs.push(Promise.all(v.auctionInfo.map(a=>project(a,a.itemData,c.evidence_key))).then(rows=>out.wire_rows=rows));if(op==='caps'&&Array.isArray(v))out.caps=v.map(x=>({definition_id:num(x.defId),minimum:num(x.minPrice),maximum:num(x.maxPrice)}));}catch{}},{once:true});}return orig.send.apply(this,args);};
 proto.open=open;proto.send=send;proto.setRequestHeader=header;restore=()=>{if(proto.open===open)proto.open=orig.open;if(proto.send===send)proto.send=orig.send;if(proto.setRequestHeader===header)proto.setRequestHeader=orig.header;};
 const response=await observe(invoke());await new Promise(r=>setTimeout(r,0));await Promise.all(jobs);out.status=num(response?.status);if(response?.success!==true)throw Error('service_failed');
 const data=response.data??response.response;
 if(['search','watched','unassigned','transfer_list'].includes(op)){const rows=data?.items??data?.auctionInfo;if(!Array.isArray(rows)||rows.length>100)throw Error('schema_unrecognized');out.rows=await Promise.all(rows.map(async raw=>{const a=raw.getAuctionData?.()??raw.auctionData??raw._auction??raw,i=raw.itemData??raw,row=await project(a,i,c.evidence_key);known.set(row.item_id,{raw,row,at:Date.now(),source:op});return row;}));}
 if(op==='balance'){const user=services.User.getUser?.();out.credits=num(data?.credits??data?.currencies?.find?.(x=>x.name==='COINS')?.funds??user?.coins?.amount);if(out.credits===null)throw Error('schema_unrecognized');}
 out.success=true;out.error=null;
}catch(e){out.error=['unsafe_identity','persona_unverified','service_timeout','service_failed','schema_unrecognized','invalid_preconditions','service_unavailable'].includes(e?.message)?e.message:'internal_error';}
finally{restore();busy=false;out.observed_at=new Date().toISOString();out.duration_ms=performance.now()-start;}return out;}
Object.defineProperty(window,'__fcE2ELiveV2',{value:Object.freeze({attach,execute})});})();

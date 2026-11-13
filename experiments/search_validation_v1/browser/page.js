/* 001c-04: only explicit, bounded native searches. Positive telemetry schema. */
(() => {
  'use strict';
  if(window.__fcSearchValidationV3)return;
  let busy=false,last=0;
  const num=v=>Number.isSafeInteger(v)&&v>=0?v:null;
  const sha=async v=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(v)))].map(n=>n.toString(16).padStart(2,'0')).join('');
  async function id(v,ns,key){
    if(!(typeof v==='string'&&/^\d{1,24}$/.test(v))&&!(Number.isSafeInteger(v)&&v>=0))throw Error('unsafe_identity');
    return ns+':'+(await sha(key+'|'+ns+'|'+v)).slice(0,24);
  }
  function valid(c){
    if(!c||Object.keys(c).sort().join()!=='evidence_key,id,params'||!/^([a-f0-9]{32})$/.test(c.id)||!/^([a-f0-9]{32})$/.test(c.evidence_key))return false;
    const p=c.params;if(!p||p.count!==21||![1,2].includes(p.page))return false;
    return Object.entries(p).every(([k,v])=>k==='with_caps'?typeof v==='boolean':(['page','count','max_bid','min_buy','max_buy','definition_id'].includes(k)&&num(v)!==null&&(!['definition_id','page','count'].includes(k)||v>0)))&&
      (!p.with_caps||p.definition_id>0)&&
      (p.min_buy??0)<=(p.max_buy??Number.MAX_SAFE_INTEGER);
  }
  async function project(a,i,key){
    return {trade_id:await id(a.tradeId,'trade',key),item_id:await id(i.id,'item',key),definition_id:num(i.definitionId),
      resource_id:num(i.resourceId),asset_id:num(i.assetId),rating:num(i.rating),rarity:num(i.rareflag),
      untradeable:typeof i.untradeable==='boolean'?i.untradeable:null,
      starting_bid:num(a.startingBid),current_bid:num(a.currentBid),buy_now_price:num(a.buyNowPrice),
      expires:a.expires===-1?-1:num(a.expires),
      trade_state:['active','expired','closed','inactive'].includes(a.tradeState)?a.tradeState:null,
      bid_state:['none','highest','outbid','buyNow','sold'].includes(a.bidState)?a.bidState:null};
  }
  function observe(o){return new Promise((resolve,reject)=>{
    const owner={};let done=false;const t=setTimeout(()=>{if(!done){done=true;o.unobserve?.(owner);reject(Error('service_timeout'));}},15000);
    o.observe(owner,(sender,r)=>{if(!done){done=true;clearTimeout(t);sender?.unobserve?.(owner);resolve(r);}});
  });}
  async function read(c){
    const out={schema:3,command_id:c?.id??null,params:c?.params??null,observed_at:new Date().toISOString(),persona:null,native_rules:null,cap_read:null,
      method:'services.Item.searchTransferMarket(criteria,page)',criteria:null,success:false,error:'invalid_command',status:null,
      network:[],rows:null,wire_rows:null,has_more:null,cache_invalidated:false,duration_ms:0};
    if(!valid(c))return out;
    if(location.protocol!=='https:'||!/^(www\.)?ea\.com$/.test(location.hostname)||!/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname)){out.error='wrong_page';return out;}
    if(busy){out.error='bridge_busy';return out;}
    if(Date.now()-last<30000){out.error='experiment_pacing';return out;}
    busy=true;last=Date.now();let restore=()=>{};const began=performance.now(),jobs=[];
    try{
      out.persona=window.__fcDiscoveryPersonaFollowupV1.inspect();if(!out.persona.accepted)throw Error('persona_unverified');
      if(typeof UTCurrencyInputControl!=='undefined'){
        const cls=UTCurrencyInputControl;
        const tiers=Array.isArray(cls.PRICE_TIERS)?cls.PRICE_TIERS.map(t=>({minimum:num(t.min),increment:num(t.inc)})):null;
        const probes=[150,700,950,1000,1100,9900,10000,10500,49750,50000,99500,100000].map(value=>({value,
          above:num(cls.getIncrementAboveVal(value)),below:num(cls.getIncrementBelowVal(value))}));
        const methods=[];let obj=services.Item;
        for(let depth=0;obj&&depth<3;depth++,obj=Object.getPrototypeOf(obj))for(const n of Object.getOwnPropertyNames(obj))
          if(/^[A-Za-z][A-Za-z0-9]{0,70}$/.test(n)&&/price|marketData/i.test(n)&&typeof services.Item[n]==='function'&&!methods.includes(n))methods.push(n);
        out.native_rules={tiers,probes,card_caps_methods:methods,classification:'NATIVE_CLIENT_OBSERVED_SERVER_LEGALITY_UNVERIFIED'};
      }
      const p=c.params,criteria=new UTSearchCriteriaDTO();criteria.type='player';criteria.count=21;
      for(const [k,v] of Object.entries({max_bid:'maxBid',min_buy:'minBuy',max_buy:'maxBuy'}))if(p[k]!=null)criteria[v]=p[k];
      if(p.definition_id!=null)criteria.defId=[p.definition_id];
      out.criteria={type:criteria.type,count:criteria.count,maxBid:num(criteria.maxBid),minBuy:num(criteria.minBuy),maxBuy:num(criteria.maxBuy),defId:p.definition_id??null};
      const proto=XMLHttpRequest.prototype,orig={open:proto.open,send:proto.send,header:proto.setRequestHeader},pending=new WeakMap();
      const open=function(method,url,...args){let m=null;try{
        const u=new URL(url,location.href);
        if(method==='GET'&&u.protocol==='https:'&&/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname)&&['/ut/game/fc27/transfermarket','/ut/game/fc27/marketdata/pricelimits'].includes(u.pathname)){
          const query={};for(const k of ['start','num','count','maxb','minb','micr','macr','maskedDefId','definitionId','defId'])if(u.searchParams.has(k))query[k]=num(Number(u.searchParams.get(k)));
          m={method:'GET',route:u.pathname,query,session_header_present:false,status:null,started_at:null,ended_at:null,duration_ms:null,payload_bytes:null};
        }
      }catch{}pending.set(this,m);return orig.open.call(this,method,url,...args);};
      const header=function(name,value){const m=pending.get(this);if(m&&String(name).toLowerCase()==='x-ut-sid')m.session_header_present=true;return orig.header.call(this,name,value);};
      const send=function(...args){const m=pending.get(this);if(m){const start=performance.now();m.started_at=new Date().toISOString();out.network.push(m);
        this.addEventListener('loadend',()=>{m.status=num(this.status);m.ended_at=new Date().toISOString();m.duration_ms=performance.now()-start;
          try{m.payload_bytes=new TextEncoder().encode(this.responseText).length;const v=JSON.parse(this.responseText);
            if(Array.isArray(v.auctionInfo)&&v.auctionInfo.length<=21)jobs.push(Promise.all(v.auctionInfo.map(a=>project(a,a.itemData,c.evidence_key))).then(rows=>out.wire_rows=rows));
            if(m.route==='/ut/game/fc27/marketdata/pricelimits'&&Array.isArray(v)&&v.length<=10&&out.cap_read)out.cap_read.wire=v.map(x=>({definition_id:num(x.defId),minimum:num(x.minPrice),maximum:num(x.maxPrice)}));
          }catch{}
        },{once:true});}return orig.send.apply(this,args);};
      proto.open=open;proto.send=send;proto.setRequestHeader=header;
      restore=()=>{if(proto.open===open)proto.open=orig.open;if(proto.send===send)proto.send=orig.send;if(proto.setRequestHeader===header)proto.setRequestHeader=orig.header;};
      if(typeof services.Item.clearTransferMarketCache==='function'){services.Item.clearTransferMarketCache();out.cache_invalidated=true;}
      const r=await observe(services.Item.searchTransferMarket(criteria,p.page));await new Promise(resolve=>setTimeout(resolve,0));await Promise.all(jobs);
      out.status=num(r?.status);if(r?.success!==true)throw Error('service_failed');
      const data=r.data??r.response,rows=data?.items??data?.auctionInfo;if(!Array.isArray(rows)||rows.length>21)throw Error('schema_unrecognized');
      out.has_more=typeof data.hasMore==='boolean'?data.hasMore:null;
      out.rows=await Promise.all(rows.map(async raw=>{
        const a=raw.getAuctionData?.()??raw.auctionData??raw._auction??raw,i=raw.itemData??raw;
        const row=await project(a,i,c.evidence_key),limits=raw.getPriceLimits?.();
        row.price_limits=limits?{minimum:num(limits.min??limits.minimum??limits.lower),maximum:num(limits.max??limits.maximum??limits.upper)}:null;
        return row;
      }));
      if(p.with_caps){
        out.cap_read={method:'services.Item.transfersDao.getItemMarketDataByDefId',status:null,success:false,rows:null,wire:null};
        const caps=await observe(services.Item.transfersDao.getItemMarketDataByDefId([p.definition_id]));
        await new Promise(resolve=>setTimeout(resolve,0));
        out.cap_read.status=num(caps.status);out.cap_read.success=caps.success===true;
        const md=caps.response?.marketData;
        if(Array.isArray(md)&&md.length<=10)out.cap_read.rows=md.map(x=>({definition_id:num(x.defId),minimum:num(x.priceLimits?.minimum),maximum:num(x.priceLimits?.maximum)}));
      }
      out.success=true;out.error=null;
    }catch(e){out.error=['unsafe_identity','persona_unverified','service_timeout','service_failed','schema_unrecognized'].includes(e?.message)?e.message:'internal_error';}
    finally{restore();busy=false;out.observed_at=new Date().toISOString();out.duration_ms=performance.now()-began;}
    return out;
  }
  Object.defineProperty(window,'__fcSearchValidationV3',{value:Object.freeze({read})});
})();

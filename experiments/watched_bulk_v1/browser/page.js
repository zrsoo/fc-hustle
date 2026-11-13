/* Isolated 001c-03 read-only experiment. Never returns raw IDs or auth values. */
(() => {
  'use strict';
  if(window.__fcWatchedBulkV2) return;
  let busy=false,lastCall=0;
  const num=x=>Number.isSafeInteger(x)&&x>=0?x:null;
  const sha=async s=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))].map(v=>v.toString(16).padStart(2,'0')).join('');
  async function identity(v,ns,key){
    if(!(typeof v==='string'&&/^\d{1,24}$/.test(v))&&!(Number.isSafeInteger(v)&&v>=0))throw Error('unsafe_integer');
    return ns+':'+(await sha(key+'|'+ns+'|'+v)).slice(0,24);
  }
  function observe(o){
    if(typeof o?.observe!=='function')throw Error('service_unavailable');
    return new Promise((resolve,reject)=>{
      const owner={};let done=false;
      const timer=setTimeout(()=>{if(!done){done=true;o.unobserve?.(owner);reject(Error('service_timeout'));}},15000);
      o.observe(owner,(sender,r)=>{if(done)return;done=true;clearTimeout(timer);sender?.unobserve?.(owner);resolve(r);});
    });
  }
  function capture(rows){
    const proto=XMLHttpRequest.prototype,orig={open:proto.open,send:proto.send,header:proto.setRequestHeader};
    const pending=new WeakMap();
    const open=function(method,url,...rest){
      let m=null;
      try{
        const u=new URL(url,location.href);
        if(u.protocol==='https:'&&/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname)&&u.pathname.startsWith('/ut/game/fc27/')){
          const route=u.pathname.slice('/ut/game/fc27/'.length);
          const safe=/^(watchlist|watchlist\/items|pilesize|tradepile|purchased\/items|user\/currencies|trade\/status)$/.test(route);
          m={method:['GET','POST','PUT','DELETE'].includes(method)?method:'OTHER',route:safe?'/ut/game/fc27/'+route:'/ut/game/fc27/:unrecognized',
            session_header_present:false,status:null,duration_ms:null,payload_bytes:null,started_at:null,ended_at:null,
            pagination:{start:num(Number(u.searchParams.get('start')??NaN)),count:num(Number(u.searchParams.get('count')??NaN))}};
        }
      }catch{}
      pending.set(this,m);return orig.open.call(this,method,url,...rest);
    };
    const header=function(name,value){const m=pending.get(this);if(m&&String(name).toLowerCase()==='x-ut-sid')m.session_header_present=true;return orig.header.call(this,name,value);};
    const send=function(...args){
      const m=pending.get(this);
      if(m){
        const start=performance.now();m.started_at=new Date().toISOString();if(rows.length<30)rows.push(m);
        this.addEventListener('loadend',()=>{m.status=num(this.status);m.duration_ms=performance.now()-start;m.ended_at=new Date().toISOString();
          try{if(this.responseType===''||this.responseType==='text')m.payload_bytes=new TextEncoder().encode(this.responseText).length;}catch{}
        },{once:true});
      }
      return orig.send.apply(this,args);
    };
    proto.open=open;proto.send=send;proto.setRequestHeader=header;
    return ()=>{if(proto.open===open)proto.open=orig.open;if(proto.send===send)proto.send=orig.send;if(proto.setRequestHeader===header)proto.setRequestHeader=orig.header;};
  }
  async function inspect(){
    const sources=[];
    const service=services.Item;
    for(const [label,obj] of [['services.Item',service],['services.Item.itemDao',service.itemDao],['repositories.Item',repositories.Item]]){
      if(!obj)continue;
      const names=new Set();let p=obj;
      for(let depth=0;p&&depth<4;depth++,p=Object.getPrototypeOf(p))for(const n of Object.getOwnPropertyNames(p))if(/watch|pile|tradestatus|setDirty|isDirty/i.test(n)&&/^[A-Za-z][A-Za-z0-9]{0,70}$/.test(n))names.add(n);
      for(const name of names){
        if(typeof obj[name]!=='function')continue;
        let src=Function.prototype.toString.call(obj[name]);
        sources.push({owner:label,name,length:src.length,sha256:await sha(src),source:src.length<=12000?src:null});
      }
    }
    return sources;
  }
  async function read(c){
    const out={schema:2,operation:c?.operation??null,observed_at:new Date().toISOString(),persona:null,
      method:null,status:null,success:false,error:'invalid_command',network:[],auctions:null,has_more:null,sources:null,
      duration_ms:0,network_at:null,request_count:0,account:null,cache_invalidated:false};
    if(!c||Object.keys(c).sort().join()!=='evidence_key,id,operation'||!['inspect','watched'].includes(c.operation)||
      !/^[a-f0-9]{32}$/.test(c.id)||!/^[a-f0-9]{32}$/.test(c.evidence_key))return out;
    if(location.protocol!=='https:'||!/^(www\.)?ea\.com$/.test(location.hostname)||!/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname)){out.error='wrong_page';return out;}
    if(busy){out.error='bridge_busy';return out;}
    busy=true;let restore=()=>{};const start=performance.now();
    try{
      out.persona=window.__fcDiscoveryPersonaFollowupV1.inspect();
      if(!out.persona.accepted)throw Error('persona_unverified');
      const repo=repositories.Item;
      const split=services.Configuration.checkFeatureEnabled(UTServerSettingsRepository.KEY.PLATFORM_SPLIT_FOR_TRANSFER_MARKET);
      out.account={platform_split:typeof split==='boolean'?split:null,
        inbox_capacity:num(repo.getPileSize(ItemPile.INBOX)),
        server_setting_capacity:num(repositories.ServerSettings.getSettingByKey(UTServerSettingsRepository.KEY.TRANSFER_TARGET_SIZE)),
        cached_count_before:num(repo.getWatchedItems().length),cached_count_after:null,
        inbox_dirty_before:repo.isDirty(ItemPile.INBOX)===true};
      if(c.operation==='inspect'){out.sources=await inspect();out.success=true;out.error=null;return out;}
      if(Date.now()-lastCall<30000)throw Error('experiment_pacing');
      restore=capture(out.network);lastCall=Date.now();
      // Source-verified local inbox cache invalidation; no account write.
      repo.setDirty(ItemPile.INBOX);out.cache_invalidated=true;
      out.method='services.Item.requestWatchedItems()';
      const r=await observe(services.Item.requestWatchedItems());
      await new Promise(resolve=>setTimeout(resolve,0));
      out.status=num(r?.status);out.success=r?.success===true;
      if(!out.success){out.error='service_failed';return out;}
      const data=r.data??r.response,rows=data?.items??data?.auctionInfo;
      if(!Array.isArray(rows)||rows.length>200)throw Error('schema_unrecognized');
      out.has_more=typeof data.hasMore==='boolean'?data.hasMore:null;
      out.auctions=await Promise.all(rows.map(async raw=>{
        const a=raw.getAuctionData?.()??raw.auctionData??raw._auction??raw,i=raw.itemData??raw;
        if(!num(i.definitionId))throw Error('schema_unrecognized');
        return {trade_id:await identity(a.tradeId,'trade',c.evidence_key),item_id:await identity(i.id,'item',c.evidence_key),definition_id:i.definitionId,
          current_bid:num(a.currentBid),starting_bid:num(a.startingBid),buy_now_price:num(a.buyNowPrice),expires:a.expires===-1?-1:num(a.expires),
          bid_state:['none','highest','outbid','buyNow','sold'].includes(a.bidState)?a.bidState:null,
          trade_state:['active','closed','expired','inactive'].includes(a.tradeState)?a.tradeState:null};
      }));
      out.error=null;
    }catch(e){out.success=false;out.error=['unsafe_integer','schema_unrecognized','service_timeout','service_unavailable','persona_unverified','experiment_pacing'].includes(e?.message)?e.message:'internal_error';}
    finally{
      restore();busy=false;out.observed_at=new Date().toISOString();out.duration_ms=performance.now()-start;
      out.request_count=out.network.length;
      if(out.account)out.account.cached_count_after=num(repositories.Item.getWatchedItems().length);
      const fresh=out.network.filter(n=>n.method==='GET'&&n.route==='/ut/game/fc27/watchlist'&&n.session_header_present&&n.status>=200&&n.status<300&&n.ended_at);
      out.network_at=fresh.length?fresh[fresh.length-1].ended_at:null;
    }
    return out;
  }
  Object.defineProperty(window,'__fcWatchedBulkV2',{value:Object.freeze({read})});
})();

/* Production protocol 2. Explicit one-shot native calls; no actor or credential export. */
(() => {
  'use strict';
  if (window.__fcProductionV1) return;
  const hex = v => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
  const num = v => Number.isSafeInteger(v) && v >= 0 ? v : null;
  const keys = (v, k) => !!v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).sort().join() === k.split(',').sort().join();
  const random = () => [...crypto.getRandomValues(new Uint8Array(16))].map(v => v.toString(16).padStart(2,'0')).join('');
  const document = random(), known = new Map(), reads = new Map(), sent = new Set();
  const routes = {search:['GET','/ut/game/fc27/transfermarket'], watched:['GET','/ut/game/fc27/watchlist'],
    balance:['GET','/ut/game/fc27/user/credits'], unassigned:['GET','/ut/game/fc27/purchased/items'],
    transfer_list:['GET','/ut/game/fc27/tradepile'], caps:['GET','/ut/game/fc27/marketdata/pricelimits'],
    status:['GET','/ut/game/fc27/trade/status/lite'],
    bid:['PUT','/ut/game/fc27/trade/:trade/bid']};
  const operation = op => Object.hasOwn(routes,op) || ['price_helpers','status_support'].includes(op);
  const empty = error => ({success:false,error,status:null,credits:null,items:null,auctions:null,caps:null,cache_invalidated:false,network:[]});
  let binding = null, nativeUser = null, nativePersona = null, busy = false, poisoned = false;
  const selected = () => services.User.getUser?.()?.getSelectedPersona?.();
  const official = () => location.protocol === 'https:' && /^(www\.)?ea\.com$/.test(location.hostname) && /\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname);
  function validContext(v) {
    return keys(v,'account,persona,game,platform,identity_namespace') && ['account','persona','identity_namespace'].every(k => hex(v[k])) && v.game === 'fc27' && v.platform === 'pc';
  }
  function validFences(v) {
    return keys(v,'owner,epoch,host_epoch,worker_epoch,document') && ['owner','host_epoch','worker_epoch','document'].every(k => hex(v[k])) && Number.isSafeInteger(v.epoch) && v.epoch > 0;
  }
  const equal = (a,b) => !!a && !!b && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => a[k] === b[k]);
  function attach(context, fences) {
    // An operator chooses the account/persona labels in the official selected tab.
    // Bind the actual selected objects privately; never inspect authentication fields.
    if (!official() || !validContext(context) || !validFences(fences) || fences.document !== document || busy || poisoned ||
        ['__fcBiddingV1','__fcDurablePageV1','__fcE2ELiveV2','__fcResolutionV2'].some(k => window[k]) ||
        window.__fcNativeCommandOwner && window.__fcNativeCommandOwner !== document) return false;
    if (window.__fcDiscoveryPersonaFollowupV1?.selectedPlatform() !== 'pc') return false;
    const u = services.User.getUser?.(), p = selected();
    if (!u || !p) return false;
    if (binding) {
      if (!equal(binding.context,context) || fences.epoch < binding.fences.epoch || fences.epoch === binding.fences.epoch && !equal(fences,binding.fences) || u !== nativeUser || p !== nativePersona) return false;
    }
    if (!binding || !equal(binding.fences,fences)) {known.clear(); reads.clear();}
    window.__fcNativeCommandOwner = document;
    binding = {context:{...context},fences:{...fences}}; nativeUser = u; nativePersona = p; return true;
  }
  function valid(c) {
    if (!keys(c,'schema,id,operation,params,context,fences') || c.schema !== 2 || !hex(c.id) || !binding ||
        !equal(c.context,binding.context) || !equal(c.fences,binding.fences) || !operation(c.operation)) return false;
    const p=c.params;
    if (!p || typeof p !== 'object' || Array.isArray(p)) return false;
    if(c.operation==='price_helpers')return keys(p,'version,probes') && p.version===1 && Array.isArray(p.probes) && p.probes.length<=32 &&
      p.probes.every(x=>keys(x,'direction,value') && ['above','below'].includes(x.direction) && num(x.value)!==null);
    if(c.operation==='status_support')return Object.keys(p).length===0;
    if(c.operation==='status')return keys(p,'trade_id,item_id,definition_id') && /^trade:[a-f0-9]{24}$/.test(p.trade_id) &&
      /^item:[a-f0-9]{24}$/.test(p.item_id) && num(p.definition_id)>0;
    if (['watched','balance','unassigned','transfer_list'].includes(c.operation)) return Object.keys(p).length === 0;
    if (c.operation === 'caps') return keys(p,'definition_id') && num(p.definition_id) > 0;
    if (c.operation === 'search') {
      if (p.page !== 1 || p.count !== 21 || p.fresh !== true) return false;
      if (p.purpose === 'discovery') return (keys(p,'purpose,page,count,fresh,max_bid,min_buy') ||
        keys(p,'purpose,definition_id,page,count,fresh,max_bid,min_buy') && num(p.definition_id)>0) && p.max_bid === 1000 && p.min_buy === 11000;
      if (!(num(p.definition_id)>0))return false;
      return p.purpose === 'pricing' && (keys(p,'purpose,definition_id,page,count,fresh') || keys(p,'purpose,definition_id,page,count,fresh,max_buy') && num(p.max_buy) > 0);
    }
    return keys(p,'trade_id,item_id,definition_id,amount,minimum,cap,deadline,status_read_id,balance_read_id') &&
      /^trade:[a-f0-9]{24}$/.test(p.trade_id) && /^item:[a-f0-9]{24}$/.test(p.item_id) &&
      [p.definition_id,p.amount,p.minimum,p.cap].every(v => num(v) > 0) && p.amount === p.minimum && p.amount <= p.cap &&
      typeof p.deadline === 'string' && Date.parse(p.deadline) > Date.now() && hex(p.status_read_id) && hex(p.balance_read_id) &&
      new Set([c.id,p.status_read_id,p.balance_read_id]).size === 3;
  }
  function helper(direction,value) {
    const control=typeof UTCurrencyInputControl==='undefined'?null:UTCurrencyInputControl;
    if(typeof control?.getIncrementAboveVal!=='function' || typeof control?.getIncrementBelowVal!=='function')throw Error('helpers_unavailable');
    // Native helpers return absolute prices, never deltas.
    const price=control[direction==='above'?'getIncrementAboveVal':'getIncrementBelowVal'](value);
    if(num(price)===null || (direction==='above'?price<value:price>value))throw Error('helper_disagreement');
    return price;
  }
  async function id(v,ns,key) {
    if (!(typeof v === 'string' && /^\d{1,24}$/.test(v)) && num(v) === null) throw Error('unsafe_identity');
    const h=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(`${key}|${ns}|${v}`));
    return ns+':'+[...new Uint8Array(h)].map(x => x.toString(16).padStart(2,'0')).join('').slice(0,24);
  }
  async function item(raw,key,lite=false) {
    const i=raw.itemData ?? raw;
    if (!(num(i.definitionId) > 0) && !(lite && (i.definitionId===undefined || i.definitionId===0))) throw Error('schema_unrecognized'); // no resource/base fallback
    return {item_id:await id(i.id,'item',key),definition_id:i.definitionId??null,
      untradeable:typeof i.untradeable === 'boolean' ? i.untradeable : typeof i.tradable === 'boolean' ? !i.tradable : null,
      last_sale_price:num(i.lastSalePrice)};
  }
  async function auction(raw,c,at) {
    if(!raw || typeof raw!=='object' || Array.isArray(raw))throw Error('schema_unrecognized');
    const a=raw.getAuctionData?.() ?? raw.auctionData ?? raw._auction ?? raw;
    if(!a || typeof a!=='object' || Array.isArray(a))throw Error('schema_unrecognized');
    const i=await item(raw,c.context.identity_namespace,c.operation==='status'), t=await id(a.tradeId,'trade',c.context.identity_namespace);
    const won=typeof a.isWon==='function'?a.isWon():null;
    const row={trade_id:t,item:i,starting_bid:num(a.startingBid),current_bid:num(a.currentBid),buy_now_price:num(a.buyNowPrice),
      expires:a.expires === -1 ? -1 : num(a.expires),trade_state:['active','closed','expired','inactive'].includes(a.tradeState)?a.tradeState:null,
      bid_state:['none','highest','outbid','buyNow','sold'].includes(a.bidState)?a.bidState:null,
      native_is_won:typeof won === 'boolean' ? won : null};
    if ([row.starting_bid,row.current_bid,row.buy_now_price,row.expires].some(v=>v===null) ||
        c.operation==='status' && (row.trade_state===null || row.bid_state===null || won!==null && typeof won!=='boolean')) throw Error('schema_unrecognized');
    return row;
  }
  const statusAvailable = () => typeof services.Item?.transfersDao?.getAuctionData==='function';
  function observe(o) {
    if (typeof o?.observe !== 'function') throw Error('service_unavailable');
    return new Promise((resolve,reject)=>{
      const owner={};let done=false;
      const timer=setTimeout(()=>{if(!done){done=true;poisoned=true;o.unobserve?.(owner);reject(Error('service_timeout'));}},15000);
      try {o.observe(owner,(sender,r)=>{if(!done){done=true;clearTimeout(timer);sender?.unobserve?.(owner);resolve(r);}});}
      catch {done=true;clearTimeout(timer);poisoned=true;o.unobserve?.(owner);reject(Error('internal_error'));}
    });
  }
  function capture(rows,c,timing) {
    const proto=XMLHttpRequest.prototype, orig={open:proto.open,send:proto.send,header:proto.setRequestHeader}, pending=new WeakMap();
    const open=function(method,url,...args){let m=null;
      try {const u=new URL(url,location.href);
        if(u.protocol==='https:' && /^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname) && u.pathname.startsWith('/ut/game/fc27/')) {
          const path=u.pathname.replace(/\/trade\/\d{1,24}\/bid$/,'/trade/:trade/bid');
          const query={};for(const k of ['start','num','definitionId','defId','macr','minb','maxb']) if(u.searchParams.has(k)) {
            const values=u.searchParams.getAll(k);if(values.length!==1 || !/^\d+$/.test(values[0]) || num(Number(values[0]))===null) throw Error('bad_query');
            query[k]=Number(values[0]);
          }
          if(c.operation==='status' && path===routes.status[1]){
            const e=known.get(c.params.trade_id);
            const values=u.searchParams.getAll('tradeIds');
            if(values.length!==1 || values[0]!==e?.native_trade_id)throw Error('bad_query');
            query.trade_id=c.params.trade_id; // exact wire match; never export the native ID
          }
          // Unknown paths are represented by a constant, never a raw identifier.
          m={host:u.hostname,method:['GET','PUT'].includes(method)?method:'OTHER',path:Object.values(routes).some(r=>r[1]===path)?path:'/unexpected',query,status:null,session_header_present:false};
        }
      } catch {m={host:'utas.invalid.ea.com',method:'OTHER',path:'/unexpected',query:{},status:null,session_header_present:false};}
      pending.set(this,m);return orig.open.call(this,method,url,...args);};
    const header=function(n,v){const m=pending.get(this);if(m && String(n).toLowerCase()==='x-ut-sid')m.session_header_present=true;return orig.header.call(this,n,v);};
    const send=function(...args){const m=pending.get(this);if(m){const sent=performance.now();rows.push(m);this.addEventListener('loadend',()=>{m.status=num(this.status);timing.ea_rtt_ms+=performance.now()-sent;},{once:true});}return orig.send.apply(this,args);};
    proto.open=open;proto.send=send;proto.setRequestHeader=header;
    return ()=>{if(proto.open===open)proto.open=orig.open;if(proto.send===send)proto.send=orig.send;if(proto.setRequestHeader===header)proto.setRequestHeader=orig.header;};
  }
  async function execute(c) {
    const out={schema:2,command_id:hex(c?.id)?c.id:'0'.repeat(32),operation:operation(c?.operation)?c.operation:null,
      context:binding?{...binding.context}:null,fences:binding?{...binding.fences}:null,result:empty('invalid_command'),
      freshness:{observed_at:new Date().toISOString(),network_at:null,request_count:0,read_id:hex(c?.id)?c.id:'0'.repeat(32),source:'native'},
      coverage:{complete:false,has_more:null},timing:{native_service_ms:0,ea_rtt_ms:0,native_helper_ms:0}};
    if(c?.operation==='price_helpers')out.result={success:false,error:'invalid_command',version:1,above_available:false,below_available:false,probes:[],network:[]};
    if(c?.operation==='status_support')out.result={success:false,error:'invalid_command',function_available:false,retained_count:0,network:[]};
    if(!valid(c))return out;
    if(!official()){out.result.error='wrong_page';return out;}
    if(busy || poisoned || window.__fcNativeCommandOwner!==document){out.result.error='bridge_busy';return out;}
    busy=true;let restore=()=>{};const start=performance.now(),p=c.params,op=c.operation,r=out.result;
    try {
      if(services.User.getUser?.()!==nativeUser || selected()!==nativePersona || window.__fcDiscoveryPersonaFollowupV1?.selectedPlatform()!=='pc')throw Error('persona_unverified');
      if(op==='status_support'){
        // Availability only. Authentication/schema/freshness require an actual status GET.
        r.function_available=statusAvailable();r.retained_count=known.size;r.success=true;r.error=null;return out;
      }
      if(op==='price_helpers'){
        const control=typeof UTCurrencyInputControl==='undefined'?null:UTCurrencyInputControl;
        r.above_available=typeof control?.getIncrementAboveVal==='function';r.below_available=typeof control?.getIncrementBelowVal==='function';
        if(!r.above_available || !r.below_available)throw Error('helpers_unavailable');
        const helperStart=performance.now();let probes;
        try{probes=p.probes.map(x=>({...x,price:helper(x.direction,x.value)}));}
        finally{out.timing.native_helper_ms=performance.now()-helperStart;}
        if(services.User.getUser?.()!==nativeUser || selected()!==nativePersona)throw Error('persona_unverified');
        r.probes=probes;r.success=true;r.error=null;return out;
      }
      let invoke;
      if(op==='search'){
        const q=new UTSearchCriteriaDTO();q.type='player';if(p.definition_id!==undefined)q.defId=[p.definition_id];q.count=21;
        for(const [k,v] of Object.entries({max_bid:'maxBid',min_buy:'minBuy',max_buy:'maxBuy'}))if(p[k]!==undefined)q[v]=p[k];
        if(typeof services.Item.clearTransferMarketCache!=='function')throw Error('service_unavailable');
        services.Item.clearTransferMarketCache();r.cache_invalidated=true;invoke=()=>services.Item.searchTransferMarket(q,1);
      }else if(['watched','unassigned','transfer_list'].includes(op)){
        const [pile,method]={watched:[ItemPile.INBOX,'requestWatchedItems'],unassigned:[ItemPile.PURCHASED,'requestUnassignedItems'],transfer_list:[ItemPile.TRANSFER,'requestTransferItems']}[op];
        if(pile===undefined || typeof repositories?.Item?.setDirty!=='function' || typeof services.Item?.[method]!=='function')throw Error('service_unavailable');
        repositories.Item.setDirty(pile);r.cache_invalidated=true;invoke=()=>services.Item[method]();
      }else if(op==='balance')invoke=()=>services.User.requestCurrencies();
      else if(op==='status'){
        if(!statusAvailable())throw Error('service_unavailable');
        const e=known.get(p.trade_id);
        if(!e || e.row.item.item_id!==p.item_id || e.row.item.definition_id!==p.definition_id)throw Error('known_identity_unavailable');
        // Native DAO consumes only tradeId/isValid and sets local isUpdating.
        // This descriptor is a request selector, never an observed auction state.
        const query={tradeId:e.native_trade_id,isValid:()=>true,isUpdating:false};
        invoke=()=>services.Item.transfersDao.getAuctionData([{getAuctionData:()=>query}]);
      }
      else if(op==='caps'){
        if(typeof services.Item?.transfersDao?.getItemMarketDataByDefId!=='function')throw Error('service_unavailable');
        invoke=()=>services.Item.transfersDao.getItemMarketDataByDefId([p.definition_id]);
      }
      else {
        const e=known.get(p.trade_id),b=reads.get(p.balance_read_id),s=reads.get(p.status_read_id);
        const age=at=>at!==null && Date.now()-Date.parse(at)>=0 && Date.now()-Date.parse(at)<=30000;
        if(!e || e.read_id!==p.status_read_id || !s || !['search','watched'].includes(s.operation) || !age(e.at) || !b || b.operation!=='balance' || !age(b.at) || b.credits<p.amount ||
          e.row.item.item_id!==p.item_id || e.row.item.definition_id!==p.definition_id || e.row.item.untradeable!==false ||
          e.row.trade_state!=='active' || !['none','outbid'].includes(e.row.bid_state) || e.row.expires<=0 ||
          Date.now()>=Date.parse(e.at)+e.row.expires*1000 || Date.parse(p.deadline)>Date.parse(e.at)+e.row.expires*1000 ||
          p.amount>=e.row.buy_now_price || sent.has(c.id) || sent.has(p.trade_id))throw Error('invalid_preconditions');
        const base=e.row.current_bid===0?e.row.starting_bid:e.row.current_bid;
        if(base<=0 || helper('above',helper('below',base))!==base)throw Error('helper_disagreement');
        const minimum=e.row.current_bid===0?base:helper('above',base);
        if(num(minimum)===null || p.amount!==minimum)throw Error('invalid_preconditions');
        sent.add(c.id);sent.add(p.trade_id);known.delete(p.trade_id);invoke=()=>services.Item.bid(e.raw,p.amount);
      }
      restore=capture(r.network,c,out.timing);const at=new Date().toISOString();
      const response=await observe(invoke());await new Promise(resolve=>setTimeout(resolve,0));
      r.status=Number.isInteger(response?.status) && response.status>=100 && response.status<=599?response.status:null;
      if(response?.success!==true)throw Error('service_failed');
      const n=r.network;
      if(n.length!==1 || n[0].method!==routes[op][0] || n[0].path!==routes[op][1])throw Error('ambiguous_network');
      if(!n[0].session_header_present || !(n[0].status>=200 && n[0].status<300))throw Error('unauthenticated');
      if(n[0].status!==r.status)throw Error('schema_unrecognized');
      if(op==='search'){
        const q=n[0].query,expected={start:0,num:21};
        if(p.definition_id!==undefined){
          if(['definitionId','defId'].filter(k=>Object.hasOwn(q,k)).length!==1)throw Error('schema_unrecognized');
          expected[Object.hasOwn(q,'definitionId')?'definitionId':'defId']=p.definition_id;
        }
        for(const [k,wire] of [['max_bid','macr'],['min_buy','minb'],['max_buy','maxb']])if(p[k]!==undefined)expected[wire]=p[k];
        if(!equal(q,expected))throw Error('schema_unrecognized');
      }
      if(op==='caps' && !equal(n[0].query,{defId:p.definition_id}))throw Error('schema_unrecognized');
      if(['watched','balance','unassigned','transfer_list'].includes(op) && !equal(n[0].query,{}))throw Error('schema_unrecognized');
      if(op==='status' && !equal(n[0].query,{trade_id:p.trade_id}))throw Error('schema_unrecognized');
      if(Date.now()<Date.parse(at) || Date.now()-Date.parse(at)>30000)throw Error('stale_source');
      out.freshness.network_at=at;
      if(services.User.getUser?.()!==nativeUser || selected()!==nativePersona)throw Error('persona_unverified');
      const data=response.data??response.response;
      if(['search','watched','transfer_list','unassigned','status'].includes(op)){
        // The native status observable exposes items, not the raw HTTP envelope.
        const rows=op==='status'?data?.items:data?.items??data?.auctionInfo??data?.itemData;
        if(!Array.isArray(rows)||rows.length>(op==='search'?21:100))throw Error('schema_unrecognized');
        if(op==='unassigned')r.items=await Promise.all(rows.map(raw=>item(raw,c.context.identity_namespace)));
        else r.auctions=await Promise.all(rows.map(raw=>auction(raw,c,at)));
        if(op==='search' && p.definition_id!==undefined && r.auctions.some(a=>a.item.definition_id!==p.definition_id))throw Error('schema_unrecognized');
        if(op==='status' && (r.auctions.length>1 || r.auctions.some(a=>a.trade_id!==p.trade_id || a.item.item_id!==p.item_id ||
          a.item.definition_id && a.item.definition_id!==p.definition_id)))throw Error('schema_unrecognized');
        const identities=(r.auctions??r.items).map(x=>x.trade_id??x.item_id);
        if(new Set(identities).size!==identities.length)throw Error('schema_unrecognized');
        // Commit exact native mappings only after the entire fresh read succeeds.
        if(['search','watched','transfer_list'].includes(op)) {
          const entries=await Promise.all(r.auctions.map(async(row,index)=>{
            const raw=rows[index],a=raw.getAuctionData?.()??raw.auctionData??raw._auction??raw;
            const native_trade_id=String(a.tradeId);
            if(await id(native_trade_id,'trade',c.context.identity_namespace)!==row.trade_id)throw Error('unsafe_identity');
            const retained=known.get(row.trade_id);
            if(retained && (retained.row.item.item_id!==row.item.item_id || retained.row.item.definition_id!==row.item.definition_id))throw Error('schema_unrecognized');
            return [row.trade_id,{raw,row,at,read_id:c.id,native_trade_id}];
          }));
          if(Date.now()<Date.parse(at) || Date.now()-Date.parse(at)>30000)throw Error('stale_source');
          entries.forEach(([key,value])=>known.set(key,value));
        }
        out.coverage.has_more=typeof data.hasMore==='boolean'?data.hasMore:null;
      }else if(op==='balance'){
        r.credits=num(data?.credits)??num(data?.currencies?.find?.(x=>x.name==='COINS')?.funds)??num(services.User.getUser?.()?.coins?.amount);
        if(r.credits===null)throw Error('schema_unrecognized');
      }else if(op==='caps'){
        // DAO observable shape is not the HTTP minPrice/maxPrice array:
        // retained native-source-contract.json projects it into marketData.
        const rows=data?.marketData;
        if(!Array.isArray(rows)||rows.length!==1)throw Error('schema_unrecognized');
        const x=rows[0];r.caps={definition_id:num(x.defId),minimum:num(x.priceLimits?.minimum),maximum:num(x.priceLimits?.maximum)};
        if(r.caps.definition_id!==p.definition_id || !(r.caps.minimum>0) || r.caps.maximum<r.caps.minimum)throw Error('schema_unrecognized');
      }
      if(Date.now()<Date.parse(at) || Date.now()-Date.parse(at)>30000)throw Error('stale_source');
      r.success=true;r.error=null;reads.set(c.id,{operation:op,at,credits:r.credits});
    }catch(e){
      r.success=false;r.error=['known_identity_unavailable','helpers_unavailable','helper_disagreement','service_unavailable','service_timeout','service_failed','schema_unrecognized','unsafe_identity','persona_unverified','invalid_preconditions','unauthenticated','ambiguous_network','stale_source'].includes(e?.message)?e.message:'internal_error';
      if(op==='bid' || ['service_timeout','ambiguous_network'].includes(r.error))poisoned=true;
    }finally{
      restore();busy=false;out.freshness.observed_at=new Date().toISOString();out.freshness.request_count=r.network.length;out.timing.native_service_ms=performance.now()-start;
    }
    return out;
  }
  Object.defineProperty(window,'__fcProductionV1',{value:Object.freeze({attach,execute,document})});
})();

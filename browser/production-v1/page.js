/* Production protocol 2. Explicit one-shot native calls; no actor or credential export. */
(() => {
  'use strict';
  if (window.__fcProductionV1) return;
  const hex = v => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
  const num = v => Number.isSafeInteger(v) && v >= 0 ? v : null;
  const keys = (v, k) => !!v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).sort().join() === k.split(',').sort().join();
  const random = () => [...crypto.getRandomValues(new Uint8Array(16))].map(v => v.toString(16).padStart(2,'0')).join('');
  const diagnostic=(id,stage,detail={})=>{try{window.__fcProductionDiagnosticsV1?.record(id,stage,detail);}catch{}};
  const fieldType=v=>v===null?'null':Array.isArray(v)?'array':typeof v;
  const document = random(), known = new Map(), statusSelectors = new Map(), physical = new Map(), reads = new Map(), sent = new Set();
  const routes = {search:['GET','/ut/game/fc27/transfermarket'], watched:['GET','/ut/game/fc27/watchlist'],
    balance:['GET','/ut/game/fc27/user/credits'], unassigned:['GET','/ut/game/fc27/purchased/items'],owned_item:['GET','/ut/game/fc27/item'],
    transfer_list:['GET','/ut/game/fc27/tradepile'], caps:['GET','/ut/game/fc27/marketdata/pricelimits'],
    status:['GET','/ut/game/fc27/trade/status/lite'],
    bid:['PUT','/ut/game/fc27/trade/:trade/bid'], move:['PUT','/ut/game/fc27/item'], list:['POST','/ut/game/fc27/auctionhouse'],
    clear_sold:['DELETE','/ut/game/fc27/trade/sold'],relist_all:['PUT','/ut/game/fc27/auctionhouse/relist']};
  const bulk=op=>['clear_sold','relist_all'].includes(op);
  const operation = op => Object.hasOwn(routes,op) || ['price_helpers','status_support'].includes(op);
  const metadataPath='/ut/game/fc27/attributes/metadata';
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
    if (!binding || !equal(binding.fences,fences)) {known.clear(); statusSelectors.clear(); physical.clear(); reads.clear();}
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
    if(['status','owned_item'].includes(c.operation))return keys(p,'trade_id,item_id,definition_id') && /^trade:[a-f0-9]{24}$/.test(p.trade_id) &&
      /^item:[a-f0-9]{24}$/.test(p.item_id) && num(p.definition_id)>0;
    if (['watched','balance','unassigned','transfer_list'].includes(c.operation)) return Object.keys(p).length === 0;
    if (c.operation === 'caps') return keys(p,'definition_id') && num(p.definition_id) > 0;
    if(bulk(c.operation))return keys(p,'before_read_id,expected_item_ids,expected_inventory_ids,expected_sold_count,expected_expired_count') &&
      hex(p.before_read_id) && c.id!==p.before_read_id &&
      ['expected_item_ids','expected_inventory_ids'].every(k=>Array.isArray(p[k]) && p[k].length<=100 &&
        new Set(p[k]).size===p[k].length && p[k].every(v=>/^item:[a-f0-9]{24}$/.test(v))) &&
      p.expected_item_ids.length>0 && p.expected_item_ids.every(v=>p.expected_inventory_ids.includes(v)) &&
      num(p.expected_sold_count)!==null && num(p.expected_expired_count)!==null;
    if(['move','list'].includes(c.operation))return keys(p,'trade_id,item_id,definition_id,paid,owned_read_id,win_read_id,caps_read_id,starting_bid,buy_now_price,duration') &&
      /^trade:[a-f0-9]{24}$/.test(p.trade_id) && /^item:[a-f0-9]{24}$/.test(p.item_id) &&
      [p.definition_id,p.paid,p.starting_bid,p.buy_now_price].every(v=>num(v)>0) && p.duration===3600 && p.starting_bid<p.buy_now_price &&
      [p.owned_read_id,p.win_read_id,p.caps_read_id].every(hex) && ![p.owned_read_id,p.win_read_id,p.caps_read_id].includes(c.id);
    if (c.operation === 'search') {
      if (!Number.isInteger(p.page) || p.page < 1 || p.page > (p.purpose==='discovery'?10:1) || p.count !== 21 || p.fresh !== true) return false;
      if (p.purpose === 'discovery') return (keys(p,'purpose,page,count,fresh,max_bid,min_buy') ||
        keys(p,'purpose,definition_id,page,count,fresh,max_bid,min_buy') && num(p.definition_id)>0) && num(p.max_bid)!==null && num(p.min_buy)!==null;
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
  async function item(raw,key,lite=false,cid=null,allowNull=false) {
    const i=raw.itemData ?? raw;
    if (!(num(i.definitionId) > 0) && !(lite && (i.definitionId===undefined || i.definitionId===0 || allowNull && i.definitionId===null))) {
      diagnostic(cid,'ITEM_SCHEMA_FAILURE',{definition_type:fieldType(i.definitionId),resource_type:fieldType(i.resourceId)});
      throw Error('schema_unrecognized'); // no resource/base fallback
    }
    return {item_id:await id(i.id,'item',key),definition_id:i.definitionId??null,
      untradeable:typeof i.untradeable === 'boolean' ? i.untradeable : typeof i.tradable === 'boolean' ? !i.tradable : null,
      last_sale_price:num(i.lastSalePrice)};
  }
  async function auction(raw,c,at) {
    if(!raw || typeof raw!=='object' || Array.isArray(raw))throw Error('schema_unrecognized');
    const a=raw.getAuctionData?.() ?? raw.auctionData ?? raw._auction ?? raw;
    if(!a || typeof a!=='object' || Array.isArray(a))throw Error('schema_unrecognized');
    const i=await item(raw,c.context.identity_namespace,c.operation==='status',c.id,c.schema===4), t=await id(a.tradeId,'trade',c.context.identity_namespace);
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
  const bidReceipt = () => ({schema:1,verdict:'UNCONFIRMED',reason:'MISSING_NATIVE_RECEIPT',
    wire_trade_id:null,wire_amount:null,wire_identity_matches:false,wire_amount_matches:false,
    wire_item_count:null,wire_error_code:null,native_success:null,native_error_code:null,
    native_error_name:null,native_item_count:null,matching_item_count:0,input_stale:null,before_bid_state:null,auction:null});
  // Observe the service's existing DAO subscription. Do not subscribe a second
  // time, dispatch a second request, or replace the returned observable.
  function captureBid(raw,amount,state) {
    const dao=services.Item.transfersDao,original=dao?.bid,restores=[];
    if(typeof original!=='function')throw Error('service_unavailable');
    const wrapped=function(input,value,...args){
      if(input!==raw || value!==amount || ++state.invocations!==1)throw Error('invalid_preconditions');
      const o=original.call(this,input,value,...args),observe=o?.observe;
      if(typeof observe!=='function')throw Error('service_unavailable');
      const intercepted=function(owner,cb,...more){return observe.call(this,owner,(sender,result)=>{
        state.native=result;return cb(sender,result);
      },...more);};
      o.observe=intercepted;restores.push(()=>{if(o.observe===intercepted)o.observe=observe;});return o;
    };
    dao.bid=wrapped;
    return ()=>{if(dao.bid===wrapped)dao.bid=original;restores.reverse().forEach(f=>f());};
  }
  async function finishBid(state,c) {
    const receipt=state.receipt,p=c.params,result=state.native,data=result?.response;
    receipt.native_success=typeof result?.success==='boolean'?result.success:null;
    receipt.native_error_code=num(result?.error?.code)??num(result?.error);
    // Only reviewed public enum names escape. Unknown errors remain ambiguous.
    const names=['STATE_INVALID','NO_TRADE_EXISTS','NOT_ENOUGH_CREDIT','INVALID_OWNER','CARD_IN_TRADE'];
    const codes=typeof UtasErrorCode==='undefined'?{}:UtasErrorCode;
    receipt.native_error_name=receipt.native_error_code===null?null:
      names.find(name=>Number.isSafeInteger(codes[name]) && codes[name]===receipt.native_error_code)??null;
    const items=Array.isArray(data?.items)?data.items:null;
    receipt.native_item_count=items?.length??null;
    const a=state.raw.getAuctionData?.();
    const stale=typeof a?.isStale==='function'?a.isStale():a?.isStale;
    receipt.input_stale=typeof stale==='boolean'?stale:null;
    const matches=[];
    for(const raw of items??[]){
      try{
        const row=await auction(raw,{...c,operation:'status'},null);
        if(row.trade_id===p.trade_id && row.item.item_id===p.item_id &&
            [null,0,p.definition_id].includes(row.item.definition_id))matches.push(row);
      }catch{} // Missing or malformed evidence never implies acceptance.
    }
    receipt.matching_item_count=matches.length;
    if(matches.length===1)receipt.auction=matches[0];
    const bound=state.invocations===1 && receipt.wire_identity_matches && receipt.wire_amount_matches;
    const row=receipt.auction;
    const participating=row && (row.bid_state==='highest' && row.current_bid===p.amount ||
      row.bid_state==='outbid' && state.before.bid_state==='none' && row.current_bid>=p.amount);
    if(bound && receipt.native_success===true && receipt.native_error_code===null && receipt.wire_error_code===null &&
        receipt.wire_item_count===1 && receipt.native_item_count===1 && receipt.input_stale!==true && participating){
      receipt.verdict='ACCEPTED';receipt.reason='MATCHING_NATIVE_PARTICIPATION';
    }else if(bound && result?.status>=400 && result.status<500 && receipt.native_success===false && receipt.native_error_name &&
        receipt.native_item_count===0 && !row && receipt.wire_error_code===receipt.native_error_code){
      receipt.verdict='REJECTED';receipt.reason='EXPLICIT_NATIVE_REJECTION';
    }else receipt.reason=receipt.input_stale===true?'STALE_NATIVE_ITEM':
      receipt.native_item_count===0?'EMPTY_NATIVE_ITEMS':row?.bid_state==='none'?'NO_ACCOUNT_PARTICIPATION':'MISSING_NATIVE_RECEIPT';
    return receipt;
  }
  function observe(o,cid,poisonFailure=true) {
    if (typeof o?.observe !== 'function') throw Error('service_unavailable');
    return new Promise((resolve,reject)=>{
      const owner={};let done=false;
      const timer=setTimeout(()=>{if(!done){done=true;if(poisonFailure)poisoned=true;diagnostic(cid,'NATIVE_TIMEOUT');o.unobserve?.(owner);reject(Error('service_timeout'));}},15000);
      try {o.observe(owner,(sender,r)=>{if(!done){done=true;clearTimeout(timer);diagnostic(cid,'NATIVE_CALLBACK',{success:r?.success,status:r?.status});sender?.unobserve?.(owner);resolve(r);}});}
      catch(e) {done=true;clearTimeout(timer);if(poisonFailure)poisoned=true;o.unobserve?.(owner);reject(Error(e?.message==='bulk_contract_changed'?'bulk_contract_changed':'internal_error'));}
    });
  }
  function capture(rows,c,timing,inventory) {
    const proto=XMLHttpRequest.prototype, orig={open:proto.open,send:proto.send,header:proto.setRequestHeader}, pending=new WeakMap();
    let active=true;const listeners=[];
    const listen=(xhr,fn)=>{const guarded=()=>{if(!inventory.controllerRead || active)fn();};
      if(inventory.controllerRead)listeners.push([xhr,guarded]);xhr.addEventListener('loadend',guarded,{once:true});};
    const open=function(method,url,...args){let m=null;
      if(inventory.controllerRead && !inventory.delivery?.sending()){
        // A matching URL is not proof of this command's request ownership.
        // Never inspect unowned query/body/header values or promote its status.
        let scope='outside_ut';try{const u=new URL(url,location.href);
          if(u.protocol==='https:' && /^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname) && u.pathname.startsWith('/ut/game/fc27/'))scope=method==='GET'?'ea_read':'ea_write';
        }catch{}
        pending.set(this,{background:true,scope,method:['GET','POST','PUT','DELETE'].includes(method)?method:'OTHER'});
        return orig.open.call(this,method,url,...args);
      }
      try {const u=new URL(url,location.href);
        const ut=u.protocol==='https:' && /^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname) && u.pathname.startsWith('/ut/game/fc27/');
        // UI navigation and telemetry are not additional bulk mutations. Observe
        // their existence without intercepting credentials, query values or bodies.
        const listRefresh=c.operation==='list' && ut && method==='GET' && u.pathname===routes.status[1];
        if((bulk(c.operation) || c.operation==='list') && (!ut && !u.pathname.startsWith('/ut/game/fc27/') ||
            ut && method==='GET' && !listRefresh && !(c.operation==='clear_sold' && u.pathname===routes.transfer_list[1]))){
          pending.set(this,{background:true,scope:ut?'ea_read':'outside_ut',method:['GET','POST','PUT','DELETE'].includes(method)?method:'OTHER'});
          return orig.open.call(this,method,url,...args);
        }
        if(u.protocol==='https:' && /^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname) && u.pathname.startsWith('/ut/game/fc27/')) {
          const path=u.pathname.replace(/\/trade\/\d{1,24}\/bid$/,'/trade/:trade/bid');
          if(c.operation==='bid'){
            const state=inventory.bid,match=u.pathname.match(/^\/ut\/game\/fc27\/trade\/(\d{1,24})\/bid$/);
            if(method!=='PUT' || !match || match[1]!==state?.nativeTrade || u.search!=='')throw Error('bad_query');
            state.receipt.wire_identity_matches=true;state.receipt.wire_trade_id=c.params.trade_id;
          }
          const query={};for(const k of ['start','num','definitionId','defId','macr','minb','maxb']) if(u.searchParams.has(k)) {
            const values=u.searchParams.getAll(k);if(values.length!==1 || !/^\d+$/.test(values[0]) || num(Number(values[0]))===null) throw Error('bad_query');
            query[k]=Number(values[0]);
          }
          if(path===metadataPath && u.searchParams.has('defIds')){
            const values=u.searchParams.getAll('defIds'),ids=values.length===1?values[0].split(','):[];
            if(!ids.length || ids.length>21 || ids.some(x=>!/^\d+$/.test(x)||!(num(Number(x))>0)))throw Error('bad_query');
            query.defIds=ids.map(Number);
            if([...u.searchParams.keys()].some(k=>k!=='defIds'))throw Error('bad_query');
          }
          if(c.operation==='status' && path===routes.status[1]){
            const e=known.get(c.params.trade_id)??statusSelectors.get(c.params.trade_id);
            const values=u.searchParams.getAll('tradeIds');
            if(values.length!==1 || values[0]!==e?.native_trade_id)throw Error('bad_query');
            query.trade_id=c.params.trade_id; // exact wire match; never export the native ID
          }
          if(c.operation==='owned_item' && path===routes.owned_item[1]){
            const e=known.get(c.params.trade_id),values=u.searchParams.getAll('idList');
            if(method!=='GET' || values.length!==1 || values[0]!==String(e?.raw?.id) ||
               [...u.searchParams.keys()].some(k=>k!=='idList'))throw Error('bad_query');
            query.item_id=c.params.item_id; // exact private wire match, no raw ID export
          }
          if(listRefresh){
            // Item.list assigns the new native auction ID before its mandatory
            // refreshAuctions read. Bind that read to this exact physical DTO.
            const nativeId=inventory.listRaw?.getAuctionData?.()?.tradeId;
            const values=u.searchParams.getAll('tradeIds');
            if(values.length!==1 || String(nativeId)==='0' || values[0]!==String(nativeId) ||
                [...u.searchParams.keys()].some(k=>k!=='tradeIds'))throw Error('bad_query');
            query.item_id=c.params.item_id;
          }
          // Unknown paths are represented by a constant, never a raw identifier.
          m={host:u.hostname,method:['GET','PUT','POST','DELETE'].includes(method)?method:'OTHER',path:path===metadataPath || Object.values(routes).some(r=>r[1]===path)?path:'/unexpected',query,status:null,session_header_present:false};
          if(m.path==='/unexpected'){
            // Diagnostic categories only: never export an unknown URL/path,
            // query, request body or header value. This does not allow traffic
            // through the command's existing exact network/freshness guard.
            const relative=u.pathname.slice('/ut/game/fc27/'.length);
            const groups={settings:'SETTINGS',usermassinfo:'USER_MASSINFO',user:'USER',
              club:'CLUB',squad:'SQUAD',store:'STORE',favorites:'FAVORITES',
              auctionhouse:'AUCTIONHOUSE',item:'ITEM'};
            const key=relative.split('/')[0];
            diagnostic(c.id,'UNCLASSIFIED_EA_REQUEST',{method:m.method,
              route_group:Object.hasOwn(groups,key)?groups[key]:'OTHER'});
          }
          if(bulk(c.operation) && u.search!=='')m.path='/unexpected';
        }
      } catch {m={host:'utas.invalid.ea.com',method:'OTHER',path:'/unexpected',query:{},status:null,session_header_present:false};}
      if((bulk(c.operation) || c.operation==='list') && !m)m={host:'utas.invalid.ea.com',method:'OTHER',path:'/unexpected',query:{},status:null,session_header_present:false};
      if(inventory.controllerRead)inventory.delivery.open(m);
      pending.set(this,m);return orig.open.call(this,method,url,...args);};
    const header=function(n,v){const m=pending.get(this);if(m && !m.background && String(n).toLowerCase()==='x-ut-sid')m.session_header_present=true;return orig.header.call(this,n,v);};
    const send=function(...args){const m=pending.get(this);if(m){
      if(c.operation==='bid'){
        const state=inventory.bid;let body;
        try{body=JSON.parse(args[0]);}catch{}
        if(!state?.receipt.wire_identity_matches || m.method!=='PUT' || m.path!==routes.bid[1] ||
            !keys(body,'bid') || body.bid!==c.params.amount || rows.length)throw Error('invalid_preconditions');
        state.receipt.wire_amount=body.bid;state.receipt.wire_amount_matches=true;
      }
      if(m.background){
        diagnostic(c.id,'BACKGROUND_REQUEST',{traffic_scope:m.scope,method:m.method});
        listen(this,()=>diagnostic(c.id,'BACKGROUND_RESPONSE',{traffic_scope:m.scope,method:m.method,status:num(this.status)}));
        return orig.send.apply(this,args);
      }
      if(c.operation==='list' && !(m.method==='POST' && m.path===routes.list[1] && equal(m.query,{}) ||
          m.method==='GET' && m.path===routes.status[1] && equal(m.query,{item_id:c.params.item_id}))){
        throw Error('ambiguous_network');
      }
      if(c.operation==='list' && (m.method==='POST' && rows.some(n=>n.method==='POST') ||
          m.method==='GET' && args[0]!=null && args[0]!==''))throw Error('ambiguous_network');
      if(bulk(c.operation)){
        m.body_empty=args[0]==null || args[0]==='';
        const target=m.method===routes[c.operation][0] && m.path===routes[c.operation][1];
        const read=c.operation==='clear_sold' && m.method==='GET' && m.path===routes.transfer_list[1];
        if(!m.body_empty || !equal(m.query,{}) || !target && !read ||
            target && rows.some(n=>n.method!=='GET') || read && rows.filter(n=>n.method==='GET').length>=2){
          inventory.bulkViolation=true;
          diagnostic(c.id,'BULK_REQUEST_BLOCKED',{traffic_scope:'ea_write',method:m.method,
            violation:!m.body_empty?'body':!equal(m.query,{})?'query':!target&&!read?'route':'duplicate'});
          throw Error('bulk_contract_changed');
        }
      }
      const sent=performance.now();rows.push(m);listen(this,()=>{
      // XHR zero means no HTTP status, not an HTTP response code. Preserve
      // that absence without manufacturing a status or a successful read.
      const wireStatus=num(this.status);m.status=wireStatus===0?null:wireStatus;
      timing.ea_rtt_ms+=performance.now()-sent;
      if(c.operation==='bid'){
        try{const data=this.responseType==='json'?this.response:JSON.parse(this.responseType==='arraybuffer'?new TextDecoder().decode(this.response):this.responseText);
          inventory.bid.receipt.wire_item_count=Array.isArray(data?.auctionInfo)?data.auctionInfo.length:null;
          inventory.bid.receipt.wire_error_code=num(data?.code);
        }catch{} // Keep only allowlisted counts/codes, never raw HTTP bodies.
      }
      // Inspect only this read's auction rows privately. Never retain the raw
      // response, headers, credentials, or unrelated response fields.
      if(c.operation==='transfer_list' && m.path===routes.transfer_list[1]){
        try{const data=this.responseType==='json'?this.response:JSON.parse(this.responseType==='arraybuffer'?new TextDecoder().decode(this.response):this.responseText);
          inventory.wire=Array.isArray(data?.auctionInfo)?data.auctionInfo:null;
          inventory.truncated=data?.hasMore===true;
        }catch{inventory.wire=null;}
      }
      diagnostic(c.id,'EA_RESPONSE',{status:m.status,request_count:rows.length,xhr_zero_status:wireStatus===0});});}return orig.send.apply(this,args);};
    proto.open=open;proto.send=send;proto.setRequestHeader=header;
    return ()=>{active=false;for(const [xhr,fn]of listeners)xhr.removeEventListener?.('loadend',fn);
      if(proto.open===open)proto.open=orig.open;if(proto.send===send)proto.send=orig.send;if(proto.setRequestHeader===header)proto.setRequestHeader=orig.header;};
  }
  function controllerReadInvocation(invoke,c,inventory){
    const queue=services.UTUtasRequestQueue,requests=[],restorers=[],subscriptions=[];
    let active=true,scope=null,current=null,primary=0,clearBefore=0,clearAfter=0,listRefresh=0,metadata=0;
    const metaItems=new Set();
    if(typeof queue?.send!=='function' || !Array.isArray(queue.queue))throw Error('service_unavailable');
    const live=()=>active && valid(c) && services.User.getUser?.()===nativeUser && selected()===nativePersona &&
      window.__fcDiscoveryPersonaFollowupV1?.selectedPlatform()==='pc';
    const within=(value,fn)=>{const previous=scope,sending=current;scope=value;
      if(value.callback)current=null;
      try{return fn();}finally{scope=previous;if(value.callback)current=sending;}};
    const wrap=(obj,key,factory)=>{
      if(!obj || typeof obj[key]!=='function')return;
      const descriptor=Object.getOwnPropertyDescriptor(obj,key),original=obj[key],replacement=factory(original);
      obj[key]=replacement;restorers.push(()=>{if(obj[key]===replacement){if(descriptor)Object.defineProperty(obj,key,descriptor);else delete obj[key];}});
    };
    function observable(value,role){
      if(typeof value?.observe!=='function')return value;
      wrap(value,'observe',original=>function(owner,callback,...args){
        // Only subscriptions registered by the owned native call/continuation
        // carry lineage. Arbitrary observers never become ownership scopes.
        if(!scope)return original.call(this,owner,callback,...args);
        subscriptions.push([this,owner]);
        return original.call(this,owner,function(sender,response,...more){
          if(!live()){try{sender?.unobserve?.(owner);}catch{}return;}
          if(role==='primary' && c.operation==='search'){
            const items=(response?.response??response?.data)?.items;
            if(Array.isArray(items))for(const item of items)metaItems.add(item);
          }
          return within({role,callback:true},()=>callback(sender,response,...more));
        },...args);
      });
      return value;
    }
    function method(obj,key,role,allow){
      wrap(obj,key,original=>function(...args){
        if(!scope || !allow(args))return original.apply(this,args);
        if(!live())throw Error('invalid_preconditions');
        return within({role,callback:false},()=>observable(original.apply(this,args),role));
      });
    }
    const finish=success=>{active=false;
      for(const [value,owner]of subscriptions){try{value.unobserve?.(owner);}catch{}}
      if(!success){for(let i=queue.queue.length-1;i>=0;i--)if(requests.some(r=>r.request===queue.queue[i].request))queue.queue.splice(i,1);
        for(const {request}of requests){try{request.abort?.();}catch{}}}
      restorers.reverse().forEach(f=>f());};
    try{
    const root=()=>scope?.role==='root';
    const parent=role=>scope?.callback===true && scope.role===role &&
      (role!=='primary' || requests.some(({token})=>token.role==='primary' && token.sent && token.opens===1));
    const item=services.Item,dao=item?.itemDao,transfers=item?.transfersDao;
    const primaryMethods={search:[dao,'searchTransferMarket'],watched:[dao,'getWatchPile'],
      transfer_list:[dao,'getTransferPile'],unassigned:[dao,'getUnassignedPile'],owned_item:[dao,'getItemDataById'],
      caps:[transfers,'getItemMarketDataByDefId'],move:[dao,'move'],list:[dao,'listItem'],
      clear_sold:[transfers,'removeSold'],relist_all:[transfers,'relistExpiredAuctions']};
    const leaf=primaryMethods[c.operation];
    if(!leaf || typeof leaf[0]?.[leaf[1]]!=='function')throw Error('service_unavailable');
    method(leaf[0],leaf[1],'primary',()=>root() || c.operation==='clear_sold' && parent('clear_before'));
    for(const [obj,key]of [[dao,'move'],[dao,'listItem'],[transfers,'removeSold'],[transfers,'relistExpiredAuctions']]){
      if(obj===leaf[0] && key===leaf[1])continue;
      wrap(obj,key,original=>function(...args){
        if(scope)throw Error('invalid_preconditions');
        return original.apply(this,args);
      });
    }
    if(c.operation==='search')method(services.PlayerMetaData,'updateItemPlayerMeta','metadata',args=>{
      if(!parent('primary'))return false;
      if(metadata || !Array.isArray(args[0]) || !args[0].length || args[0].length>21 ||
          !args[0].every(raw=>metaItems.has(raw)))throw Error('invalid_preconditions');
      metadata++;return true;
    });
    if(c.operation==='list')method(item,'refreshAuctions','list_refresh',args=>{
      if(!parent('primary'))return false;
      if(listRefresh || args.length!==1 || args[0]!==inventory.listRaw)throw Error('invalid_preconditions');
      listRefresh++;return true;
    });
    if(c.operation==='clear_sold')wrap(item,'requestTransferItems',original=>function(...args){
      let role;
      if(root() && !primary){if(clearBefore || args.length)throw Error('invalid_preconditions');clearBefore++;role='clear_before';}
      else if(parent('primary')){if(clearAfter || args.length)throw Error('invalid_preconditions');clearAfter++;role='clear_after';}
      if(!role)return original.apply(this,args);
      if(!live())throw Error('invalid_preconditions');
      return within({role,callback:false},()=>observable(original.apply(this,args),role));
    });
    inventory.delivery={
      sending:()=>current!==null,
      open:m=>{
        if(!current || ++current.opens!==1 || !m || m.background)throw Error('ambiguous_network');
        const role=current.role,primaryRoute=role==='primary' && m.method===routes[c.operation][0] && m.path===routes[c.operation][1];
        const auxiliary=m.method==='GET' && (role==='metadata' && m.path===metadataPath ||
          role==='list_refresh' && m.path===routes.status[1] ||
          ['clear_before','clear_after'].includes(role) && m.path===routes.transfer_list[1]);
        if(!primaryRoute && !auxiliary)throw Error('ambiguous_network');
      }
    };
    wrap(queue,'send',original=>function(request,...args){
      if(scope?.role==='root')throw Error('invalid_preconditions');
      if(!scope || scope.callback)return original.call(this,request,...args);
      if(!live() || typeof request?.send!=='function')throw Error('invalid_preconditions');
      const token={role:scope.role,sent:false,opens:0};
      if(token.role==='primary' && ++primary!==1)throw Error('ambiguous_network');
      request.doRetry=false;request.doReauth=false;requests.push({request,token});
      wrap(request,'send',send=>function(...more){
        if(!live() || token.sent)throw Error('invalid_preconditions');
        token.sent=true;const previous=current;current=token;
        try{return send.apply(this,more);}finally{current=previous;}
      });
      return original.call(this,request,...args);
    });
    const verify=()=>{if(primary!==1 || requests.some(({token})=>!token.sent || token.opens!==1))throw Error('ambiguous_network');};
    return {observable:within({role:'root',callback:false},invoke),finish,verify};}
    catch(e){finish(false);throw e;}
  }
  async function execute(c,controllerRead=false) {
    diagnostic(c?.id,'PAGE_ENTER');
    const out={schema:2,command_id:hex(c?.id)?c.id:'0'.repeat(32),operation:operation(c?.operation)?c.operation:null,
      context:binding?{...binding.context}:null,fences:binding?{...binding.fences}:null,result:empty('invalid_command'),
      freshness:{observed_at:new Date().toISOString(),network_at:null,request_count:0,read_id:hex(c?.id)?c.id:'0'.repeat(32),source:'native'},
      coverage:{complete:false,has_more:null},timing:{native_service_ms:0,ea_rtt_ms:0,native_helper_ms:0}};
    if(c?.operation==='price_helpers')out.result={success:false,error:'invalid_command',version:1,above_available:false,below_available:false,probes:[],network:[]};
    if(c?.operation==='status_support')out.result={success:false,error:'invalid_command',function_available:false,retained_count:0,bid_receipt_schema:1,network:[]};
    if(controllerRead && !['search','watched','transfer_list','caps','price_helpers','owned_item','unassigned','move','list','clear_sold','relist_all'].includes(c?.operation))return out;
    if(!valid(c))return out;
    if(!official()){out.result.error='wrong_page';return out;}
    if(busy || poisoned || window.__fcNativeCommandOwner!==document){out.result.error='bridge_busy';return out;}
    busy=true;let restore=()=>{},restoreBid=()=>{},finishRead=()=>{},verifyRead=()=>{},bidState=null;const start=performance.now(),p=c.params,op=c.operation,r=out.result;
    if(op==='bid')r.bid_receipt=bidReceipt();
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
      let invoke,listRaw=null;
      if(op==='search'){
        const q=new UTSearchCriteriaDTO();q.type='player';if(p.definition_id!==undefined)q.defId=[p.definition_id];q.count=21;
        diagnostic(c.id,'NATIVE_DATA',{definition_type:fieldType(q.defId),definition_count:Array.isArray(q.defId)?q.defId.length:undefined});
        for(const [k,v] of Object.entries({max_bid:'maxBid',min_buy:'minBuy',max_buy:'maxBuy'}))if(p[k]!==undefined)q[v]=p[k];
        if(typeof services.Item.clearTransferMarketCache!=='function')throw Error('service_unavailable');
        services.Item.clearTransferMarketCache();r.cache_invalidated=true;invoke=()=>services.Item.searchTransferMarket(q,p.page);
      }else if(['watched','unassigned','transfer_list'].includes(op)){
        const [pile,method]={watched:[ItemPile.INBOX,'requestWatchedItems'],unassigned:[ItemPile.PURCHASED,'requestUnassignedItems'],transfer_list:[ItemPile.TRANSFER,'requestTransferItems']}[op];
        if(pile===undefined || typeof repositories?.Item?.setDirty!=='function' || typeof services.Item?.[method]!=='function')throw Error('service_unavailable');
        repositories.Item.setDirty(pile);r.cache_invalidated=true;invoke=()=>services.Item[method]();
      }else if(op==='balance')invoke=()=>services.User.requestCurrencies();
      else if(op==='owned_item'){
        const e=known.get(p.trade_id);
        const terminal=e?.controller_status?.row??e?.row,terminalAt=e?.controller_status?.at??e?.at;
        if(!e || e.row.item.item_id!==p.item_id || e.row.item.definition_id!==p.definition_id ||
           terminal.trade_state!=='closed' || terminal.bid_state!=='highest' || terminal.expires>0 ||
           terminal.native_is_won!==true || Date.now()-Date.parse(terminalAt)<0 || Date.now()-Date.parse(terminalAt)>30000 ||
           typeof services.Item.requestItemsById!=='function')throw Error('known_identity_unavailable');
        invoke=()=>services.Item.requestItemsById([String(e.raw.id)]);
      }
      else if(op==='status'){
        if(!statusAvailable())throw Error('service_unavailable');
        const e=known.get(p.trade_id)??statusSelectors.get(p.trade_id);
        const identity=e?.row?.item??e?.identity;
        if(!e || identity.item_id!==p.item_id || identity.definition_id!==p.definition_id)throw Error('known_identity_unavailable');
        // Native DAO consumes only tradeId/isValid and sets local isUpdating.
        // This descriptor is a request selector, never an observed auction state.
        const query={tradeId:e.native_trade_id,isValid:()=>true,isUpdating:false};
        invoke=()=>services.Item.transfersDao.getAuctionData([{getAuctionData:()=>query}]);
      }
      else if(op==='caps'){
        if(typeof services.Item?.transfersDao?.getItemMarketDataByDefId!=='function')throw Error('service_unavailable');
        invoke=()=>services.Item.transfersDao.getItemMarketDataByDefId([p.definition_id]);
      }
      else if(bulk(op)){
        const s=reads.get(p.before_read_id),age=s?Date.now()-Date.parse(s.at):-1;
        const same=(a,b)=>JSON.stringify([...a].sort())===JSON.stringify([...b].sort());
        if(!s || s.operation!=='transfer_list' || !s.complete || age<0 || age>30000 || !s.bulk ||
            sent.has(c.id) || sent.has('bulk:'+p.before_read_id))throw Error('invalid_preconditions');
        const ids=s.rows.map(r=>r.item.item_id),sold=[],expired=[],current=[];
        for(let i=0;i<s.rows.length;i++){
          const r=s.rows[i],n=s.bulk[i],e=physical.get(r.item.item_id),a=e?.raw.getAuctionData?.();
          const itemId=e?.raw.id,tradeId=a?.tradeId;
          const isSold=r.trade_state==='closed' && r.current_bid>0 && r.expires<=0;
          const isExpired=r.trade_state==='expired' && r.current_bid===0 && r.expires===-1;
          const isActive=r.trade_state==='active' && r.expires>0;
          if(!n.trade_owner || r.bid_state!=='none' || [isSold,isExpired,isActive].filter(Boolean).length!==1 ||
              n.sold!==isSold || n.expired!==isExpired || n.active!==isActive || !a || e.read_id!==p.before_read_id ||
              a.tradeOwner!==true || a.isSold?.()!==isSold || a.isExpired?.()!==isExpired || a.isActiveTrade?.()!==isActive ||
              a.startingBid!==r.starting_bid || a.buyNowPrice!==r.buy_now_price || a.currentBid!==r.current_bid ||
              a.tradeState!==r.trade_state || a.bidState!==r.bid_state ||
              await id(itemId,'item',c.context.identity_namespace)!==r.item.item_id ||
              e.raw.definitionId!==r.item.definition_id || await id(tradeId,'trade',c.context.identity_namespace)!==r.trade_id)
            throw Error('invalid_preconditions');
          if(isSold)sold.push(r.item.item_id);if(isExpired)expired.push(r.item.item_id);
          current.push({r,raw:e.raw,itemId,tradeId,n});
        }
        const targets=op==='clear_sold'?sold:expired;
        if(!same(ids,p.expected_inventory_ids) || !same(targets,p.expected_item_ids) ||
            sold.length!==p.expected_sold_count || expired.length!==p.expected_expired_count ||
            op==='relist_all' && sold.length)throw Error('invalid_preconditions');
        // Recheck the repository set while holding the same native owner.
        const repo=repositories.Item.getTransferItems?.();
        if(repositories.Item.transfer?.endOfList!==true || !Array.isArray(repo) || repo.length!==s.rows.length ||
            Date.now()-Date.parse(s.at)<0 || Date.now()-Date.parse(s.at)>30000 || current.some(({r,raw,itemId,tradeId,n})=>{
              const a=raw.getAuctionData?.();
              return !repo.includes(raw) || raw.id!==itemId || raw.definitionId!==r.item.definition_id || !a ||
                a.tradeId!==tradeId || a.startingBid!==r.starting_bid || a.buyNowPrice!==r.buy_now_price ||
                a.currentBid!==r.current_bid || a.tradeState!==r.trade_state || a.bidState!==r.bid_state ||
                a.tradeOwner!==true || a.isSold?.()!==n.sold || a.isExpired?.()!==n.expired || a.isActiveTrade?.()!==n.active;
            }))throw Error('invalid_preconditions');
        const method=op==='clear_sold'?'clearSoldItems':'relistExpiredAuctions';
        if(typeof services.Item[method]!=='function')throw Error('service_unavailable');
        sent.add(c.id);sent.add('bulk:'+p.before_read_id);reads.delete(p.before_read_id);
        // Proven zero-argument native service; duration is verified only on readback.
        invoke=()=>services.Item[method]();
      }
      else if(['move','list'].includes(op)){
        const e=physical.get(p.item_id),caps=reads.get(p.caps_read_id),owned=reads.get(p.owned_read_id);
        const age=at=>at!==null && Date.now()-Date.parse(at)>=0 && Date.now()-Date.parse(at)<=30000;
        if(!e || e.read_id!==p.owned_read_id || !owned || !age(e.at) || !caps || caps.operation!=='caps' || !age(caps.at) ||
          caps.caps?.definition_id!==p.definition_id || e.item.definition_id!==p.definition_id || e.item.untradeable!==false ||
          e.item.last_sale_price!==p.paid || sent.has(c.id) || sent.has(op+':'+p.item_id) ||
          p.starting_bid<caps.caps.minimum || p.buy_now_price>caps.caps.maximum ||
          helper('below',p.buy_now_price)!==p.starting_bid || helper('above',p.starting_bid)!==p.buy_now_price ||
          helper('above',helper('below',p.starting_bid))!==p.starting_bid)throw Error('invalid_preconditions');
        if(op==='move'){
          const win=known.get(p.trade_id),s=reads.get(p.win_read_id);
          if(!['unassigned','owned_item'].includes(e.operation) || !win || win.read_id!==p.win_read_id || !s || s.operation!=='watched' || !age(win.at) ||
            win.row.item.item_id!==p.item_id || win.row.item.definition_id!==p.definition_id || win.row.current_bid!==p.paid ||
            win.row.trade_state!=='closed' || win.row.bid_state!=='highest' || win.row.expires>0 || win.row.native_is_won===false ||
            typeof services.Item.move!=='function' || ItemPile.TRANSFER===undefined)throw Error('invalid_preconditions');
          invoke=()=>services.Item.move([e.raw],ItemPile.TRANSFER,false);
        }else{
          if(e.operation!=='transfer_list' || owned.complete!==true || e.row.trade_state!=='inactive' || e.row.current_bid!==0 ||
            typeof services.Item.list!=='function')throw Error('invalid_preconditions');
          invoke=()=>services.Item.list(e.raw,p.starting_bid,p.buy_now_price,p.duration);
        }
        if(op==='list')listRaw=e.raw;
        sent.add(c.id);sent.add(op+':'+p.item_id);physical.delete(p.item_id);
      }
      else {
        const e=known.get(p.trade_id),b=reads.get(p.balance_read_id),s=reads.get(p.status_read_id);
        const age=at=>at!==null && Date.now()-Date.parse(at)>=0 && Date.now()-Date.parse(at)<=30000;
        if(!e || e.read_id!==p.status_read_id || !s || !['search','watched'].includes(s.operation) || !age(e.at) || !b || b.operation!=='balance' || !age(b.at) || b.credits<p.amount ||
          e.row.item.item_id!==p.item_id || e.row.item.definition_id!==p.definition_id || e.row.item.untradeable!==false ||
          e.row.trade_state!=='active' || !['none','outbid'].includes(e.row.bid_state) || e.row.expires<=0 ||
          Date.now()>=Date.parse(e.at)+e.row.expires*1000 || Date.parse(p.deadline)>Date.parse(e.at)+e.row.expires*1000 ||
          p.amount>=e.row.buy_now_price || sent.has(c.id) || sent.has('bid_read:'+p.status_read_id))throw Error('invalid_preconditions');
        const base=e.row.current_bid===0?e.row.starting_bid:e.row.current_bid;
        if(base<=0 || helper('above',helper('below',base))!==base)throw Error('helper_disagreement');
        const minimum=e.row.current_bid===0?base:helper('above',base);
        if(num(minimum)===null || p.amount!==minimum)throw Error('invalid_preconditions');
        // Consume this exact observation, not the trade for its entire lifetime.
        // A later outbid native read permits a new minimum-bid intent. Duplicate
        // commands/reads remain blocked; ambiguous writes still poison the page.
        // Recheck the mutable native DTO against the independently retained row.
        const current=await auction(e.raw,c,null),nativeTrade=String(e.raw.getAuctionData?.()?.tradeId);
        if(!equal(current.item,e.row.item) || current.trade_id!==p.trade_id ||
            ['starting_bid','current_bid','buy_now_price','trade_state','bid_state'].some(k=>current[k]!==e.row[k]) ||
            current.expires<=0 || nativeTrade!==e.native_trade_id)throw Error('invalid_preconditions');
        r.bid_receipt.before_bid_state=e.row.bid_state;
        bidState={raw:e.raw,before:e.row,nativeTrade,invocations:0,native:null,receipt:r.bid_receipt};
        restoreBid=captureBid(e.raw,p.amount,bidState);
        sent.add(c.id);sent.add('bid_read:'+p.status_read_id);known.delete(p.trade_id);invoke=()=>services.Item.bid(e.raw,p.amount);
      }
      const inventory={wire:null,truncated:false,listRaw,bid:bidState,controllerRead};
      restore=capture(r.network,c,out.timing,inventory);const at=new Date().toISOString();
      if(bulk(op) && (!valid(c) || services.User.getUser?.()!==nativeUser || selected()!==nativePersona ||
          window.__fcNativeCommandOwner!==document || window.__fcDiscoveryPersonaFollowupV1?.selectedPlatform()!=='pc'))throw Error('persona_unverified');
      diagnostic(c.id,'NATIVE_INVOKE');
      let observable;
      if(controllerRead){const delivery=controllerReadInvocation(invoke,c,inventory);observable=delivery.observable;finishRead=delivery.finish;verifyRead=delivery.verify;}
      else observable=invoke();
      const response=await observe(observable,c.id,!controllerRead);await new Promise(resolve=>setTimeout(resolve,0));
      verifyRead();
      r.status=Number.isInteger(response?.status) && response.status>=100 && response.status<=599?response.status:null;
      if(op==='bid'){
        await finishBid(bidState,c);
        if(r.bid_receipt.verdict==='REJECTED')throw Error('bid_rejected');
        if(r.bid_receipt.verdict!=='ACCEPTED')throw Error('bid_unconfirmed');
      }
      if(bulk(op) && inventory.bulkViolation)throw Error('bulk_contract_changed');
      if(response?.success!==true)throw Error('service_failed');
      // A special-version search can fetch attributes before its observable completes.
      // Keep every observation and require exactly one intended request, plus at most
      // one narrowly reviewed read-only metadata request. Never ignore unknown traffic.
      const targets=r.network.filter(n=>n.method===routes[op][0] && n.path===routes[op][1]);
      const auxiliary=r.network.filter(n=>n.method==='GET' &&
        (n.path===metadataPath && op==='search' || n.path===routes.transfer_list[1] && op==='clear_sold' ||
         n.path===routes.status[1] && op==='list' && equal(n.query,{item_id:p.item_id})));
      if(targets.length!==1 || auxiliary.length>(op==='clear_sold'?2:1) || targets.length+auxiliary.length!==r.network.length)throw Error(bulk(op)?'bulk_contract_changed':'ambiguous_network');
      const n=targets;
      if(bulk(op) && r.network.some(x=>!x.session_header_present || x.status!==200 || x.host!==n[0].host))throw Error('bulk_contract_changed');
      if(r.network.some(x=>!x.session_header_present || !(x.status>=200 && x.status<300)))throw Error('unauthenticated');
      if(auxiliary.some(x=>x.host!==n[0].host))throw Error('ambiguous_network');
      if(n[0].status!==r.status)throw Error('schema_unrecognized');
      if(op==='search'){
        // FC27 requests 21 rows as a lookahead, but advances 20 rows per page.
        // The overlapping row is deduplicated by the discovery actor.
        const q=n[0].query,expected={start:(p.page-1)*20,num:21};
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
      if(op==='owned_item' && !equal(n[0].query,{item_id:p.item_id}))throw Error('schema_unrecognized');
      if(Date.now()<Date.parse(at) || Date.now()-Date.parse(at)>30000)throw Error('stale_source');
      out.freshness.network_at=at;
      if(services.User.getUser?.()!==nativeUser || selected()!==nativePersona)throw Error('persona_unverified');
      const data=response.data??response.response;
      diagnostic(c.id,'NATIVE_DATA',{data_type:fieldType(data),row_count:Array.isArray(data?.items)?data.items.length:undefined});
      if(['search','watched','transfer_list','unassigned','owned_item','status'].includes(op)){
        // The native status observable exposes items, not the raw HTTP envelope.
        const rows=op==='status'?data?.items:data?.items??data?.auctionInfo??data?.itemData;
        if(!Array.isArray(rows)||rows.length>(op==='search'?21:100))throw Error('schema_unrecognized');
        if(['unassigned','owned_item'].includes(op))r.items=await Promise.all(rows.map(raw=>item(raw,c.context.identity_namespace,false,c.id)));
        else r.auctions=await Promise.all(rows.map(raw=>auction(raw,c,at)));
        if(op==='search' && p.definition_id!==undefined && r.auctions.some(a=>a.item.definition_id!==p.definition_id))throw Error('schema_unrecognized');
        if(op==='owned_item' && (r.items.length>1 || r.items.some(i=>i.item_id!==p.item_id || i.definition_id!==p.definition_id)))throw Error('schema_unrecognized');
        if(auxiliary.some(x=>!keys(x.query,'defIds') || !x.query.defIds?.length ||
            x.query.defIds.some(d=>!r.auctions.some(a=>a.item.definition_id===d))))throw Error('schema_unrecognized');
        if(op==='status' && (r.auctions.length>1 || r.auctions.some(a=>a.trade_id!==p.trade_id || a.item.item_id!==p.item_id ||
          a.item.definition_id && a.item.definition_id!==p.definition_id)))throw Error('schema_unrecognized');
        const identities=(r.auctions??r.items).map(x=>op==='transfer_list'?x.item.item_id:x.trade_id??x.item_id);
        if(new Set(identities).size!==identities.length)throw Error(op==='transfer_list'?'transfer_list_conflict':'schema_unrecognized');
        // Commit exact native mappings only after the entire fresh read succeeds.
        if(['search','watched','transfer_list'].includes(op)) {
          const entries=await Promise.all(r.auctions.map(async(row,index)=>{
            const raw=rows[index],a=raw.getAuctionData?.()??raw.auctionData??raw._auction??raw;
            const native_trade_id=String(a.tradeId);
            if(op==='transfer_list' && (native_trade_id==='0' || row.trade_state==='inactive'))return null;
            if(await id(native_trade_id,'trade',c.context.identity_namespace)!==row.trade_id)throw Error('unsafe_identity');
            const retained=known.get(row.trade_id);
            if(retained && (retained.row.item.item_id!==row.item.item_id || retained.row.item.definition_id!==row.item.definition_id))throw Error('schema_unrecognized');
            return [row.trade_id,{raw,row,at,read_id:c.id,native_trade_id}];
          }));
          if(Date.now()<Date.parse(at) || Date.now()-Date.parse(at)>30000)throw Error('stale_source');
          entries.filter(Boolean).forEach(([key,value])=>{
            known.set(key,value);
            // A bid consumes its write observation, but must not erase the
            // exact native selector needed for an independent readback when
            // the explicitly incomplete watched endpoint omits the auction.
            // This map grants no write authority, has no raw DTO/read ID, and
            // is invalidated with every complete fence change.
            statusSelectors.set(key,{native_trade_id:value.native_trade_id,
              identity:{item_id:value.row.item.item_id,definition_id:value.row.item.definition_id}});
          });
        }
        out.coverage.has_more=typeof data.hasMore==='boolean'?data.hasMore:null;
        if(op==='transfer_list'){
          const repository=repositories.Item.getTransferItems?.();
          const endValue=repositories.Item.transfer?.endOfList,end=endValue===true;
          const proof={reason:'TRANSFER_LIST_UNKNOWN',wire_count:inventory.wire?.length??null,
            callback_count:rows.length,repository_count:Array.isArray(repository)?repository.length:null,repository_end_of_list:end};
          // Compare every physical entry and its observed state across all three
          // views. Inactive cards may share the native sentinel trade ID 0.
          const signature=row=>JSON.stringify([row.item.item_id,row.item.definition_id,row.trade_id,
            row.starting_bid,row.current_bid,row.buy_now_price,row.expires,row.trade_state,row.bid_state]);
          const same=(a,b)=>a.length===b.length && new Set(b.map(x=>x.item.item_id)).size===b.length &&
            a.map(signature).sort().join('|')===b.map(signature).sort().join('|');
          if(inventory.truncated || data.hasMore===true || endValue===false)proof.reason='TRANSFER_LIST_TRUNCATED';
          else if(end && inventory.wire && Array.isArray(repository)){
            try{
              const wire=await Promise.all(inventory.wire.map(x=>{
                let data={...x,tradeId:x.tradeIdStr??x.tradeId};
                // A physical Transfer List item without an auction uses the
                // native UTAuctionEntity inactive defaults. Compare those
                // semantics while retaining every explicitly supplied value.
                if((data.tradeId==null || String(data.tradeId)==='0') &&
                   (data.tradeState==null || data.tradeState==='inactive')){
                  const defaults={tradeId:'0',tradeState:'inactive',bidState:'none',startingBid:0,
                    currentBid:0,buyNowPrice:0,expires:-1};
                  for(const [key,value] of Object.entries(defaults))if(data[key]==null)data[key]=value;
                }
                return auction({...x.itemData,definitionId:x.itemData?.resourceId,auctionData:data},c,at);
              }));
              const repo=await Promise.all(repository.map(x=>auction(x,c,at)));
              proof.reason=same(r.auctions,wire)&&same(r.auctions,repo)?'TRANSFER_LIST_COMPLETE':'TRANSFER_LIST_CONFLICT';
            }catch{proof.reason='TRANSFER_LIST_CONFLICT';}
          }
          out.coverage.transfer_list=proof;
          out.coverage.complete=proof.reason==='TRANSFER_LIST_COMPLETE';
          if(out.coverage.complete)out.coverage.has_more=false;
          // Optional proof used exclusively by the production bulk adapter.
          // Missing predicates/ownership leave ordinary inventory usable but
          // cannot authorize bulk writes.
          if(out.coverage.complete && rows.every(raw=>{
            const a=raw.getAuctionData?.();return typeof a?.tradeOwner==='boolean' &&
              ['isSold','isExpired','isActiveTrade'].every(k=>typeof a[k]==='function');
          }) && rows.every(raw=>{
            const w=inventory.wire.find(w=>String(w.itemData?.id)===String(raw.id));
            return typeof w?.tradeOwner==='boolean' && w.tradeOwner===raw.getAuctionData().tradeOwner;
          }))out.coverage.bulk=rows.map((raw,i)=>{
            const a=raw.getAuctionData();return {item_id:r.auctions[i].item.item_id,trade_owner:a.tradeOwner,
              sold:a.isSold(),expired:a.isExpired(),active:a.isActiveTrade()};
          });
        }
        if(['unassigned','owned_item','transfer_list'].includes(op)){
          const projected=op==='transfer_list'?r.auctions.map(x=>x.item):r.items;
          projected.forEach((i,index)=>physical.set(i.item_id,{raw:rows[index],item:i,row:op==='transfer_list'?r.auctions[index]:null,
            at,read_id:c.id,operation:op}));
        }
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
      r.success=true;r.error=null;reads.set(c.id,{operation:op,at,credits:r.credits,caps:r.caps,complete:out.coverage.complete,
        rows:['transfer_list','search','watched'].includes(op)?r.auctions:null,bulk:out.coverage.bulk,fences:{...c.fences}});
    }catch(e){
      if(op==='bid' && r.bid_receipt?.verdict==='ACCEPTED'){
        r.bid_receipt.verdict='UNCONFIRMED';r.bid_receipt.reason='ENVELOPE_VALIDATION_FAILED';
      }
      r.success=false;r.error=['bid_rejected','bid_unconfirmed','bulk_contract_changed','transfer_list_conflict','known_identity_unavailable','helpers_unavailable','helper_disagreement','service_unavailable','service_timeout','service_failed','schema_unrecognized','unsafe_identity','persona_unverified','invalid_preconditions','unauthenticated','ambiguous_network','stale_source'].includes(e?.message)?e.message:'internal_error';
      if(r.error==='transfer_list_conflict')r.auctions=null;
      diagnostic(c.id,'PAGE_FAILURE',{error:r.error,error_class:e?.name});
      if(!controllerRead && !bulk(op) && r.error!=='bid_rejected' && (['bid','move','list'].includes(op) || ['service_timeout','ambiguous_network'].includes(r.error)))poisoned=true;
    }finally{
      finishRead(r.success);restoreBid();restore();busy=false;out.freshness.observed_at=new Date().toISOString();out.freshness.request_count=r.network.length;out.timing.native_service_ms=performance.now()-start;
      diagnostic(c.id,'PAGE_FINISHED',{success:r.success,error:r.error,request_count:r.network.length});
    }
    return out;
  }
  const controller=window.__fcControllerFactoryV1?.({keys,hex,num,equal,id,auction,known,reads,helper,bidReceipt,captureBid,finishBid,diagnostic,
    scope:(context,fences)=>!!binding && equal(context,binding.context) && equal(fences,binding.fences),
    acquire:()=>{if(busy || poisoned || !official() || window.__fcNativeCommandOwner!==document)return false;busy=true;return true;},
    release:()=>{busy=false;},
    // Account labels are bound by explicit operator selection in attach. A PC
    // persona display name is not an EA saved-sign-in identifier. Never infer
    // account identity by reading login fields or by comparing these aliases.
    auth:()=>{if(services.User.getUser?.()!==nativeUser || selected()!==nativePersona || window.__fcDiscoveryPersonaFollowupV1?.selectedPlatform()!=='pc')throw Error('persona_unverified');}});
  Object.defineProperty(window,'__fcProductionV1',{value:Object.freeze({attach,execute,document,
    executeReadController:c=>execute(c,true),
    executeController:controller?.execute,interruptController:controller?.interrupt})});
})();

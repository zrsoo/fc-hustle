/* Finite research commands. The default production server rejects this dialect. */
(() => {
  'use strict';
  if(window.__fcBulkTransferV1)return;
  let binding=null,user=null,persona=null,busy=false,snapshot=null;
  const sent=new Set(),consumed=new Set();
  const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  const integer=n=>Number.isSafeInteger(n)&&n>=0;
  const selected=()=>services.User.getUser()?.getSelectedPersona?.();
  const safeId=v=>typeof v==='string'&&/^\d{1,24}$/.test(v)||integer(v);
  async function id(v,namespace,key){
    if(!safeId(v))throw Error('unsafe_identity');
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(`${key}|${namespace}|${v}`));
    return namespace+':'+[...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('').slice(0,24);
  }
  async function project(raw,c,wire=false){
    const a=wire?raw:raw.getAuctionData?.()??raw.auctionData??raw._auction??raw;
    const i=wire?raw.itemData:raw;
    const trade=a.tradeIdStr??a.tradeId;
    const row={trade_id:await id(trade,'trade',c.context.identity_namespace),item_id:await id(i.id,'item',c.context.identity_namespace),
      definition_id:wire?i.resourceId:i.definitionId,starting_bid:a.startingBid,current_bid:a.currentBid,
      buy_now_price:a.buyNowPrice,expires:a.expires,trade_state:a.tradeState??null,bid_state:a.bidState??null,
      trade_owner:typeof a.tradeOwner==='boolean'?a.tradeOwner:null};
    for(const k of ['definition_id','starting_bid','current_bid','buy_now_price'])if(!integer(row[k]))throw Error('inventory_schema');
    if(!Number.isSafeInteger(row.expires)||row.expires < -1)throw Error('inventory_schema');
    return row;
  }
  function inspect(){
    const sources=[];
    const add=(owner,obj,names)=>{for(const name of names)if(typeof obj?.[name]==='function')sources.push({owner,name,source:Function.prototype.toString.call(obj[name])});};
    add('services.Item',services.Item,['clearSoldItems','relistExpiredAuctions','requestTransferItems']);
    add('services.Item.transfersDao',services.Item.transfersDao,['removeSold','relistExpiredAuctions','getTransferItems']);
    add('repositories.Item',repositories.Item,['getTransferItems','setTransferItems','getPileSize']);
    add('UTTransferListViewController.prototype',globalThis.UTTransferListViewController?.prototype,['_clearSold','_relistAll']);
    add('UTTransferSectionListViewModel.prototype',globalThis.UTTransferSectionListViewModel?.prototype,['getSoldItems','getUnsoldItems','getActiveItems']);
    const first=repositories.Item.getTransferItems?.()[0]?.getAuctionData?.();
    add('loaded transfer AuctionData',first,['isSold','isExpired','isInactive','isValid','isActiveTrade']);
    const names=[];
    for(let obj=services.Item,depth=0;obj&&depth<3;obj=Object.getPrototypeOf(obj),depth++)
      for(const name of Object.getOwnPropertyNames(obj))if(/sold|relist/i.test(name)&&!names.includes(name))names.push(name);
    return {sources,names};
  }
  function observe(observable){
    if(typeof observable?.observe!=='function')throw Error('service_unavailable');
    return new Promise((resolve,reject)=>{const owner={};let done=false;
      const timer=setTimeout(()=>{if(!done){done=true;observable.unobserve?.(owner);reject(Error('native_timeout_no_retry'));}},18000);
      try{observable.observe(owner,(sender,response)=>{if(!done){done=true;clearTimeout(timer);sender?.unobserve?.(owner);resolve(response);}});}
      catch(e){done=true;clearTimeout(timer);observable.unobserve?.(owner);reject(e);}
    });
  }
  function capture(c,network,pending){
    const proto=XMLHttpRequest.prototype,original={open:proto.open,send:proto.send,header:proto.setRequestHeader};
    const requests=new WeakMap();
    const open=function(method,url,...args){
      const u=new URL(url,location.href);
      if(u.pathname.startsWith('/ut/game/fc27/')){
        const allowedHost=u.protocol==='https:'&&/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname);
        const allowedPath=['/ut/game/fc27/tradepile','/ut/game/fc27/trade/sold','/ut/game/fc27/auctionhouse/relist'].includes(u.pathname);
        requests.set(this,{host:allowedHost?u.hostname:'unexpected',method:['GET','DELETE','PUT'].includes(method)?method:'OTHER',
          path:allowedPath?u.pathname:'/unexpected',query_empty:u.search==='',request_body:null,body_kind:'empty',
          status:null,session_header_present:false,started_at:null,response:null});
      }
      return original.open.call(this,method,url,...args);
    };
    const header=function(name,value){const n=requests.get(this);if(n&&String(name).toLowerCase()==='x-ut-sid')n.session_header_present=true;return original.header.call(this,name,value);};
    const send=function(body){const n=requests.get(this);if(n){
      n.body_kind=body==null||body===''?'empty':'unexpected';
      const allowed=n.host!=='unexpected'&&n.path!=='/unexpected'&&n.query_empty&&n.body_kind==='empty'&&
        (n.method==='GET'&&n.path==='/ut/game/fc27/tradepile'||c.operation==='bulk_clear_sold'&&n.method==='DELETE'&&n.path==='/ut/game/fc27/trade/sold'||
         c.operation==='bulk_relist_all'&&n.method==='PUT'&&n.path==='/ut/game/fc27/auctionhouse/relist');
      if(!allowed)throw Error('wire_contract_mismatch');
      if(n.method!=='GET'&&network.some(previous=>previous.method!=='GET'))throw Error('duplicate_native_mutation_blocked');
      n.started_at=new Date().toISOString();network.push(n);
      this.addEventListener('loadend',()=>{
        n.status=this.status;n.ended_at=new Date().toISOString();
        pending.push((async()=>{
          let data=null;
          try{const text=this.responseType==='arraybuffer'?new TextDecoder().decode(this.response):
              this.responseType==='json'?JSON.stringify(this.response):this.responseText;
            if(text)data=JSON.parse(text);
          }catch{n.response={kind:'unparsed'};return;}
          if(data===null){n.response={kind:'empty'};return;}
          const keys=Object.keys(data),known=['auctionInfo','tradeIdList','credits','dynamicObjectivesUpdates','errorCode','code'];
          n.response={kind:'json',keys:keys.filter(k=>known.includes(k)),other_key_count:keys.filter(k=>!known.includes(k)).length};
          if(Array.isArray(data.auctionInfo))n.response.auctions=await Promise.all(data.auctionInfo.map(row=>project(row,c,true)));
          if(Array.isArray(data.tradeIdList))n.response.trade_ids=await Promise.all(data.tradeIdList.map(row=>id(row.idStr??row.id,'trade',c.context.identity_namespace)));
          for(const k of ['credits','errorCode','code'])if(integer(data[k]))n.response[k]=data[k];
        })());
      },{once:true});
    }return original.send.call(this,body);};
    proto.open=open;proto.send=send;proto.setRequestHeader=header;
    return ()=>{if(proto.open===open)proto.open=original.open;if(proto.send===send)proto.send=original.send;if(proto.setRequestHeader===header)proto.setRequestHeader=original.header;};
  }
  async function execute(c){
    const out={schema:2,command_id:c.id,operation:c.operation,context:c.context,fences:c.fences,
      observed_at:new Date().toISOString(),success:false,error:null,status:null,network:[],sources:[],inventory:null,callback:null};
    let restore=()=>{},acquired=false;const pending=[];
    try{
      const p=window.__fcProductionV1;
      if(!p||p.document!==c.fences.document||window.__fcNativeCommandOwner!==p.document||!p.attach(c.context,c.fences))throw Error('production_binding_required');
      if(busy)throw Error('single_native_owner_busy');
      if(!binding||!equal(binding,c.fences)){binding={...c.fences};user=services.User.getUser();persona=selected();snapshot=null;}
      if(services.User.getUser()!==user||selected()!==persona||window.__fcDiscoveryPersonaFollowupV1?.selectedPlatform()!=='pc')throw Error('persona_unverified');
      if(sent.has(c.id))throw Error('duplicate_command');
      busy=true;acquired=true;sent.add(c.id);
      if(c.operation==='bulk_inspect'){
        const inspected=inspect();out.sources=inspected.sources;out.names=inspected.names;out.success=true;return out;
      }
      restore=capture(c,out.network,pending);
      if(c.operation==='bulk_inventory'){
        repositories.Item.setDirty(ItemPile.TRANSFER);
        const response=await observe(services.Item.requestTransferItems());
        out.status=response.status;
        if(response.success!==true)throw Error('native_read_failed');
        const data=response.data??response.response;
        if(!Array.isArray(data?.items))throw Error('inventory_schema');
        const rows=await Promise.all(data.items.map(row=>project(row,c)));
        await new Promise(resolve=>setTimeout(resolve,0));await Promise.all(pending);
        if(out.network.length!==1||out.network[0].method!=='GET'||out.network[0].status!==200||!out.network[0].session_header_present)throw Error('fresh_authenticated_GET_required');
        const wire=out.network[0].response?.auctions;
        if(!wire||rows.length!==wire.length||new Set(rows.map(r=>r.item_id)).size!==rows.length||
          rows.some(r=>!wire.some(w=>w.item_id===r.item_id&&w.trade_id===r.trade_id&&w.starting_bid===r.starting_bid&&w.buy_now_price===r.buy_now_price&&w.trade_state===r.trade_state)))throw Error('complete_wire_inventory_required');
        const capacity=repositories.Item.getPileSize(ItemPile.TRANSFER);
        const native_counts={sold:0,expired:0,active:0};
        for(const raw of data.items){const a=raw.getAuctionData();
          if(!['isSold','isExpired','isActiveTrade'].every(k=>typeof a[k]==='function'))throw Error('inventory_schema');
          native_counts.sold+=a.isSold()?1:0;native_counts.expired+=a.isExpired()?1:0;native_counts.active+=a.isActiveTrade()?1:0;
        }
        if(repositories.Item.transfer?.endOfList!==true)throw Error('complete_wire_inventory_required');
        out.inventory={rows,occupancy:rows.length,capacity,complete:true,native_counts,repository_end_of_list:true};
        snapshot={read_id:c.id,at:Date.now(),rows};out.success=true;
      }else if(['bulk_clear_sold','bulk_relist_all'].includes(c.operation)){
        const p=c.params;
        if(!snapshot||snapshot.read_id!==p.before_read_id||Date.now()-snapshot.at>30000||consumed.has(c.operation))throw Error('fresh_authorized_snapshot_required');
        const sold=snapshot.rows.filter(r=>r.trade_owner===true&&r.trade_state==='closed'&&r.current_bid>0&&r.expires<=0);
        const expired=snapshot.rows.filter(r=>r.trade_owner===true&&r.trade_state==='expired'&&r.current_bid===0&&r.expires<=0);
        const targets=c.operation==='bulk_clear_sold'?sold:expired;
        if(!equal(targets.map(r=>r.item_id).sort(),[...p.expected_item_ids].sort())||
          !equal(snapshot.rows.map(r=>r.item_id).sort(),[...p.expected_inventory_ids].sort())||
          p.expected_sold_count!==sold.length||p.expected_expired_count!==expired.length||
          c.operation==='bulk_relist_all'&&(p.duration_seconds!==3600||sold.length!==0))throw Error('eligible_state_changed');
        const method=c.operation==='bulk_clear_sold'?'clearSoldItems':'relistExpiredAuctions';
        if(typeof services.Item[method]!=='function')throw Error('service_unavailable');
        consumed.add(c.operation);snapshot=null;
        // Exactly one zero-argument native bulk service invocation. No per-item loop.
        const response=await observe(services.Item[method]());
        out.status=response.status;
        out.callback={success:response.success===true,status:Number.isInteger(response.status)?response.status:null,
          error_code:integer(response.error?.code)?response.error.code:null,item_ids:[]};
        if(Array.isArray(response.data?.itemIds))out.callback.item_ids=await Promise.all(response.data.itemIds.map(v=>id(v,'item',c.context.identity_namespace)));
        await new Promise(resolve=>setTimeout(resolve,0));await Promise.all(pending);
        const writes=out.network.filter(n=>n.method!=='GET');
        const expected=c.operation==='bulk_clear_sold'?['DELETE','/ut/game/fc27/trade/sold']:['PUT','/ut/game/fc27/auctionhouse/relist'];
        if(writes.length!==1||writes[0].method!==expected[0]||writes[0].path!==expected[1]||
          writes[0].status!==200||!writes[0].session_header_present)throw Error('ambiguous_mutation_no_retry');
        if(response.success!==true)throw Error('native_mutation_failed_no_retry');
        out.success=true;
      }else throw Error('unsupported_operation');
    }catch(e){out.error=['production_binding_required','single_native_owner_busy','persona_unverified','duplicate_command','wire_contract_mismatch','duplicate_native_mutation_blocked','service_unavailable','native_timeout_no_retry','native_read_failed','inventory_schema','fresh_authenticated_GET_required','complete_wire_inventory_required','unsafe_identity','fresh_authorized_snapshot_required','eligible_state_changed','ambiguous_mutation_no_retry','native_mutation_failed_no_retry','unsupported_operation'].includes(e?.message)?e.message:'internal_error';}
    finally{restore();if(acquired)busy=false;out.observed_at=new Date().toISOString();}
    return out;
  }
  Object.defineProperty(window,'__fcBulkTransferV1',{value:Object.freeze({execute})});
})();

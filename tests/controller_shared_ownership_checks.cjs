'use strict';
// Full shared seam, native request objects, metadata and captured service follow-ups.
const assert=require('node:assert/strict');
const {probe}=require('./audit_controller_bridge_attribution.cjs');
const {setup}=require('./production_page_checks.cjs');
const {fixture:bulk}=require('./production_bulk_checks.cjs');
const {fixture:resale}=require('./resale_native_checks.cjs');
const native=require('./controller_followup_fixture.cjs');
const pricing={purpose:'pricing',definition_id:7654321,page:1,count:21,fresh:true};
function wire(h,path){const x=new h.sandbox.XMLHttpRequest();x.open('GET','https://utas.test.ea.com/ut/game/fc27/'+path);
  x.setRequestHeader('X-UT-SID','CREDENTIAL-CANARY-DO-NOT-RETAIN');x.send();}
function hooks(h){
  const b=h.sandbox,refs=[];
  for(const obj of [b.XMLHttpRequest.prototype,b.services.UTUtasRequestQueue,b.services.Item,b.services.Item.itemDao,
    b.services.Item.transfersDao,b.services.PlayerMetaData]){
    if(obj)for(const key of Object.keys(obj))if(typeof obj[key]==='function')refs.push([obj,key,obj[key]]);
  }
  return ()=>{for(const [obj,key,value]of refs)assert.equal(obj[key],value,'hook not restored: '+key);};
}
async function shared(h,op,params={}){
  const c=h.command(op,params),restore=hooks(h),value=JSON.parse(JSON.stringify(await h.api.executeReadController(c)));
  restore();assert(!JSON.stringify(value).includes('CANARY'));
  return {c,value};
}
function metadataScene(options={}){
  const h=setup(),q=h.enableControllerQueue(),b=h.sandbox,item=b.services.Item;
  let metaCalls=0;
  b.services.PlayerMetaData={updateItemPlayerMeta(rows){
    metaCalls++;assert.equal(rows.length,1);
    return q.request('metadata',notify=>{wire(h,'attributes/metadata?defIds='+(options.wrongWire?999:rows[0].definitionId));notify({success:true,status:200});});
  }};
  item.searchTransferMarket=function(criteria,page){
    const result=q.observable();
    this.itemDao.searchTransferMarket(criteria,page).observe(this,(sender,response)=>{
      sender.unobserve(this);
      if(options.background)wire(h,'watchlist');
      if(options.backgroundQueued)q.request('unrelated',notify=>{wire(h,'watchlist');notify({success:true,status:200});});
      const rows=options.forged?[h.raw()]:response.data.items;
      const meta=b.services.PlayerMetaData.updateItemPlayerMeta(rows);
      if(options.duplicate)b.services.PlayerMetaData.updateItemPlayerMeta(rows);
      meta.observe(this,(sender)=>{sender.unobserve(this);result.notify(response);});
    });
    return result;
  };
  if(options.delayed){
    q.queue.send=function(request){if(request.operation==='search'){
      this.queue.push({request});setTimeout(()=>{this.queue.splice(this.queue.findIndex(r=>r.request===request),1);request.send();},0);
    }else request.send();return request;};
  }
  return {h,q,metaCalls:()=>metaCalls};
}
async function suite(){
  assert.equal(await probe(),0,'all historical adversarial cases must now pass');
  let cases=9;
  // Genuine simple reads must still work. Missing APIs cannot make negative tests green.
  for(const op of ['search','watched','caps','unassigned','transfer_list','owned_item']){
    const h=setup();let params={};
    if(op==='search')params=pricing;
    if(op==='caps')params={definition_id:7654321};
    if(op==='transfer_list'){
      const raw=h.raw(),a=raw.getAuctionData();
      h.setTransferWire({auctionInfo:[{...a,itemData:{id:raw.id,resourceId:raw.definitionId,untradeable:false,lastSalePrice:7700}}]});
      h.sandbox.repositories.Item.getTransferItems=()=>[raw];h.sandbox.repositories.Item.transfer={endOfList:true};
    }
    if(op==='owned_item'){
      h.setAuction({tradeState:'closed',bidState:'highest',expires:0,currentBid:800,isWon:()=>true});
      h.sandbox.services.Item.requestItemsById=ids=>h.response('owned_item',{items:[h.raw()]},{idList:ids});
    }
    const q=h.enableControllerQueue();
    if(op==='owned_item'){
      const {value}=await shared(h,'watched'),r=value.result.auctions[0];
      params={trade_id:r.trade_id,item_id:r.item.item_id,definition_id:r.item.definition_id};
    }
    const {value}=await shared(h,op,params);assert(value.result.success,JSON.stringify(value));
    assert.equal(value.result.network.length,1);for(const r of q.requests)assert.equal(r.count,1);cases++;
  }
  for(const options of [{},{background:true},{backgroundQueued:true},{delayed:true,backgroundQueued:true}]){
    const f=metadataScene(options),{value}=await shared(f.h,'search',pricing);
    assert(value.result.success,JSON.stringify(value));assert.equal(value.result.network.length,2);
    assert.equal(f.metaCalls(),1);
    for(const r of f.q.requests){assert.equal(r.count,1);assert.equal(r.send,r.originalSend);assert.equal(r.observe,r.originalObserve);}
    const unrelated=f.q.requests.find(r=>r.operation==='unrelated');if(unrelated)assert.equal(unrelated.doRetry,undefined);
    cases++;
  }
  for(const options of [{forged:true},{duplicate:true},{wrongWire:true}]){
    const f=metadataScene(options),{value}=await shared(f.h,'search',pricing);
    assert(!value.result.success);assert.equal(f.metaCalls(),options.forged?0:1);
    for(const r of f.q.requests)assert.equal(r.send,r.originalSend);cases++;
  }
  // Both native Clear Sold variants: cached before-read or a genuine pre-read.
  for(const cacheBefore of [false,true]){
    const f=await bulk('clear_sold'),q=native.bulk(f,'clear_sold',{cacheBefore});
    const {value}=await shared(f.h,'clear_sold',f.params);assert(value.result.success,JSON.stringify(value));
    assert.equal(value.result.network.length,cacheBefore?2:3);
    assert.equal(q.requests.filter(r=>r.operation==='clear_sold').length,1);assert.equal(f.calls.length,1);cases++;
  }
  for(const operation of ['move','list','clear_sold','relist_all']){
    let f,q,leaf,method,path,params;
    if(operation==='move' || operation==='list'){
      f=await resale();q=native.resale(f);params=f.params;
      if(operation==='list'){
        assert((await shared(f.h,'move',f.params)).value.result.success);
        const pile=await f.read('transfer_list'),caps=await f.read('caps',{definition_id:7654321});
        const raw=f.h.sandbox.repositories.Item.getTransferItems()[0];raw.pile=f.h.sandbox.ItemPile.TRANSFER;raw.isStack=()=>false;
        params={...params,owned_read_id:pile.c.id,caps_read_id:caps.c.id};
      }
      leaf=f.h.sandbox.services.Item.itemDao;method=operation==='move'?'move':'listItem';path=operation==='move'?'item':'auctionhouse';
    }else{
      f=await bulk(operation);q=native.bulk(f,operation);params=f.params;
      leaf=f.h.sandbox.services.Item.transfersDao;method=operation==='clear_sold'?'removeSold':'relistExpiredAuctions';
      path=operation==='clear_sold'?'trade/sold':'auctionhouse/relist';
    }
    // A native-looking callback and a matching unowned mutation are insufficient.
    leaf[method]=()=>{
      const result=q.observable();
      setTimeout(()=>{
        const x=new f.h.sandbox.XMLHttpRequest();x.open(operation==='clear_sold'?'DELETE':operation==='list'?'POST':'PUT','https://utas.test.ea.com/ut/game/fc27/'+path);
        x.setRequestHeader('X-UT-SID','CREDENTIAL-CANARY-DO-NOT-RETAIN');x.send();
        result.notify({success:true,status:200,response:{auctionIds:['30000000000000000001']}});
      },0);return result;
    };
    const {value}=await shared(f.h,operation,params);assert(!value.result.success,'unowned mutation supplied authority: '+operation);
    assert(!value.result.network.some(n=>n.method!=='GET'),'unowned mutation entered protocol evidence');cases++;
  }
  // A lost pre-clear read must not allow its late callback to dispatch a DELETE.
  // A lost post-clear read must not replay the DELETE already performed once.
  for(const stage of ['before','after']){
    const f=await bulk('clear_sold'),q=native.bulk(f,'clear_sold');let reads=0,pending;
    const unrelated={request:{unowned:true}};q.queue.queue.push(unrelated);
    q.queue.send=function(request){if(request.operation==='transfer_list' && ++reads===(stage==='before'?1:2)){
      pending=request;this.queue.push({request});return request;
    }request.send();return request;};
    const {value}=await shared(f.h,'clear_sold',f.params);
    assert(!value.result.success);assert.equal(value.result.error,'service_timeout');
    assert(pending.aborted);assert(q.queue.queue.includes(unrelated));assert(!q.queue.queue.some(r=>r.request===pending));
    const count=f.calls.length;assert.equal(count,stage==='before'?0:1);
    pending.send();assert.equal(f.calls.length,count,'late native continuation dispatched a mutation');
    const retry=await shared(f.h,'clear_sold',f.params);assert(!retry.value.result.success);assert.equal(f.calls.length,count);
    cases++;
  }
  for(const unexpected of ['move','queue']){
    const h=setup(),q=h.enableControllerQueue(),item=h.sandbox.services.Item;let writes=0;
    item.itemDao.move=()=>{writes++;throw Error('unexpected_native_mutation');};
    item.searchTransferMarket=function(){
      if(unexpected==='move')this.itemDao.move([],3,false);
      else h.sandbox.services.UTUtasRequestQueue.send({send(){writes++;}});
      throw Error('unexpected_native_work_was_not_blocked');
    };
    const {value}=await shared(h,'search',pricing);assert(!value.result.success);assert.equal(writes,0);assert.equal(q.requests.length,0);cases++;
  }
  {
    const f=metadataScene();Object.defineProperty(f.h.sandbox.services.PlayerMetaData,'updateItemPlayerMeta',{
      value:f.h.sandbox.services.PlayerMetaData.updateItemPlayerMeta,writable:false,configurable:true});
    const {value}=await shared(f.h,'search',pricing);assert(!value.result.success);assert.equal(f.q.requests.length,0);cases++;
  }
  console.log('PASS '+cases+' shared ownership cases: all reads, callback interleaving, metadata, cached/fresh native follow-ups, restoration, late withdrawal and no mutation replay');
}
if(require.main===module)suite().catch(e=>{console.error(e);process.exitCode=1;});
module.exports={suite,metadataScene};

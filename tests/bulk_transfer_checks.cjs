'use strict';
// OFFLINE native doubles. No browser, EA traffic, credentials or account writes.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const crypto=require('node:crypto').webcrypto;
const hex=n=>n.toString(16).padStart(32,'0');
const context={account:hex(1),persona:hex(2),identity_namespace:hex(3),game:'fc27',platform:'pc'};
const fences={owner:hex(4),epoch:1,host_epoch:hex(5),worker_epoch:hex(6),document:hex(7)};
function setup(){
  let data=[1,2,3,4,5].map(n=>({id:String(1000+n),definitionId:100+n,a:{tradeId:String(2000+n),
    startingBid:700,currentBid:n<=2?1500:0,buyNowPrice:1500,expires:n<=3?-1:3600,
    tradeState:n<=2?'closed':n===3?'expired':'active',bidState:'none',tradeOwner:true}}));
  const calls={clear:0,relist:0,wire:[]};let dirty=false,mode='ok';
  const native=()=>data.map(x=>({...x,getAuctionData:()=>({...x.a,isSold:()=>x.a.tradeState==='closed'&&x.a.currentBid>0,
    isExpired:()=>x.a.tradeState==='expired',isActiveTrade:()=>x.a.tradeState==='active'})}));
  const wireRows=()=>data.map(x=>({...x.a,tradeIdStr:x.a.tradeId,itemData:{id:x.id,resourceId:x.definitionId}}));
  class XHR{
    constructor(){this.handlers=[];this.status=200;this.responseType='';}
    open(method,url){this.method=method;this.url=url;}
    setRequestHeader(){}
    addEventListener(event,fn){assert.equal(event,'loadend');this.handlers.push(fn);}
    send(body){calls.wire.push({method:this.method,path:new URL(this.url).pathname,body});
      this.responseText=JSON.stringify(this.method==='GET'?{auctionInfo:wireRows()}:this.method==='PUT'?{tradeIdList:data.filter(x=>x.id==='1003').map(x=>({idStr:x.a.tradeId}))}:{});
      for(const f of this.handlers)f();
    }
  }
  function request(method,path){const x=new XHR();x.open(method,'https://utas.test.ea.com/ut/game/fc27/'+path);x.setRequestHeader('X-UT-SID','SYNTHETIC-SECRET-CANARY');x.send(null);}
  const observable=fn=>({observe(owner,cb){fn();if(mode==='timeout')return;cb({unobserve(){}},{success:true,status:200,data:{items:native(),itemIds:[]}});},unobserve(){}});
  const repository={transfer:{endOfList:true},setDirty(pile){assert.equal(pile,2);dirty=true;},getPileSize(){return 100;},getTransferItems:native};
  const persona={},user={getSelectedPersona:()=>persona};
  const item={
    requestTransferItems(){assert(dirty);dirty=false;return observable(()=>request('GET','tradepile'));},
    clearSoldItems(...args){assert.equal(args.length,0);calls.clear++;
      return observable(()=>{request('GET','tradepile');request('DELETE','trade/sold');
        data=data.filter(x=>x.a.tradeState!=='closed');if(mode==='ambiguous')request('DELETE','trade/sold');request('GET','tradepile');});},
    relistExpiredAuctions(...args){assert.equal(args.length,0);calls.relist++;
      return observable(()=>{for(const x of data)if(x.a.tradeState==='expired')Object.assign(x.a,{tradeId:'9999',tradeState:'active',expires:3600});request('PUT','auctionhouse/relist');});},
    transfersDao:{removeSold(){},relistExpiredAuctions(){}}
  };
  const page={document:hex(7),attach(c,f){return JSON.stringify(c)===JSON.stringify(context)&&f.document===hex(7);}};
  const window={__fcProductionV1:page,__fcNativeCommandOwner:hex(7),__fcDiscoveryPersonaFollowupV1:{selectedPlatform:()=> 'pc'}};
  const nativeTimers=new Map();let nextTimer=0;
  const timed=(f,ms)=>{if(ms===18000){const id=++nextTimer;nativeTimers.set(id,f);return {nativeTimer:id};}return setTimeout(f,ms);};
  const cancel=t=>{if(t?.nativeTimer)nativeTimers.delete(t.nativeTimer);else clearTimeout(t);};
  const sandbox=vm.createContext({window,services:{User:{getUser:()=>user},Item:item},repositories:{Item:repository},ItemPile:{TRANSFER:2},
    XMLHttpRequest:XHR,crypto,TextEncoder,TextDecoder,URL,location:{href:'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/'},
    setTimeout:timed,clearTimeout:cancel,Date,console});
  vm.runInContext(fs.readFileSync('browser/production-v1/bulk-transfer.js','utf8'),sandbox);
  const execute=(n,operation,params={})=>window.__fcBulkTransferV1.execute({schema:2,id:hex(n),operation,params,context,fences});
  const p=(r,op)=>{const rows=r.inventory.rows,sold=rows.filter(x=>x.trade_state==='closed'),expired=rows.filter(x=>x.trade_state==='expired');
    return {before_read_id:r.command_id,expected_item_ids:(op==='bulk_clear_sold'?sold:expired).map(x=>x.item_id),
      expected_inventory_ids:rows.map(x=>x.item_id),expected_sold_count:sold.length,expected_expired_count:expired.length,
      ...(op==='bulk_relist_all'?{duration_seconds:3600}:{})};};
  return {execute,p,calls,setMode(v){mode=v;},fireTimeout(){for(const f of nativeTimers.values())f();nativeTimers.clear();},
    setPersonaBad(){window.__fcDiscoveryPersonaFollowupV1.selectedPlatform=()=> 'ps5';}};
}
(async()=>{
  let h=setup();const sources=await h.execute(1,'bulk_inspect');assert(sources.success);assert.equal(sources.network.length,0);
  const before=await h.execute(2,'bulk_inventory');assert(before.success);assert.equal(before.inventory.occupancy,5);
  assert.deepEqual(JSON.parse(JSON.stringify(before.inventory.native_counts)),{sold:2,expired:1,active:2});
  const params=h.p(before,'bulk_clear_sold');const clear=await h.execute(3,'bulk_clear_sold',params);
  assert(clear.success);assert.equal(h.calls.clear,1);assert.equal(clear.network.filter(n=>n.method==='DELETE').length,1);
  assert.equal(clear.network.filter(n=>n.method==='GET').length,2);
  const duplicate=await h.execute(4,'bulk_clear_sold',params);assert(!duplicate.success);assert.equal(h.calls.clear,1);
  const after=await h.execute(5,'bulk_inventory');assert(after.success);assert.equal(after.inventory.occupancy,3);
  const relist=await h.execute(6,'bulk_relist_all',h.p(after,'bulk_relist_all'));assert(relist.success);assert.equal(h.calls.relist,1);
  assert.equal(relist.network.length,1);assert.equal(relist.network[0].method,'PUT');assert.equal(relist.network[0].body_kind,'empty');
  const final=await h.execute(7,'bulk_inventory');assert(final.success);
  const expired=before.inventory.rows.find(r=>r.trade_state==='expired'),active=final.inventory.rows.find(r=>r.item_id===expired.item_id);
  assert.equal(active.starting_bid,expired.starting_bid);assert.equal(active.buy_now_price,expired.buy_now_price);assert.equal(active.expires,3600);
  assert.notEqual(active.trade_id,expired.trade_id);assert.equal(active.trade_state,'active');
  assert(!JSON.stringify([before,clear,after,relist,final]).includes('SYNTHETIC-SECRET-CANARY'));
  h=setup();const r=await h.execute(10,'bulk_inventory');const bad=h.p(r,'bulk_relist_all');bad.duration_seconds=7200;
  assert.equal((await h.execute(11,'bulk_relist_all',bad)).error,'eligible_state_changed');assert.equal(h.calls.relist,0);
  h=setup();const v=await h.execute(20,'bulk_inventory');h.setMode('ambiguous');
  assert.equal((await h.execute(21,'bulk_clear_sold',h.p(v,'bulk_clear_sold'))).error,'duplicate_native_mutation_blocked');
  assert.equal(h.calls.wire.filter(n=>n.method==='DELETE').length,1);
  assert(!(await h.execute(22,'bulk_clear_sold',h.p(v,'bulk_clear_sold'))).success);assert.equal(h.calls.clear,1);
  h=setup();h.setPersonaBad();assert.equal((await h.execute(30,'bulk_inventory')).error,'persona_unverified');assert.equal(h.calls.wire.length,0);
  h=setup();const preTimeout=await h.execute(40,'bulk_inventory');h.setMode('timeout');
  const pending=h.execute(41,'bulk_clear_sold',h.p(preTimeout,'bulk_clear_sold'));
  assert.equal((await h.execute(42,'bulk_inventory')).error,'single_native_owner_busy');
  assert.equal((await h.execute(43,'bulk_inventory')).error,'single_native_owner_busy','a refused concurrent call must not release the lock');
  h.fireTimeout();assert.equal((await pending).error,'native_timeout_no_retry');
  assert(!(await h.execute(44,'bulk_clear_sold',h.p(preTimeout,'bulk_clear_sold'))).success);
  assert.equal(h.calls.clear,1,'lost callback cannot cause a second dispatch');
  // Execute the ACTUALLY CAPTURED DAO functions in an isolated native double.
  const captured=JSON.parse(fs.readFileSync('docs/research/002-bulk-transfer-operations/source-inspection.json','utf8')).response.sources;
  for(const name of ['removeSold','relistExpiredAuctions']){
    const source=captured.find(s=>s.owner==='services.Item.transfersDao'&&s.name===name).source;
    const sent=[];function EAObservable(){this.notify=v=>{this.result=v;};}
    function UTHttpRequest(){this.setPath=path=>{this.path=path;};}
    function UTHttpResponseDTO(){}
    const sandbox=vm.createContext({EAObservable,UTHttpRequest,UTHttpResponseDTO,HttpRequestMethod:{DELETE:'DELETE',PUT:'PUT'},GAME_NAME:'fc27',
      JSUtils:{assignPropertyValues:(a,b)=>Object.assign(b,a),isObject:v=>v!==null&&typeof v==='object'},
      getDefaultDispatcher:()=>({notify(){}}),AppNotification:{OBJECTIVE_UPDATE:'event'}});
    const fn=vm.runInContext('('+source+')',sandbox);
    const dao={requestDelegate:{send(request){sent.push(request);return {observe(owner,callback){callback({unobserve(){}},{success:true,status:200,response:{tradeIdList:[{idStr:'123'}]}});}};}}};
    const result=fn.call(dao);assert.equal(sent.length,1);
    assert.equal(sent[0].requestType,name==='removeSold'?'DELETE':'PUT');
    assert.equal(sent[0].path,name==='removeSold'?'/ut/game/fc27/trade/sold':'/ut/game/fc27/auctionhouse/relist');
    assert.equal(sent[0].body,undefined);
    if(name==='relistExpiredAuctions')assert.equal(result.result.response.auctionIds[0],'123');
  }
  console.log('PASS bulk contracts: captured native DAO routes/body, single bulk invocation, prices/hour, identity, state filtering, ambiguity, duplicates, persona, no secrets');
})().catch(e=>{console.error(e);process.exitCode=1;});

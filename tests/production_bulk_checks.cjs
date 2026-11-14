'use strict';
// Execute deployed production page/worker code, with private native DTO/XHR doubles.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {setup}=require('./production_page_checks.cjs');

async function fixture(op='clear_sold',mode='ok'){
  const h=setup(),calls=[],wire=[],detached=[];
  const states=op==='clear_sold'?['closed','closed','expired','expired','active']:['expired','expired','active'];
  let rows=states.map((state,i)=>{
    const a={tradeId:String(500+i),startingBid:700+i*100,currentBid:state==='closed'?1000:0,
      buyNowPrice:1500+i*100,expires:state==='active'?10000:-1,tradeState:state,bidState:'none',tradeOwner:true,
      isSold(){return this.tradeState==='closed';},isExpired(){return this.tradeState==='expired';},isActiveTrade(){return this.tradeState==='active';}};
    return {id:String(300+i),definitionId:123+i,untradeable:false,lastSalePrice:0,getAuctionData:()=>a};
  });
  const repo=h.sandbox.repositories.Item;
  repo.transfer={endOfList:true};repo.getTransferItems=()=>rows;
  const rawWire=()=>rows.map(r=>({...r.getAuctionData(),itemData:{id:r.id,resourceId:r.definitionId,untradeable:false,lastSalePrice:0}}));
  const services=h.sandbox.services.Item;
  services.requestTransferItems=()=>{
    h.setTransferWire({auctionInfo:rawWire()});
    return h.response('transfer_list',{items:rows,hasMore:false});
  };
  function emit(method,path,body=null,query=''){
    const x=new h.sandbox.XMLHttpRequest();
    if(mode==='status')x.status=201;
    x.open(method,(mode==='host'?'https://elsewhere.invalid':'https://utas.test.ea.com')+'/ut/game/fc27/'+path+query);
    if(mode!=='noauth')x.setRequestHeader('X-UT-SID','PRIVATE-NATIVE-CANARY');
    x.send(body);wire.push([method,path]);
  }
  const method=op==='clear_sold'?'clearSoldItems':'relistExpiredAuctions';
  services[method]=function(...args){
    calls.push(method);assert.equal(args.length,0,'native bulk call must have zero arguments');
    return {observe(owner,callback){
      const nativeMethod=op==='clear_sold'?'DELETE':'PUT',path=op==='clear_sold'?'trade/sold':'auctionhouse/relist';
      if(mode==='pre-get' || mode==='both-get')emit('GET','tradepile');
      emit(nativeMethod,mode==='route'?'item':path,mode==='body'?'{"duration":3600}':null,mode==='query'?'?duration=3600':'');
      if(mode==='duplicate')emit(nativeMethod,path);
      if(mode==='per-item')emit('DELETE','trade/500');
      if(mode!=='no-effect'){
        if(op==='clear_sold')rows=rows.filter(r=>r.getAuctionData().tradeState!=='closed');
        else for(const r of rows){const a=r.getAuctionData();if(a.tradeState==='expired')Object.assign(a,{tradeState:'active',tradeId:String(Number(a.tradeId)+100),expires:3600});}
      }
      if(op==='clear_sold' && mode!=='no-get')emit('GET','tradepile');
      if(mode==='third-get') {emit('GET','tradepile');emit('GET','tradepile');}
      callback({unobserve(value){assert.equal(value,owner);detached.push(value);}},{success:mode!=='failed',status:200,data:{}});
    },unobserve(owner){detached.push(owner);}};
  };
  const before=h.command('transfer_list'),v=await h.execute(before);
  assert.equal(v.result.success,true,JSON.stringify(v));assert(v.coverage.complete);assert(v.coverage.bulk);
  const targets=v.result.auctions.filter(r=>r.trade_state===(op==='clear_sold'?'closed':'expired'));
  const params={before_read_id:before.id,expected_item_ids:targets.map(r=>r.item.item_id),
    expected_inventory_ids:v.result.auctions.map(r=>r.item.item_id),expected_sold_count:op==='clear_sold'?2:0,expected_expired_count:2};
  return {h,calls,wire,detached,params,before:v,rows:()=>rows};
}

async function workerContract(){
  const calls=[],files=[],handlers={},context={account:'1'.repeat(32),persona:'2'.repeat(32),identity_namespace:'3'.repeat(32),game:'fc27',platform:'pc'};
  const owner={context,owner:'4'.repeat(32),epoch:1};let peer,delivered=false;
  const page={document:'5'.repeat(32),attach(){return true;},execute(c){calls.push(c.operation);return {production:true};}};
  const pageSandbox=vm.createContext({window:{__fcProductionV1:page,__fcBulkTransferV1:{execute(){throw Error('research replay forbidden');}}}});
  const chrome={storage:{session:{async get(){return {productionTab:1,productionDocument:null};},async set(){}}},
    tabs:{async get(){return {url:'https://www.ea.com/ultimate-team/web-app/'};}},
    scripting:{async executeScript(spec){if(spec.files){files.push(...spec.files);return [];}
      return [{result:await vm.runInContext('('+spec.func.toString()+')(...'+JSON.stringify(spec.args)+')',pageSandbox)}];}},
    action:{onClicked:{addListener(f){handlers.click=f;}},async setBadgeText(){}},
    alarms:{onAlarm:{addListener(f){handlers.alarm=f;}},async create(){}}};
  const sandbox=vm.createContext({chrome,URL,crypto:require('node:crypto').webcrypto,AbortSignal,Date,
    async fetch(url,options){const path=new URL(url).pathname,value=JSON.parse(options.body);let result={};
      if(path==='/hello'){if(value.peer)peer=value.peer;result={schema:2,host_epoch:'6'.repeat(32),owner};}
      if(path==='/next'){
        if(delivered)throw Error('stop finite worker fixture');
        delivered=true;result={schema:2,id:'7'.repeat(32),operation:'clear_sold',context,fences:peer.fences,params:{}};
      }
      return {ok:true,async json(){return result;}};
    }});
  vm.runInContext(fs.readFileSync('browser/production-v1/worker.js','utf8'),sandbox);
  assert.deepEqual(calls,[],'loading worker launches no maintenance');
  await vm.runInContext('poll()',sandbox);
  assert.deepEqual(calls,['clear_sold']);assert(!files.includes('bulk-transfer.js'));
}

(async()=>{
  for(const op of ['clear_sold','relist_all']){
    for(const mode of op==='clear_sold'?['ok','no-get','both-get']:['ok']){
      const f=await fixture(op,mode),before=JSON.parse(JSON.stringify(f.before.result.auctions));
      const c=f.h.command(op,f.params),v=await f.h.execute(c);
      assert.equal(v.result.success,true,JSON.stringify(v));assert.equal(f.calls.length,1);assert.equal(f.detached.length,1);
      assert.equal(f.wire.filter(([m])=>m!=='GET').length,1);
      assert(v.result.network.every(n=>n.body_empty && Object.keys(n.query).length===0));
      const after=await f.h.execute(f.h.command('transfer_list'));
      assert(after.result.success);assert(after.coverage.complete);
      const last=before.at(-1),retained=after.result.auctions.find(r=>r.item.item_id===last.item.item_id);
      assert.deepEqual(retained,last,'unaffected active listing preserved');
      if(op==='relist_all')for(const r of after.result.auctions.slice(0,2)){
        const old=before.find(a=>a.item.item_id===r.item.item_id);
        assert.equal(r.expires,3600);assert.equal(r.starting_bid,old.starting_bid);assert.equal(r.buy_now_price,old.buy_now_price);
        assert.deepEqual(r.item,old.item);assert.notEqual(r.trade_id,old.trade_id);
      }
      assert(!(await f.h.execute(c)).result.success);assert.equal(f.calls.length,1);
    }
    for(const mode of ['body','query','route','host','duplicate','per-item','failed','status','noauth',...(op==='clear_sold'?['third-get']:[])]){
      const f=await fixture(op,mode),r=await f.h.execute(f.h.command(op,f.params));
      assert.equal(r.result.success,false,mode);assert.equal(f.calls.length,1);
      if(mode!=='failed')assert.equal(r.result.error,'bulk_contract_changed',mode);
      assert(f.wire.filter(([m])=>m!=='GET').length<=1,mode+' may send at most one mutation');
      if(['body','query','route','host'].includes(mode))assert.equal(f.wire.length,0,mode+' blocked before XHR.send');
      assert(!(await f.h.execute(f.h.command(op,f.params))).result.success);
      assert.equal(f.calls.length,1,'no replacement command for consumed snapshot');
    }
    for(const mode of ['stale','owner','persona','snapshot','membership','count','manual-new','native-price','native-identity','predicates','duration','end-changed','during-hash','identity-during-hash']){
      const f=await fixture(op),p={...f.params};
      if(mode==='stale')f.h.advance(31000);
      if(mode==='persona')f.h.switchPersona({platform:'PC',isPC:true});
      if(mode==='snapshot')p.before_read_id='9'.repeat(32);
      if(mode==='membership')p.expected_item_ids=p.expected_item_ids.slice(1);
      if(mode==='count')p.expected_expired_count++;
      if(mode==='manual-new')f.rows().push({...f.rows()[0],id:'999'});
      if(mode==='native-price')f.rows()[0].getAuctionData().buyNowPrice++;
      if(mode==='native-identity')f.rows()[0].id='999';
      if(mode==='predicates')f.rows()[0].getAuctionData()[op==='clear_sold'?'isSold':'isExpired']=()=>false;
      if(mode==='duration')p.duration=3600;
      if(mode==='end-changed')f.h.sandbox.repositories.Item.transfer.endOfList=false;
      if(mode==='during-hash' || mode==='identity-during-hash'){
        // WebCrypto awaits may yield to client activity. Recheck all mutable
        // native fields synchronously once hashing completes, before dispatch.
        const actual=f.h.sandbox.crypto;
        f.h.sandbox.crypto={subtle:{async digest(...args){
          const value=await actual.subtle.digest(...args);
          if(mode==='during-hash')f.rows()[0].getAuctionData().buyNowPrice++;
          else f.rows()[0].id='999';
          return value;
        }}};
      }
      const c=f.h.command(op,p);if(mode==='owner')c.fences.epoch++;
      const r=await f.h.execute(c);assert(!r.result.success,mode);assert.equal(f.calls.length,0,mode);
    }
  }
  const h=setup();assert.deepEqual(h.calls,[]);assert.deepEqual(h.timers,[],'page install/attach starts no job');
  await workerContract();
  console.log('PASS production native bulk: zero arguments, guarded single DELETE/PUT, independent reads, stable manual items, fences, semantics, ordinary worker dispatch; no research or recurring maintenance');
})().catch(e=>{console.error(e);process.exitCode=1;});

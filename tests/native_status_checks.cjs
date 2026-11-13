'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const {setup,ctx,hex}=require('./production_page_checks.cjs');
const samples=[];
async function read(h,op,params={}){
  const command=h.command(op,params),response=await h.execute(command);
  samples.push({command,response,now:h.now()});return response;
}
async function seed(h){
  const r=await read(h,'watched');assert(r.result.success);
  const a=r.result.auctions[0];
  return {trade_id:a.trade_id,item_id:a.item.item_id,definition_id:a.item.definition_id};
}
// Independent native implementation: no historical source/function bytes involved.
function install(h,options={}){
  const state={options,selectors:[]},dao=h.sandbox.services.Item.transfersDao;
  dao.getAuctionData=function nativeStatus(items){
    assert.equal(this,dao);assert.equal(items.length,1);
    const q=items[0].getAuctionData();assert(q.isValid());assert.equal(q.isUpdating,false);
    state.selectors.push(q.tradeId);q.isUpdating=true;
    const o=state.options,raw=h.raw(),auction=raw.getAuctionData();
    const resultItem={...raw,definitionId:0,...o.item,
      getAuctionData:()=>({...auction,currentBid:1200,expires:-1,tradeState:'closed',bidState:'outbid',...o.auction,
        isWon:()=>{h.advance(o.projectionDelay??0);return o.won??false;}})};
    return {observe(owner,callback){
      if(o.unobservable)throw Error('fixture failure');
      if(!o.cache){
        const send=()=>{
          const x=new h.sandbox.XMLHttpRequest();x.status=o.http??200;
          x.open(o.method??'GET',o.url??('https://utas.test.ea.com/ut/game/fc27/trade/status/lite?tradeIds='+(o.wireId??q.tradeId)));
          if(!o.noAuth)x.setRequestHeader('X-UT-SID','PRIVATE-FIXTURE');x.send();
        };
        send();if(o.fanout)send();
      }
      h.advance(o.delay??8);
      if(o.switchPersona)h.switchPersona({platform:'PC',isPC:true});
      callback({unobserve(){}},{success:o.success??true,status:o.status??o.http??200,
        response:o.data??{items:o.empty?[]:o.duplicate?[resultItem,resultItem]:[resultItem]}});
    },unobserve(){}};
  };
  return state;
}
(async()=>{
  for(const unavailable of [undefined,null,{},42]){
    const h=setup();h.sandbox.services.Item.transfersDao.getAuctionData=unavailable;
    let r=await read(h,'status_support');assert.equal(r.result.function_available,false);assert(r.result.success);
    const p=await seed(h),before=h.calls.length;
    r=await read(h,'status',p);assert.equal(r.result.error,'service_unavailable');assert.equal(h.calls.length,before);
  }
  // Hashing is still used for privacy-preserving identity, and only identity.
  let h=setup(),state=install(h),digests=[];
  h.sandbox.crypto={getRandomValues:webcrypto.getRandomValues.bind(webcrypto),subtle:{digest(algorithm,bytes){
    const text=new TextDecoder().decode(bytes);digests.push(text);
    assert(text.startsWith(ctx.identity_namespace+'|item|')||text.startsWith(ctx.identity_namespace+'|trade|'),'unexpected function/source digest');
    return webcrypto.subtle.digest(algorithm,bytes);
  }}};
  const p=await seed(h);
  let r=await read(h,'status_support');assert(r.result.function_available);assert.equal(r.result.network.length,0);
  assert(!Object.hasOwn(r.result,'source_sha256'));assert(!Object.hasOwn(r.result,'source_match'));
  for(const definitionId of [0,undefined,p.definition_id]){
    state.options={item:{definitionId}};r=await read(h,'status',p);assert(r.result.success,JSON.stringify(r));
    assert.equal(r.result.auctions[0].item.definition_id,definitionId??null);
    assert.equal(r.result.auctions[0].trade_id,p.trade_id);assert.equal(r.result.auctions[0].item.item_id,p.item_id);
    assert.equal(r.result.network[0].method,'GET');assert(r.result.network[0].session_header_present);
    assert.equal(r.freshness.request_count,1);assert.equal(r.result.auctions[0].current_bid,1200);
  }
  assert(digests.length>0);
  // Function identity/source spelling can change while its behavior remains valid.
  const original=h.sandbox.services.Item.transfersDao.getAuctionData;
  h.sandbox.services.Item.transfersDao.getAuctionData=new Proxy(original,{apply(fn,self,args){return Reflect.apply(fn,self,args);}});
  assert((await read(h,'status',p)).result.success);
  for(const [options,error] of [
    [{cache:true},'ambiguous_network'],[{fanout:true},'ambiguous_network'],
    [{noAuth:true},'unauthenticated'],[{http:401,success:false},'service_failed'],[{http:401},'unauthenticated'],
    [{method:'PUT'},'ambiguous_network'],[{url:'https://utas.test.ea.com/ut/game/fc27/watchlist'},'ambiguous_network'],
    [{url:'https://outside.example/trade/status/lite'},'ambiguous_network'],
    [{wireId:'999'},'ambiguous_network'],[{status:201},'schema_unrecognized'],
    [{delay:30001},'stale_source'],[{delay:-1},'stale_source'],[{projectionDelay:30001},'stale_source'],
    [{data:{}},'schema_unrecognized'],[{data:{auctionInfo:[]}},'schema_unrecognized'],
    [{data:{items:{}}},'schema_unrecognized'],[{data:{items:[null]}},'schema_unrecognized'],
    [{duplicate:true},'schema_unrecognized'],[{auction:{currentBid:-1}},'schema_unrecognized'],
    [{auction:{expires:-2}},'schema_unrecognized'],[{auction:{tradeState:'mystery'}},'schema_unrecognized'],
    [{auction:{bidState:'mystery'}},'schema_unrecognized'],[{won:'yes'},'schema_unrecognized'],
    [{item:{id:'999'}},'schema_unrecognized'],[{item:{definitionId:99}},'schema_unrecognized'],
    [{item:{definitionId:null}},'schema_unrecognized'],[{auction:{tradeId:'999'}},'schema_unrecognized'],
    [{switchPersona:true},'persona_unverified']
  ]){
    h=setup();const params=await seed(h);install(h,options);r=await read(h,'status',params);
    assert.equal(r.result.success,false,JSON.stringify(options));assert.equal(r.result.error,error,JSON.stringify(options));
    assert.equal(r.coverage.complete,false);
  }
  h=setup();let params=await seed(h);state=install(h,{empty:true});
  r=await read(h,'status',params);assert(r.result.success);assert.deepEqual(r.result.auctions,[]);assert.equal(r.coverage.complete,false);
  // Lite rows never turn a retained exact version into zero or refresh full identity.
  state.options={};assert((await read(h,'status',params)).result.success);
  for(const wrong of [{item_id:'item:'+'e'.repeat(24)},{definition_id:99},{trade_id:'trade:'+'e'.repeat(24)}]){
    const count=state.selectors.length;r=await read(h,'status',{...params,...wrong});
    assert.equal(r.result.error,'known_identity_unavailable');assert.equal(state.selectors.length,count);
  }
  // Retained selectors are snapshots, not mutable repository object identities.
  h=setup();const raw=h.raw(),a=raw.getAuctionData();raw.getAuctionData=()=>a;
  h.sandbox.services.Item.requestWatchedItems=()=>h.response('watched',{items:[raw]});
  params=await seed(h);state=install(h);a.tradeId='999';raw.id='999';
  assert((await read(h,'status',params)).result.success);assert.deepEqual(state.selectors,['20000000000000000001']);
  // Conflicting full reads cannot replace established trade/item/version mappings.
  for(const field of ['id','definitionId']){
    h=setup();params=await seed(h);install(h);const conflict={...h.raw(),[field]:field==='id'?'999':99};
    h.sandbox.services.Item.requestWatchedItems=()=>h.response('watched',{items:[conflict]});
    assert.equal((await read(h,'watched')).result.error,'schema_unrecognized');
    assert((await read(h,'status',params)).result.success);
  }
  // Every reconnect clears private mappings; an identical reattach is idempotent.
  for(const field of ['epoch','owner','host_epoch','worker_epoch']){
    h=setup();params=await seed(h);state=install(h);const old=h.command('status',params);
    assert(h.api.attach(ctx,h.fences));assert((await read(h,'status',params)).result.success);
    const fences={...h.fences,epoch:2};if(field!=='epoch')fences[field]=hex(88);
    assert(h.api.attach(ctx,fences));Object.assign(h.fences,fences);
    assert.equal((await h.execute(old)).result.error,'invalid_command');
    assert.equal((await read(h,'status_support')).result.retained_count,0);
    const count=state.selectors.length;assert.equal((await read(h,'status',params)).result.error,'known_identity_unavailable');
    assert.equal(state.selectors.length,count);assert(!h.api.attach(ctx,{...fences,epoch:1}));
    assert(!h.api.attach(ctx,{...fences,worker_epoch:hex(99)}));
    await seed(h);assert((await read(h,'status',params)).result.success);
  }
  const previous=h.api.document;h=setup();state=install(h);assert.notEqual(h.api.document,previous);
  assert.equal((await read(h,'status',params)).result.error,'known_identity_unavailable');assert.equal(state.selectors.length,0);
  await seed(h);assert((await read(h,'status',params)).result.success);
  if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(samples));
  console.log('PASS native status: availability, independent functions, authenticated GET, schema, exact retained identities, freshness, omissions, reconnect epochs, no source digests');
})().catch(e=>{console.error(e);process.exitCode=1;});

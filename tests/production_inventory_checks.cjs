'use strict';
// Executes production JS and the retained native DAO as a behavioral fixture.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const {setup,ctx,hex}=require('./production_page_checks.cjs');
const reviewed=JSON.parse(fs.readFileSync('docs/research/001c/001c-06-resume-01/source-contract.json','utf8'));
const samples=[];
const hash=async(v,ns)=>ns+':'+Buffer.from(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(ctx.identity_namespace+'|'+ns+'|'+v))).toString('hex').slice(0,24);
function nativeDAO(h,mode='ok'){
  let lastQuery;
  h.sandbox.EAObservable=class{notify(v){this.value=v;}observe(owner,cb){cb(this,this.value);}unobserve(){}};
  h.sandbox.UTHttpRequest=class{setPath(p){this.path=p;}setUrlVariables(v){this.query=v;}};
  h.sandbox.UTHttpResponseDTO=class{};
  h.sandbox.JSUtils={assignPropertyValues:(a,b)=>Object.assign(b,a),isObject:v=>v&&typeof v==='object'};
  h.sandbox.DebugUtils={Assert:(v)=>assert(v)};h.sandbox.GAME_NAME='fc27';
  const raw=h.raw(),a=raw.getAuctionData();
  const item={id:raw.id,definitionId:mode==='wrongVersion'?99:mode==='omitted'?undefined:0,tradable:false,lastSalePrice:0,
    getAuctionData:()=>({...a,tradeId:mode==='wrongTrade'?'20000000000000000002':a.tradeId,currentBid:1200,expires:-1,tradeState:'closed',bidState:'outbid',isWon:()=>false})};
  h.sandbox.factories={Item:{generateItemsFromAuctionData:rows=>rows}};
  const dao=h.sandbox.services.Item.transfersDao;
  dao.requestDelegate={send(e){assert.equal(e.cache,false);assert.equal(e.path,'/ut/game/fc27/trade/status/lite');
    lastQuery=e.query;assert.deepEqual(JSON.parse(JSON.stringify(e.query)),{tradeIds:a.tradeId});
    return h.response('status',{auctionInfo:mode==='empty'?[]:[item]},mode==='wrongWire'?{tradeIds:'999'}:e.query);
  }};
  dao.getAuctionData=vm.runInContext('('+reviewed.function_source+')',h.sandbox);
  return ()=>lastQuery;
}
async function read(h,op,params={}){
  const c=h.command(op,params),r=await h.execute(c);samples.push({command:c,response:r,now:h.now()});return r;
}
(async()=>{
  let h=setup();nativeDAO(h);
  let support=await read(h,'status_support');assert(support.result.function_available);assert.equal(support.result.retained_count,0);assert.equal(support.freshness.request_count,0);
  const methods={watched:['INBOX','requestWatchedItems','auctions'],unassigned:['PURCHASED','requestUnassignedItems','items'],transfer_list:['TRANSFER','requestTransferItems','auctions']};
  for(const [op,[pile,method,field]] of Object.entries(methods)){
    h=setup();let wins=0;
    const rows=Array.from({length:50},(_,index)=>({id:String(300000+index),definitionId:261855+index,tradable:index%2===0,lastSalePrice:index,
      getAuctionData:()=>({tradeId:String(500000+index),startingBid:700,currentBid:800+index*50,buyNowPrice:10500,
        expires:index===0?-1:100+index,tradeState:index===0?'closed':'active',bidState:index===0?'highest':index%2?'outbid':'highest',
        isWon(){wins++;return index===0;}})}));
    h.sandbox.services.Item[method]=()=>h.response(op,{items:rows,hasMore:true});
    const r=await read(h,op);assert(r.result.success);assert.equal(r.result[field].length,50);assert(r.result.cache_invalidated);
    assert.equal(h.events[0],'dirty:'+h.sandbox.ItemPile[pile]);assert.equal(h.events[1],op);assert.equal(r.coverage.complete,false);assert.equal(r.coverage.has_more,true);
    for(let index=0;index<50;index++){
      const row=r.result[field][index],item=field==='items'?row:row.item;
      assert.equal(item.item_id,await hash(String(300000+index),'item'));assert.equal(item.definition_id,261855+index);assert.equal(item.untradeable,index%2!==0);
      if(field==='auctions'){
        assert.equal(row.trade_id,await hash(String(500000+index),'trade'));assert.equal(row.current_bid,800+index*50);assert.equal(row.expires,index===0?-1:100+index);
        assert.equal(row.trade_state,index===0?'closed':'active');assert.equal(row.bid_state,index===0?'highest':index%2?'outbid':'highest');assert.equal(row.native_is_won,index===0);
      }
    }
    assert.equal(wins,field==='items'?0:50,'isWon evaluated exactly once per projected auction');
    for(const mode of ['cache','noAuth','http401','fanout','stale','malformed']){
      const bad=setup(mode),r=await read(bad,op);assert(!r.result.success,op+mode);
    }
    for(const missing of ['dirty','method','pile']){
      const bad=setup();if(missing==='dirty')delete bad.sandbox.repositories.Item.setDirty;
      if(missing==='method')delete bad.sandbox.services.Item[method];if(missing==='pile')delete bad.sandbox.ItemPile[pile];
      const r=await read(bad,op);assert.equal(r.result.error,'service_unavailable');assert.equal(bad.calls.length,0);
    }
    const wrongRoute=setup();wrongRoute.sandbox.services.Item[method]=()=>wrongRoute.response('balance',{items:rows});
    assert.equal((await read(wrongRoute,op)).result.error,'ambiguous_network');
    const duplicate=setup();duplicate.sandbox.services.Item[method]=()=>duplicate.response(op,{items:[rows[0],rows[0]]});
    assert.equal((await read(duplicate,op)).result.error,'schema_unrecognized');
  }
  h=setup();const raw=h.raw(),auction=raw.getAuctionData();delete auction.isWon;
  raw.getAuctionData=()=>auction;h.sandbox.services.Item.requestWatchedItems=()=>h.response('watched',{items:[raw]});
  assert.equal((await read(h,'watched')).result.auctions[0].native_is_won,null);
  for(const mode of ['ok','omitted','empty','wrongVersion','wrongTrade','wrongWire']){
    h=setup();nativeDAO(h,mode);let r=await read(h,'watched');const row=r.result.auctions[0];
    const p={trade_id:row.trade_id,item_id:row.item.item_id,definition_id:row.item.definition_id};
    r=await read(h,'status',p);
    if(['ok','omitted','empty'].includes(mode)){
      assert(r.result.success,JSON.stringify(r));assert.equal(r.result.auctions.length,mode==='empty'?0:1);
      if(mode!=='empty')assert.equal(r.result.auctions[0].item.definition_id,mode==='omitted'?null:0);
      assert.deepEqual(r.result.network[0].query,{trade_id:p.trade_id});assert.equal(r.freshness.request_count,1);
      // No lite row overwrites the retained exact version: repeated status remains valid.
      if(mode==='ok')assert((await read(h,'status',p)).result.success);
    }else assert(!r.result.success,mode);
  }
  h=setup();nativeDAO(h);const watched=await read(h,'watched'),row=watched.result.auctions[0];
  const p={trade_id:row.trade_id,item_id:row.item.item_id,definition_id:row.item.definition_id};
  assert((await read(h,'status',p)).result.success);
  const attempts=h.calls.length;
  assert.equal((await read(h,'status',{...p,item_id:'item:'+'e'.repeat(24)})).result.error,'known_identity_unavailable');
  assert.equal(h.calls.length,attempts);
  assert(h.api.attach(ctx,{...h.fences,epoch:2}));h.fences.epoch=2;
  support=await read(h,'status_support');assert.equal(support.result.retained_count,0);assert(support.result.function_available);
  const before=h.calls.length;assert.equal((await read(h,'status',p)).result.error,'known_identity_unavailable');assert.equal(h.calls.length,before);
  // A genuinely new page cannot reverse a pseudonym. Explicit fresh full read required.
  h=setup();nativeDAO(h);assert.equal((await read(h,'status',p)).result.error,'known_identity_unavailable');assert.equal(h.calls.length,0);
  await read(h,'watched');assert((await read(h,'status',p)).result.success);
  h=setup();await read(h,'watched');assert.equal((await read(h,'status',p)).result.error,'service_unavailable');assert.equal(h.calls.filter(x=>x==='status').length,0);
  if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(samples));
  console.log('PASS inventory: 50 exact rows, dirty-before-read, cache/auth/route failures, reviewed DAO execution, lite omissions, unknown IDs, reconnect fence and reacquisition');
})().catch(e=>{console.error(e);process.exitCode=1;});

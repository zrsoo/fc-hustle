'use strict';
const assert=require('node:assert/strict');
const {setup}=require('./production_page_checks.cjs');

async function fixture(mode='ok'){
  const h=setup(), writes=[];
  let moved=false,listed=false;
  const acquired={...h.raw(),lastSalePrice:mode==='paid'?750:800};
  const terminal={...h.raw().getAuctionData(),currentBid:800,expires:0,tradeState:'closed',bidState:'highest',isWon:()=>true};
  const inactive={...terminal,tradeId:'0',currentBid:0,expires:-1,tradeState:'inactive',bidState:'none',isWon:()=>false};
  const active={...inactive,tradeId:'30000000000000000001',startingBid:11750,buyNowPrice:12000,expires:3600,tradeState:'active'};
  acquired.getAuctionData=()=>moved?(listed?active:inactive):terminal;
  const watched={...acquired,getAuctionData:()=>terminal};
  const item=h.sandbox.services.Item;
  item.requestWatchedItems=()=>h.response('watched',{items:[watched]});
  item.requestUnassignedItems=()=>h.response('unassigned',{items:moved?[]:[mode==='physical'?{...acquired,id:'10000000000000000002'}:acquired]});
  item.requestTransferItems=()=>{
    const rows=moved?[acquired]:[];
    const a=listed?active:inactive;
    h.setTransferWire({auctionInfo:rows.map(i=>({...a,itemData:{id:i.id,resourceId:i.definitionId,untradeable:false,lastSalePrice:i.lastSalePrice}}))});
    return h.response('transfer_list',{items:rows,hasMore:false});
  };
  h.sandbox.repositories.Item.getTransferItems=()=>moved?[acquired]:[];
  h.sandbox.repositories.Item.transfer={endOfList:true};
  item.move=(rows,pile,flag)=>{
    assert.equal(rows.length,1);assert.equal(rows[0],acquired);assert.equal(pile,3);assert.equal(flag,false);
    writes.push('move');moved=true;return h.response('move',{});
  };
  item.list=(raw,start,bin,duration)=>{
    assert.equal(raw,acquired);assert.equal(start,11750);assert.equal(bin,12000);assert.equal(duration,3600);
    writes.push('list');listed=true;return h.response('list',{});
  };
  if(mode==='caps')item.transfersDao.getItemMarketDataByDefId=()=>h.response('caps',{
    marketData:[{defId:7654321,priceLimits:{minimum:150,maximum:11000}}]},{defId:7654321});
  async function read(op,p={}){const c=h.command(op,p),v=await h.execute(c);assert.equal(v.result.success,true,JSON.stringify(v));return {c,v};}
  const win=await read('watched'),owned=await read('unassigned'),caps=await read('caps',{definition_id:7654321});
  const r=win.v.result.auctions[0];
  const params={trade_id:r.trade_id,item_id:r.item.item_id,definition_id:r.item.definition_id,paid:800,
    win_read_id:win.c.id,owned_read_id:owned.c.id,caps_read_id:caps.c.id,starting_bid:11750,buy_now_price:12000,duration:3600};
  return {h,writes,read,params,win,owned,caps};
}

(async()=>{
  const f=await fixture();
  let c=f.h.command('move',f.params),r=await f.h.execute(c);
  assert.equal(r.result.success,true,JSON.stringify(r));assert.deepEqual(f.writes,['move']);
  assert.equal(r.result.network[0].method,'PUT');assert.equal(r.result.network[0].path,'/ut/game/fc27/item');
  const pile=await f.read('transfer_list');assert.equal(pile.v.coverage.complete,true);
  const caps=await f.read('caps',{definition_id:7654321});
  c=f.h.command('list',{...f.params,owned_read_id:pile.c.id,caps_read_id:caps.c.id});r=await f.h.execute(c);
  assert.equal(r.result.success,true,JSON.stringify(r));assert.deepEqual(f.writes,['move','list']);
  assert.equal(r.result.network[0].method,'POST');assert.equal(r.result.network[0].path,'/ut/game/fc27/auctionhouse');
  const after=await f.read('transfer_list');
  assert.equal(after.v.result.auctions[0].expires,3600);assert.notEqual(after.v.result.auctions[0].trade_id,f.params.trade_id);
  assert.equal(after.v.result.auctions[0].item.item_id,f.params.item_id);
  const retry=await f.h.execute(f.h.command('list',{...c.params,owned_read_id:after.c.id}));
  assert.equal(retry.result.success,false);assert.deepEqual(f.writes,['move','list']);

  for(const mode of ['paid','physical','caps','stale','owner','persona','tick','minimum','duration','wrong-read','not-won']){
    const x=await fixture(mode),p={...x.params};
    if(mode==='stale')x.h.advance(31000);
    if(mode==='persona')x.h.switchPersona({platform:'PC',isPC:true});
    if(mode==='tick')p.starting_bid=11500;
    if(mode==='minimum')p.starting_bid=100;
    if(mode==='duration')p.duration=7200;
    if(mode==='wrong-read')p.owned_read_id=x.caps.c.id;
    if(mode==='not-won'){
      const raw=x.h.raw();
      x.h.sandbox.services.Item.requestWatchedItems=()=>x.h.response('watched',{items:[raw]});
      p.win_read_id=(await x.read('watched')).c.id;
    }
    const cmd=x.h.command('move',p);
    if(mode==='owner')cmd.fences.epoch++;
    const result=await x.h.execute(cmd);
    assert.equal(result.result.success,false,mode);assert.deepEqual(x.writes,[],mode);
  }
  console.log('PASS native resale: exact physical DTO, native move/list arguments, current caps/ticks, hour, persona/epoch, paid proof and no replay');
})().catch(e=>{console.error(e);process.exitCode=1;});

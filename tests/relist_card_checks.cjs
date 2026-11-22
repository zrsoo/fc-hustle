'use strict';
// Card-by-card relist: the page lists an expired card again only under its own
// expired trade id from a fresh complete transfer-list read.
const assert=require('node:assert/strict');
const {setup}=require('./production_page_checks.cjs');

async function fixture(state='expired'){
  const h=setup(),writes=[];
  let listed=false;
  const card={...h.raw(),lastSalePrice:800};
  const before={...h.raw().getAuctionData(),tradeId:'20000000000000000001',currentBid:0,expires:-1,tradeState:state,
    bidState:'none',startingBid:11750,buyNowPrice:12000,isWon:()=>false};
  const active={...before,tradeId:'30000000000000000001',expires:3600,tradeState:'active'};
  card.getAuctionData=()=>listed?active:before;
  const item=h.sandbox.services.Item;
  item.requestTransferItems=()=>{
    const a=listed?active:before;
    h.setTransferWire({auctionInfo:[{...a,itemData:{id:card.id,resourceId:card.definitionId,untradeable:false,lastSalePrice:800}}]});
    return h.response('transfer_list',{items:[card],hasMore:false});
  };
  h.sandbox.repositories.Item.getTransferItems=()=>[card];
  h.sandbox.repositories.Item.transfer={endOfList:true};
  item.list=(raw,start,bin,duration)=>{
    assert.equal(raw,card);assert.equal(start,11750);assert.equal(bin,12000);assert.equal(duration,3600);
    writes.push('list');listed=true;return h.response('list',{});
  };
  async function read(op,p={}){const c=h.command(op,p),v=await h.execute(c);assert.equal(v.result.success,true,JSON.stringify(v));return {c,v};}
  const pile=await read('transfer_list'),caps=await read('caps',{definition_id:7654321});
  const r=pile.v.result.auctions[0];
  const params={trade_id:r.trade_id,item_id:r.item.item_id,definition_id:r.item.definition_id,paid:800,
    win_read_id:pile.c.id,owned_read_id:pile.c.id,caps_read_id:caps.c.id,starting_bid:11750,buy_now_price:12000,duration:3600};
  return {h,writes,read,params,pile,active};
}

(async()=>{
  const f=await fixture();
  assert.equal(f.pile.v.result.auctions[0].trade_state,'expired');
  const r=await f.h.execute(f.h.command('list',f.params));
  assert.equal(r.result.success,true,JSON.stringify(r));assert.deepEqual(f.writes,['list']);
  assert.equal(r.result.network[0].method,'POST');assert.equal(r.result.network[0].path,'/ut/game/fc27/auctionhouse');
  const after=await f.read('transfer_list');
  assert.equal(after.v.result.auctions[0].trade_state,'active');assert.notEqual(after.v.result.auctions[0].trade_id,f.params.trade_id);
  // The relisted card expires again under its new trade id: the same page lists it again (live 2026-11-22).
  Object.assign(f.active,{tradeState:'expired',expires:-1});
  const pile2=await f.read('transfer_list'),caps2=await f.read('caps',{definition_id:7654321});
  const r2=pile2.v.result.auctions[0];assert.equal(r2.trade_state,'expired');assert.notEqual(r2.trade_id,f.params.trade_id);
  const p2={...f.params,trade_id:r2.trade_id,owned_read_id:pile2.c.id,win_read_id:pile2.c.id,caps_read_id:caps2.c.id};
  const second=await f.h.execute(f.h.command('list',p2));
  assert.equal(second.result.success,true,JSON.stringify(second));assert.deepEqual(f.writes,['list','list']);
  // No second listing of the same expired trade, nor of the first one again (a refusal poisons the page).
  const third=await f.h.execute(f.h.command('list',p2));
  assert.equal(third.result.success,false);assert.deepEqual(f.writes,['list','list']);

  for(const mode of ['active','closed','other-trade','separate-win-read','stale']){
    const x=await fixture(mode==='active'||mode==='closed'?mode:'expired'),p={...x.params};
    if(mode==='other-trade')p.trade_id='trade:'+'9'.repeat(24);
    if(mode==='separate-win-read')p.win_read_id=(await x.read('watched')).c.id;
    if(mode==='stale')x.h.advance(31000);
    const result=await x.h.execute(x.h.command('list',p));
    assert.equal(result.result.success,false,mode);assert.deepEqual(x.writes,[],mode);
  }
  console.log('PASS card relist: an expired card is listed again only under its own trade id from a fresh complete read; no replay');
})().catch(e=>{console.error(e);process.exitCode=1;});

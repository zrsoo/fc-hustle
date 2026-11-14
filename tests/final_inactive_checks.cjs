'use strict';
const assert=require('node:assert/strict');
const {setup}=require('./production_page_checks.cjs');
(async()=>{
 const h=setup();h.setAuction({tradeId:'0',tradeState:'inactive',bidState:'none',startingBid:0,currentBid:0,buyNowPrice:0,expires:0});
 const raw=h.raw();h.sandbox.repositories.Item.getTransferItems=()=>[raw];h.sandbox.repositories.Item.transfer={endOfList:true};
 h.sandbox.services.Item.requestTransferItems=()=>h.response('transfer_list',{items:[raw]});
 const itemData={id:raw.id,resourceId:raw.definitionId,untradeable:false,lastSalePrice:7700};
 h.setTransferWire({auctionInfo:[{itemData,expires:0}]});
 let r=await h.execute(h.command('transfer_list'));
 assert(r.result.success);assert(r.coverage.complete,JSON.stringify(r.coverage));
 assert.equal(r.result.auctions.length,1);assert.equal(r.result.auctions[0].trade_state,'inactive');
 assert.equal(r.result.auctions[0].item.last_sale_price,7700);
 for(const changed of [{startingBid:123},{tradeState:'active'},{itemData:{...itemData,id:'999999999999999999'}}]){
  h.setTransferWire({auctionInfo:[{itemData,expires:0,...changed}]});
  r=await h.execute(h.command('transfer_list'));assert(r.result.success);assert.equal(r.coverage.complete,false);
  assert.equal(r.coverage.transfer_list.reason,'TRANSFER_LIST_CONFLICT');
 }
 console.log('PASS inactive pile: actual physical member counted using native defaults; explicit value/state/identity conflicts remain blocked');
})().catch(e=>{console.error(e);process.exitCode=1;});

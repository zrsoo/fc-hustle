'use strict';
// Execute the deployed native reader, including XHR capture and repository proof.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {setup}=require('./production_page_checks.cjs');
const samples=[];
function rows(n=5){
  return Array.from({length:n},(_,i)=>({id:String(300000+i),definitionId:123,
    tradable:true,lastSalePrice:0,getAuctionData:()=>({
      tradeId:i%5===3?'0':String(500000+i),startingBid:i%5===3?0:800,
      currentBid:i%5===2?900:0,buyNowPrice:15000,
      expires:i%5===0?300:-1,tradeState:['active','expired','closed','inactive',null][i%5],
      bidState:i%5===2?'sold':'none',isWon:()=>false})}));
}
function wire(rows){return rows.map(x=>({...x.getAuctionData(),itemData:{id:x.id,resourceId:x.definitionId}}));}
async function run(name,{n=5,change=()=>{},mode='ok'}={}){
  const h=setup(mode),callback=rows(n),state={callback,wire:wire(callback),repo:callback,end:true,hasMore:false};
  change(state);
  h.setTransferWire({auctionInfo:state.wire,hasMore:state.wireMore??false});
  h.sandbox.repositories.Item.transfer={endOfList:state.end};
  h.sandbox.repositories.Item.getTransferItems=()=>state.repo;
  h.sandbox.services.Item.requestTransferItems=()=>h.response('transfer_list',{items:state.callback,hasMore:state.hasMore});
  const command=h.command('transfer_list'),response=await h.execute(command);
  samples.push({name,command,response,now:h.now()});
  assert.equal(h.events[0],'dirty:3');
  assert.deepEqual(h.calls,['transfer_list']);
  return response;
}
(async()=>{
  for(const n of [0,5,49,50,51,75,100]){
    const r=await run('complete-'+n,{n});
    assert(r.result.success,JSON.stringify(r));assert(r.coverage.complete);
    assert.equal(r.result.auctions.length,n);assert.equal(r.coverage.transfer_list.wire_count,n);
    if(n>=5)assert.deepEqual(r.result.auctions.slice(0,5).map(x=>x.trade_state),['active','expired','closed','inactive',null]);
  }
  const cases=[
    ['missing-wire',s=>{s.wire=null;},'TRANSFER_LIST_UNKNOWN'],
    ['missing-repository',s=>{s.repo=undefined;},'TRANSFER_LIST_UNKNOWN'],
    ['unknown-end',s=>{s.end=undefined;},'TRANSFER_LIST_UNKNOWN'],
    ['callback-more',s=>{s.hasMore=true;},'TRANSFER_LIST_TRUNCATED'],
    ['wire-more',s=>{s.wireMore=true;},'TRANSFER_LIST_TRUNCATED'],
    ['repository-more',s=>{s.end=false;},'TRANSFER_LIST_TRUNCATED'],
    ['callback-truncated',s=>{s.callback=s.callback.slice(0,4);},'TRANSFER_LIST_CONFLICT'],
    ['wire-truncated',s=>{s.wire=s.wire.slice(0,4);},'TRANSFER_LIST_CONFLICT'],
    ['repository-truncated',s=>{s.repo=s.repo.slice(0,4);},'TRANSFER_LIST_CONFLICT'],
    ['wire-state-conflict',s=>{s.wire[0].currentBid=950;},'TRANSFER_LIST_CONFLICT'],
    ['wire-item-conflict',s=>{s.wire[0].itemData.id='99999';},'TRANSFER_LIST_CONFLICT'],
    ['wire-version-conflict',s=>{s.wire[0].itemData.resourceId=999;},'TRANSFER_LIST_CONFLICT'],
    ['repository-conflict',s=>{s.repo=rows();s.repo[0].getAuctionData=()=>({...rows()[0].getAuctionData(),buyNowPrice:9999});},'TRANSFER_LIST_CONFLICT'],
    ['wire-duplicate',s=>{s.wire[1]=s.wire[0];},'TRANSFER_LIST_CONFLICT'],
    ['repository-duplicate',s=>{s.repo=[s.repo[0],s.repo[0],...s.repo.slice(2)];},'TRANSFER_LIST_CONFLICT'],
  ];
  for(const [name,change,reason]of cases){
    const r=await run(name,{change});assert(r.result.success,name);
    assert.equal(r.coverage.complete,false,name);assert.equal(r.coverage.transfer_list.reason,reason,name);
  }
  for(const mode of ['cache','noAuth','http401','fanout','stale','malformed']){
    const r=await run(mode,{mode});assert(!r.result.success,mode);
  }
  const duplicate=await run('callback-duplicate',{change:s=>{s.callback=[s.callback[0],s.callback[0],...s.callback.slice(2)];}});
  assert.equal(duplicate.result.error,'transfer_list_conflict');
  if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(samples));
  console.log('PASS: native all-state occupancy, empty/full/over-cap, missing/truncated/conflicting views and freshness/authentication failures');
})().catch(e=>{console.error(e);process.exitCode=1;});

'use strict';
// Synthetic native/wire results through the actual production page, zero EA.
const assert=require('node:assert/strict');
const {setup}=require('./production_page_checks.cjs');
async function run(mode){
  const h=setup(),s=h.command('watched'),b=h.command('balance');
  if(mode==='previousOutbid')h.setAuction({currentBid:2600,bidState:'outbid'});
  const row=(await h.execute(s)).result.auctions[0];await h.execute(b);
  const amount=mode==='previousOutbid'?2700:2500;
  const c=h.command('bid',{trade_id:row.trade_id,item_id:row.item.item_id,definition_id:row.item.definition_id,
    amount,minimum:amount,cap:9000,deadline:'2030-01-01T00:01:00Z',status_read_id:s.id,balance_read_id:b.id});
  let sends=0;
  h.sandbox.UtasErrorCode={STATE_INVALID:123}; // Explicit synthetic enum, not a claimed EA code.
  const dao=h.sandbox.services.Item.transfersDao;
  const fake=function(input,value){return {observe(owner,cb){
    const X=h.sandbox.XMLHttpRequest,x=new X();
    x.open('PUT','https://utas.test.ea.com/ut/game/fc27/trade/'+(mode==='wrongTrade'?'20000000000000000002':'20000000000000000001')+'/bid');
    x.setRequestHeader('X-UT-SID','not-a-real-session');
    const a=input.getAuctionData();
    const returned={...input,getAuctionData:()=>({...a,currentBid:value,bidState:mode==='none'?'none':mode==='previousOutbid'?'outbid':'highest',
      ...(mode==='wrongItem'?{tradeId:'20000000000000000002'}:{})})};
    const items=['empty','stale','rejected','errorSuccess','unknownError'].includes(mode)?[]:[returned];
    if(mode==='stale')input.getAuctionData=()=>({...a,isStale:()=>true});
    x.status=['rejected','unknownError'].includes(mode)?409:200;
    x.responseText=JSON.stringify({auctionInfo:items,...(['rejected','errorSuccess','unknownError'].includes(mode)?{code:mode==='unknownError'?456:123}:{})});
    x.send(JSON.stringify({bid:mode==='wrongAmount'?value+100:value,...(mode==='extraBody'?{unexpected:true}:{})}));sends++;
    cb({unobserve(){}},{success:!['rejected','unknownError'].includes(mode),status:x.status,
      ...(['rejected','errorSuccess','unknownError'].includes(mode)?{error:{code:mode==='unknownError'?456:123}}:{}),response:{items}});
  },unobserve(){}};};
  dao.bid=fake;
  const r=await h.execute(c);
  assert.equal(dao.bid,fake,'DAO hook restored');
  assert.equal(sends,['wrongTrade','wrongAmount','extraBody'].includes(mode)?0:1);
  const again=await h.execute(c);assert.equal(again.result.success,false);assert.equal(dao.bid,fake);
  return {r,c,sends};
}
(async()=>{
  for(const mode of ['empty','stale','none','wrongItem','previousOutbid','errorSuccess','unknownError']){
    const {r}=await run(mode);assert.equal(r.result.success,false,mode);
    assert.equal(r.result.bid_receipt.verdict,'UNCONFIRMED',mode);
  }
  for(const mode of ['wrongTrade','wrongAmount','extraBody'])assert.equal((await run(mode)).sends,0);
  const accepted=await run('accepted');assert(accepted.r.result.success);assert.equal(accepted.r.result.bid_receipt.verdict,'ACCEPTED');
  const rejected=await run('rejected');assert.equal(rejected.r.result.error,'bid_rejected');assert.equal(rejected.r.result.bid_receipt.verdict,'REJECTED');
  if(process.argv.includes('--samples'))process.stdout.write(JSON.stringify([accepted,rejected]));
  else console.log('PASS bid receipts: accepted identity, empty/stale/none/error, prior-outbid, wrong wire zero sends, explicit rejection, no duplicate dispatch, hooks restored');
})().catch(e=>{console.error(e);process.exitCode=1;});

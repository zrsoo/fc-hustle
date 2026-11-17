"use strict";
const assert=require('node:assert/strict');
const {setup}=require('./production_page_checks.cjs');
const native=require('./controller_native_checks.cjs');
(async()=>{
  let n=0;
  const f=setup();f.enableControllerQueue();let r=await f.api.executeReadController(f.command('watched'));
  assert.equal(r.result.success,true,JSON.stringify(r));assert.deepEqual(JSON.parse(JSON.stringify(r.coverage.watch_list)),{capacity:50,wire_count:1,callback_count:1,repository_count:1,repository_full:false});n++;
  for(const mode of ['missing','zero','wrong_count','wrong_full']){
    const h=setup();h.enableControllerQueue();const repo=h.sandbox.repositories.Item;
    if(mode==='missing')delete repo.getPileSize;
    if(mode==='zero')repo.getPileSize=()=>0;
    if(mode==='wrong_count')repo.getWatchedItems=()=>[];
    if(mode==='wrong_full')repo.isPileFull=()=>true;
    r=await h.api.executeReadController(h.command('watched'));assert.equal(r.result.success,false,mode);n++;
  }
  const h=native.setup(1);const full=await native.seed(h),t=full.targets[0];h.setOptions({watchFull:true});const before=h.calls.length;
  r=await h.execute(h.command('bid',{target:t,amount:500,minimum:500,cap:1000,deadline:'2030-01-01T00:03:00Z',status_read_id:full.v.command_id,batch_id:native.hex(77),decision_id:native.hex(78)}));
  assert.equal(r.success,false);assert.equal(r.error,'invalid_preconditions');assert.equal(h.calls.length,before);assert.equal(r.network.length,0);n++;
  const g=native.setup(1);g.raw[0].getAuctionData().watched=true;const known=await native.seed(g);g.setOptions({watchFull:true});
  r=await g.execute(g.command('bid',{target:known.targets[0],amount:500,minimum:500,cap:1000,deadline:'2030-01-01T00:03:00Z',status_read_id:known.v.command_id,batch_id:native.hex(77),decision_id:native.hex(78)}));
  assert.equal(r.success,true,JSON.stringify(r));n++;
  const vm=require('node:vm'),fs=require('node:fs');const methods=JSON.parse(fs.readFileSync('docs/research/005/stage14/public-watch-contract.json','utf8')).methods;
  for(const watched of [false,true]){
    const calls=[];class Panel{setBidBuyBusyState(v){calls.push(v);}}
    const b=vm.createContext({ItemPile:{INBOX:'inbox'},UTAuctionActionPanelView:Panel,repositories:{Item:{isPileFull:()=>true}},utils:{PopupManager:{Alerts:{WATCH_LIST_FULL:'FULL',BID_TOO_LOW:'LOW'},showAlert:v=>calls.push(v)}}});
    const onBid=vm.runInContext('('+methods.ui_bid_capacity_guard+')',b),a={watched,currentBid:0,startingBid:500,getSecondsRemaining:()=>300,isHighestBid:()=>false};
    onBid.call({panel:new Panel(),viewmodel:{current:()=>({getAuctionData:()=>a})},eBidConfirmed:()=>calls.push('BID')},null,null,{value:500});
    assert(calls.includes(watched?'BID':'FULL'));assert.equal(calls.includes('BID'),watched);n++;
  }
  console.log('PASS '+n+' native watch-capacity contracts; no account requests');
})().catch(e=>{console.error(e);process.exitCode=1;});

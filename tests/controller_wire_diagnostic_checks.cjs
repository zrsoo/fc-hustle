'use strict';
const assert=require('node:assert/strict');
const {setup,seed}=require('./controller_native_checks.cjs');
async function suite(){
  for(const type of [undefined,'json','arraybuffer']){
    const h=setup(1),t=(await seed(h)).targets;
    const wire={...h.raw[0].getAuctionData(),itemData:{id:h.raw[0].id},currentBid:700,bidState:'outbid'};
    h.setOptions({responseType:type,wire:{auctionInfo:[wire],message:'PRIVATE_CANARY',credentials:'PRIVATE_CANARY'},auction:{currentBid:500,bidState:'outbid'}});
    const c=h.command('status_batch',{targets:t}),result=await h.execute(c);
    assert(result.success,JSON.stringify(result));
    const records=h.sandbox.window.__fcProductionDiagnosticsV1.get(c.id);
    const record=records.find(r=>r.stage==='WIRE_AUCTION');
    assert.equal(record.detail.wire_ready,true);assert.equal(record.detail.wire_target_found,true);
    assert.equal(record.detail.wire_current_bid,700);assert.equal(result.auctions[0].current_bid,500);
    assert.equal(record.detail.wire_identity_matches,true);assert.equal(record.detail.wire_callback_matches,false);
    assert.equal(record.detail.target_index,0);assert(!JSON.stringify(records).includes('PRIVATE_CANARY'));
    assert(records.some(r=>r.stage==='EA_BODY'&&r.detail.row_count===1&&r.detail.message_present===true));
    assert.equal(h.calls.filter(r=>r.method!=='GET').length,0,'diagnostics issue no account writes');
    h.setOptions({wire:{auctionInfo:[{...wire,currentBid:500}]},auction:{currentBid:500,bidState:'outbid'}});
    const next=h.command('status_batch',{targets:t});assert((await h.execute(next)).success);
    assert.equal(h.sandbox.window.__fcProductionDiagnosticsV1.get(next.id).find(r=>r.stage==='WIRE_AUCTION').detail.wire_callback_matches,true);
  }
  console.log('PASS owned wire/current callback comparison across response encodings; no sensitive values or writes');
}
suite().catch(e=>{console.error(e);process.exitCode=1;});

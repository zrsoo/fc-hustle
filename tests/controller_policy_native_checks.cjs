'use strict';
// Actual shared page read -> durable-mode bridge bid -> exact-target readback.
const assert=require('node:assert/strict');
const {setup,hex}=require('./controller_native_checks.cjs');
async function suite(){
  for(const age of [0,31000]){
    const h=setup(2),c={...h.command('search',{purpose:'discovery',page:1,count:21,fresh:true,max_bid:1000,min_buy:11000}),schema:2};
    const full=JSON.parse(JSON.stringify(await h.api.executeReadController(c)));
    assert(full.result.success,JSON.stringify(full));assert.equal(full.freshness.request_count,1);
    const row=full.result.auctions[0],t={trade_id:row.trade_id,item_id:row.item.item_id,definition_id:row.item.definition_id};
    const before=full.freshness.network_at;h.advance(age);
    const params={target:t,amount:500,minimum:500,cap:1000,deadline:'2030-01-01T00:03:00Z',
      status_read_id:c.id,batch_id:hex(100),decision_id:hex(101)};
    const count=h.calls.length;
    const bid=await h.execute(h.command('bid',params));assert(bid.success,JSON.stringify(bid));
    assert.equal(h.calls.length-count,1);assert.equal(h.calls.at(-1).method,'PUT');
    assert.equal(full.freshness.network_at,before,'never relabel observation time');
    const status=await h.execute(h.command('status_batch',{targets:[t]}));assert(status.success,JSON.stringify(status));
    assert.equal(status.links[0].full_read_id,c.id);assert.equal(status.links[0].full_observed_at,before);
    assert.equal(status.auctions[0].item.definition_id,0);
    h.setOptions({auction:{tradeState:'closed',bidState:'highest',expires:0,currentBid:500,isWon:()=>true}});
    const terminal=await h.execute(h.command('status_batch',{targets:[t]}));assert(terminal.success,JSON.stringify(terminal));
    assert.equal(terminal.auctions[0].native_is_won,true);
    const owned=await h.api.executeReadController({...h.command('owned_item',t),schema:2});
    assert(owned.result.success,JSON.stringify(owned));assert.equal(owned.freshness.request_count,1);
    assert.equal(owned.result.items[0].item_id,t.item_id);
  }
  // Local changed state prevents the old minimum being silently raised.
  const h=setup(1),c={...h.command('search',{purpose:'discovery',page:1,count:21,fresh:true,max_bid:1000,min_buy:11000}),schema:2};
  const full=await h.api.execute(c);assert(full.result.success);
  const row=full.result.auctions[0],t={trade_id:row.trade_id,item_id:row.item.item_id,definition_id:row.item.definition_id};
  h.raw[0].getAuctionData().currentBid=600;
  const n=h.calls.length;
  const result=await h.execute(h.command('bid',{target:t,amount:500,minimum:500,cap:1000,deadline:'2030-01-01T00:03:00Z',
    status_read_id:c.id,batch_id:hex(100),decision_id:hex(101)}));
  assert(!result.success);assert.equal(h.calls.length,n);
  assert((await h.execute(h.command('balance'))).success);
  // A shared-read timeout cannot poison unrelated later controller writes.
  for(const options of [{timeout:true},{zeroOwned:true},{delayedSend:true}]){
    const h=setup(1),c={...h.command('search',{purpose:'discovery',page:1,count:21,fresh:true,max_bid:1000,min_buy:11000}),schema:2};
    h.setOptions(options);const failed=await h.api.executeReadController(c);assert(!failed.result.success);
    const saved=JSON.stringify(failed);h.late.forEach(f=>f());assert.equal(JSON.stringify(failed),saved);
    assert.equal(h.queue.queue.length,0,'abandoned shared reads are removed from native queue');
    h.setOptions({});const full=await h.api.executeReadController({...c,id:hex(999)});assert(full.result.success,JSON.stringify(full));
    const row=full.result.auctions[0],t={trade_id:row.trade_id,item_id:row.item.item_id,definition_id:row.item.definition_id};
    const bid=await h.execute(h.command('bid',{target:t,amount:500,minimum:500,cap:1000,deadline:'2030-01-01T00:03:00Z',
      status_read_id:full.command_id,batch_id:hex(100),decision_id:hex(101)}));assert(bid.success,JSON.stringify(bid));
    const n=h.calls.length;
    const forbidden=await h.api.executeReadController({...c,id:hex(998),operation:'bid',params:{}});
    assert(!forbidden.result.success);assert.equal(h.calls.length,n,'read seam cannot authorize mutations');
  }
  console.log('PASS shared discovery, retained ages/full links, native bid and changed-state skip');
}
suite().catch(e=>{console.error(e);process.exitCode=1;});

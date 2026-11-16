'use strict';
// Shipped controller maintenance entry point with existing native-call fixtures.
const assert=require('node:assert/strict');
const {fixture:resale}=require('./resale_native_checks.cjs');
const {fixture:bulk}=require('./production_bulk_checks.cjs');
const native=require('./controller_followup_fixture.cjs');
(async()=>{
  const f=await resale(),q=native.resale(f),send=q.queue.send;
  let r=await f.h.api.executeReadController(f.h.command('move',f.params));
  assert(r.result.success,JSON.stringify(r));assert.deepEqual(f.writes,['move']);
  const pile=await f.read('transfer_list'),caps=await f.read('caps',{definition_id:7654321});
  const raw=f.h.sandbox.repositories.Item.getTransferItems()[0];raw.pile=f.h.sandbox.ItemPile.TRANSFER;raw.isStack=()=>false;
  r=await f.h.api.executeReadController(f.h.command('list',{...f.params,owned_read_id:pile.c.id,caps_read_id:caps.c.id}));
  assert(r.result.success,JSON.stringify(r));assert.deepEqual(f.writes,['move','list']);
  assert.equal(r.result.network.length,2,'native list keeps its existing status GET');
  for(const request of q.requests){assert.equal(request.count,1);assert.equal(request.send,request.originalSend);}
  assert.equal(q.queue.send,send);
  // A failed resale command is consumed without poisoning this document.
  const bad=await resale('paid');native.resale(bad);
  r=await bad.h.api.executeReadController(bad.h.command('move',bad.params));assert(!r.result.success);
  assert((await bad.h.api.executeReadController(bad.h.command('watched'))).result.success);
  assert.deepEqual(bad.writes,[]);
  for(const op of ['clear_sold','relist_all']){
    const f=await bulk(op),method=op==='clear_sold'?'clearSoldItems':'relistExpiredAuctions';
    const q=native.bulk(f,op),send=q.queue.send;
    r=await f.h.api.executeReadController(f.h.command(op,f.params));assert(r.result.success,JSON.stringify(r));
    assert.equal(f.calls.length,1);assert.equal(q.requests.filter(r=>r.operation===op).length,1);
    for(const request of q.requests){assert.equal(request.count,1);assert.equal(request.send,request.originalSend);}
    assert.equal(q.queue.send,send);
    assert.equal(r.result.network.length,op==='clear_sold'?3:1,'native bulk follow-up GETs preserved');
    const after=await f.h.execute(f.h.command('transfer_list'));assert(after.result.success && after.coverage.complete);
    assert(after.result.auctions.every(r=>op==='clear_sold'?r.trade_state!=='closed':r.trade_state==='active'));
    const n=f.calls.length;r=await f.h.api.executeReadController(f.h.command(op,f.params));assert(!r.result.success);assert.equal(f.calls.length,n);
  }
  console.log('PASS controller maintenance: same native methods/arguments and readbacks, one-shot queue ownership, cleanup, non-poisoning and no replay');
})().catch(e=>{console.error(e);process.exitCode=1;});

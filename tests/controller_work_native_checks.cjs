'use strict';
// Shipped controller maintenance entry point with existing native-call fixtures.
const assert=require('node:assert/strict');
const {fixture:resale}=require('./resale_native_checks.cjs');
const {fixture:bulk}=require('./production_bulk_checks.cjs');
function ownedQueue(h,methods){
  const requests=[],queue={queue:[],send(r){r.send();return r;}};
  h.sandbox.services.UTUtasRequestQueue=queue;
  for(const name of methods){const original=h.sandbox.services.Item[name];
    h.sandbox.services.Item[name]=function(...args){
      const request={send(){assert.equal(this.doRetry,false);assert.equal(this.doReauth,false);this.count=(this.count??0)+1;},abort(){this.aborted=true;}};
      request.original=request.send;requests.push(request);queue.send(request);
      return original.apply(this,args);
    };
  }
  return {requests,queue,send:queue.send};
}
(async()=>{
  const f=await resale(),q=ownedQueue(f.h,['move','list']);
  let r=await f.h.api.executeReadController(f.h.command('move',f.params));
  assert(r.result.success,JSON.stringify(r));assert.deepEqual(f.writes,['move']);
  const pile=await f.read('transfer_list'),caps=await f.read('caps',{definition_id:7654321});
  r=await f.h.api.executeReadController(f.h.command('list',{...f.params,owned_read_id:pile.c.id,caps_read_id:caps.c.id}));
  assert(r.result.success,JSON.stringify(r));assert.deepEqual(f.writes,['move','list']);
  for(const request of q.requests){assert.equal(request.count,1);assert.equal(request.send,request.original);}
  assert.equal(q.queue.send,q.send);
  // A failed resale command is consumed without poisoning this document.
  const bad=await resale('paid');ownedQueue(bad.h,['move']);
  r=await bad.h.api.executeReadController(bad.h.command('move',bad.params));assert(!r.result.success);
  assert((await bad.h.api.executeReadController(bad.h.command('watched'))).result.success);
  assert.deepEqual(bad.writes,[]);
  for(const op of ['clear_sold','relist_all']){
    const f=await bulk(op),method=op==='clear_sold'?'clearSoldItems':'relistExpiredAuctions';
    const q=ownedQueue(f.h,[method]);
    r=await f.h.api.executeReadController(f.h.command(op,f.params));assert(r.result.success,JSON.stringify(r));
    assert.equal(f.calls.length,1);assert.equal(q.requests.length,1);assert.equal(q.requests[0].count,1);
    assert.equal(q.requests[0].send,q.requests[0].original);assert.equal(q.queue.send,q.send);
    const after=await f.h.execute(f.h.command('transfer_list'));assert(after.result.success && after.coverage.complete);
    assert(after.result.auctions.every(r=>op==='clear_sold'?r.trade_state!=='closed':r.trade_state==='active'));
    const n=f.calls.length;r=await f.h.api.executeReadController(f.h.command(op,f.params));assert(!r.result.success);assert.equal(f.calls.length,n);
  }
  console.log('PASS controller maintenance: same native methods/arguments and readbacks, one-shot queue ownership, cleanup, non-poisoning and no replay');
})().catch(e=>{console.error(e);process.exitCode=1;});

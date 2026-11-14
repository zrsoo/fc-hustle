'use strict';
const assert=require('node:assert/strict');
const {fixture}=require('./production_bulk_checks.cjs');
(async()=>{
 for(const op of ['clear_sold','relist_all']){
  for(const mode of ['background-read','background-telemetry']){
   const f=await fixture(op,mode),c=f.h.command(op,f.params),r=await f.h.execute(c);
   assert(r.result.success,JSON.stringify(r));assert.equal(f.calls.length,1);
   assert.equal(r.result.network.filter(n=>n.method!=='GET').length,1);
   const trace=f.h.sandbox.window.__fcProductionDiagnosticsV1.get(c.id);
   assert(trace.some(r=>r.stage==='BACKGROUND_REQUEST'));
   assert(trace.some(r=>r.stage==='BACKGROUND_RESPONSE'));
   assert(!JSON.stringify(trace).includes('PRIVATE-NATIVE-CANARY'));
   assert(!(await f.h.execute(f.h.command(op,f.params))).result.success);
   assert.equal(f.calls.length,1);
  }
  for(const mode of ['duplicate','per-item','body','query','host','route']){
   const f=await fixture(op,mode),c=f.h.command(op,f.params),r=await f.h.execute(c);
   assert.equal(r.result.error,'bulk_contract_changed');
   const trace=f.h.sandbox.window.__fcProductionDiagnosticsV1.get(c.id);
   assert(trace.some(r=>r.stage==='BULK_REQUEST_BLOCKED' && ['body','query','route','duplicate'].includes(r.detail.violation)));
   assert(f.wire.filter(([m])=>m!=='GET').length<=1);
  }
 }
 console.log('PASS browser navigation and telemetry isolation; one mutation; blocked duplicate/write/body/query/host guards and sanitized diagnostics');
})().catch(e=>{console.error(e);process.exitCode=1;});

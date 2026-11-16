'use strict';
// Actual page and diagnostics implementation with explicit offline native/XHR
// doubles. These failures are test contracts, never live coverage evidence.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {setup}=require('./production_page_checks.cjs');
(async()=>{
  const h=setup('networkZero'),command=h.command('watched');
  const response=await h.execute(command);
  assert.equal(response.result.success,false);
  assert.equal(response.result.error,'service_failed');
  assert.equal(response.result.status,null);
  assert.equal(response.result.network.length,1);
  assert.equal(response.result.network[0].method,'GET');
  assert.equal(response.result.network[0].path,'/ut/game/fc27/watchlist');
  assert.equal(response.result.network[0].status,null);
  assert.equal(response.freshness.network_at,null);
  assert.equal(response.freshness.request_count,1);
  assert.equal(response.result.auctions,null);
  assert.equal(h.calls.length,1); // No automatic native retry.
  const diagnostics=h.sandbox.window.__fcProductionDiagnosticsV1.get(command.id);
  const event=diagnostics.find(r=>r.stage==='EA_RESPONSE');
  assert(event);assert.equal(event.detail.xhr_zero_status,true);
  assert(!Object.hasOwn(event.detail,'status'));
  assert(!JSON.stringify(diagnostics).includes('CREDENTIAL-CANARY'));
  const okay=setup(),good=await okay.execute(okay.command('watched'));
  assert.equal(good.result.success,true);assert.equal(good.result.network[0].status,200);
  if(process.argv.includes('--sample'))console.log(JSON.stringify({command,response,diagnostics}));
  else console.log('PASS network failure: absent HTTP status retained as null, explicit zero diagnostic, failed/unfresh, no retry or secret');
})().catch(e=>{console.error(e);process.exitCode=1;});

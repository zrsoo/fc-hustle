'use strict';
// Offline doubles only; these observations never enter live case evidence.
const assert=require('node:assert/strict');
const {setup}=require('./production_page_checks.cjs');
(async()=>{
 const samples=[];
 for(const [mode,group] of [['ambientSettings','SETTINGS'],['ambientUser','USER'],['ambientOther','OTHER']]){
  const h=setup(mode),command=h.command('balance'),response=await h.execute(command);
  assert.equal(response.result.success,false);assert.equal(response.result.error,'ambiguous_network');
  assert.equal(response.freshness.network_at,null);assert.equal(response.result.credits,null);
  assert.equal(response.result.network.length,2);assert.equal(h.calls.length,1);
  assert.equal(response.result.network[1].path,'/unexpected');
  const diagnostics=h.sandbox.window.__fcProductionDiagnosticsV1.get(command.id);
  const event=diagnostics.find(r=>r.stage==='UNCLASSIFIED_EA_REQUEST');
  assert(event);assert.deepEqual(JSON.parse(JSON.stringify(event.detail)),{method:'POST',route_group:group});
  assert(!JSON.stringify({response,diagnostics}).includes('CREDENTIAL-CANARY'));
  assert(!JSON.stringify(diagnostics).includes('opaque/'));
  assert(!JSON.stringify(diagnostics).includes('user/'));
  assert.equal(h.api.attach(command.context,command.fences),false); // Poisoned; no silent resume.
  samples.push({command,response,diagnostics});
 }
 const h=setup(),good=await h.execute(h.command('balance'));
 assert.equal(good.result.success,true);assert.equal(good.result.credits,90000);
 if(process.argv.includes('--sample'))console.log(JSON.stringify(samples));
 else console.log('PASS typed route groups; strict failed/unfresh overlap; no retry, unknown path, body or credential leakage');
})().catch(e=>{console.error(e);process.exitCode=1;});

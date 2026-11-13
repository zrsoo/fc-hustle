'use strict';
// Execute the shipped page. Controlled clocks identify each timing boundary.
const assert=require('node:assert/strict');
const {setup}=require('./production_page_checks.cjs');
(async()=>{
  const h=setup(),proto=h.sandbox.XMLHttpRequest.prototype,send=proto.send;
  proto.send=function(...args){h.advance(125);return send.apply(this,args);};
  const c=h.command('search',{purpose:'pricing',definition_id:7654321,page:1,count:21,fresh:true});
  const r=JSON.parse(JSON.stringify(await h.api.execute(c)));
  assert(r.result.success);
  assert.equal(r.timing.ea_rtt_ms,125);
  assert.equal(r.timing.native_helper_ms,0);
  assert.equal(r.timing.native_service_ms,133);
  const control=h.sandbox.UTCurrencyInputControl;
  for(const name of ['getIncrementAboveVal','getIncrementBelowVal']){
    const f=control[name];control[name]=function(v){h.advance(3);return f.call(this,v);};
  }
  const hc=h.command('price_helpers',{version:1,probes:[{direction:'above',value:750},{direction:'below',value:1500}]});
  const hr=JSON.parse(JSON.stringify(await h.api.execute(hc)));
  assert(hr.result.success);
  assert.deepEqual(hr.timing,{native_service_ms:6,ea_rtt_ms:0,native_helper_ms:6});
  assert.equal(hr.freshness.request_count,0);
  process.stdout.write(JSON.stringify([{command:c,response:r},{command:hc,response:hr}]));
})().catch(e=>{console.error(e);process.exitCode=1;});

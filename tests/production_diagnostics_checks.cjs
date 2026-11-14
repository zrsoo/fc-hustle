'use strict';
const {setup,pricing}=require('./production_page_checks.cjs');
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
 const h=setup('broad'),c=h.command('search',{purpose:'discovery',page:1,count:21,fresh:true,max_bid:1000,min_buy:11000});
 const r=await h.execute(c);assert(r.result.success);
 const trace=h.sandbox.window.__fcProductionDiagnosticsV1.get(c.id);
 for(const stage of ['PAGE_ENTER','NATIVE_INVOKE','NATIVE_CALLBACK','EA_RESPONSE','NATIVE_DATA','PAGE_FINISHED'])assert(trace.some(r=>r.stage===stage),stage);
 const broken=setup('wrongVersion'),bc=broken.command('search',pricing);
 assert(!(await broken.execute(bc)).result.success);
 assert(broken.sandbox.window.__fcProductionDiagnosticsV1.get(bc.id).some(r=>r.stage==='PAGE_FAILURE'&&r.detail.error==='schema_unrecognized'));
 const sandbox=vm.createContext({window:{}});vm.runInContext(fs.readFileSync('browser/production-v1/diagnostics.js','utf8'),sandbox);
 const api=sandbox.window.__fcProductionDiagnosticsV1,id='a'.repeat(32);
 api.record(id,'PAGE_FAILURE',{error:'schema_unrecognized',error_class:'TypeError',password:'SECRET',definition_type:'SECRET',status:200});
 for(let i=0;i<100;i++)api.record(id,'PAGE_ENTER');
 assert.equal(api.get(id).length,64);assert(!JSON.stringify(api.get(id)).includes('SECRET'));
 api.record(id,'UNKNOWN_SECRET_STAGE');assert.equal(api.get(id).length,64);
 console.log('PASS diagnostics: executed page stages, failure, bounded typed allowlist, no raw secret retention');
})().catch(e=>{console.error(e);process.exitCode=1;});

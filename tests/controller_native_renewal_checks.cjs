'use strict';
// Captured native renewal methods + shipped bridge. No network, auth state or credentials.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {nativeScene}=require('./controller_balance_native_checks.cjs');
const {setup,seed}=require('./controller_native_checks.cjs');
const {setup:sharedSetup}=require('./production_page_checks.cjs');
const capture=JSON.parse(fs.readFileSync('docs/research/005/stage11/current-public-native-renewal-contract.json','utf8'));

function renewalScene({nativeDefault=true,renewalSuccess=true,otherEnvironment=false}={}){
  const {h}=nativeScene(90000),b=h.sandbox;let expired=true,renewals=0,telemetry=0,sends=0;
  b._0x512d02=()=>{throw Error('unresolved captured native lookup');};b.AuthEnvironment={UTAS:'UTAS'};b.HttpStatusCode={UNAUTHORIZED:401};
  b.JSUtils.isObject=v=>v!==null && typeof v==='object';
  const immediate=(v,other=false)=>({observe(owner,callback){
    if(other)callback.call(owner,{unobserve(){}},{success:true,response:{environment:'NUCLEUS'}});
    callback.call(owner,{unobserve(){}},v);}});
  const delegate={authenticate(environment){assert.equal(environment,'UTAS');renewals++;
    if(renewalSuccess)expired=false;return immediate({success:renewalSuccess,response:{environment:'UTAS'}},otherEnvironment);},
    requestTelemetry(){telemetry++;return immediate({success:true});}};
  const requests=[];
  b.UTHttpRequest=class extends b.EAObservable{
    constructor(){super();this.authDelegate=delegate;this.doReauth=nativeDefault;this.doRetry=true;
      this.originalSend=this.send;this.originalObserve=this.observe;this.originalRenewal=this._handleReauth;requests.push(this);}
    setPath(path){this.path=path;}
    send(){sends++;this.sends=(this.sends??0)+1;assert.equal(this.sends,1,'never replay original request');assert.equal(this.doRetry,false);
      const x=new b.XMLHttpRequest();x.status=expired?401:200;this.http={status:x.status};
      x.responseType='json';x.response={currencies:[{name:'COINS',funds:90000}],unopenedPacks:{preOrderPacks:0,recoveredPacks:0}};
      x.open('GET','https://utas.test.ea.com'+this.path);x.setRequestHeader('X-UT-SID','CANARY');x.send();
      if(expired)this._handleFail();else this.notify({success:true,status:200,response:x.response});}
    _notify(){this.notify({success:false,status:401,error:{code:401}});}
    abort(){}
  };
  for(const [key,source]of Object.entries(capture.methods))b.UTHttpRequest.prototype[key]=vm.runInContext('('+source+')',b);
  return {h,requests,counts:()=>({renewals,telemetry,sends})};
}

async function suite(){
  let cases=0;
  // The failed read stays failed, native renewal updates only the synthetic session,
  // and the next independently journaled read proves recovery. No original replay.
  const s=renewalScene(),command=s.h.command('balance'),first=await s.h.execute(command);
  assert.equal(first.success,false);assert.equal(first.status,401);assert.equal(first.credits,null);
  assert.deepEqual(s.counts(),{renewals:1,telemetry:1,sends:1});
  const trace=s.h.sandbox.window.__fcProductionDiagnosticsV1.get(command.id).filter(r=>r.stage==='NATIVE_RENEWAL_RESULT');
  assert.equal(trace.length,1);assert.equal(trace[0].detail.success,true);
  assert.equal(s.requests[0]._handleReauth,s.requests[0].originalRenewal,'restore the native renewal callback');
  const next=await s.h.execute(s.h.command('balance'));assert(next.success);assert.equal(next.credits,90000);
  assert.deepEqual(s.counts(),{renewals:1,telemetry:1,sends:2});cases++;
  for(const nativeDefault of [false,null]){
    // A native opt-out or non-true flag is never turned on by the bridge.
    const scene=renewalScene({nativeDefault});
    const r=await scene.h.execute(scene.h.command('balance'));assert(!r.success);assert.equal(scene.counts().renewals,0);cases++;
  }
  const failed=renewalScene({renewalSuccess:false});assert(!(await failed.h.execute(failed.h.command('balance'))).success);
  assert.deepEqual(failed.counts(),{renewals:1,telemetry:0,sends:1});cases++;
  const other=renewalScene({otherEnvironment:true,renewalSuccess:false}),otherCommand=other.h.command('balance');
  assert(!(await other.h.execute(otherCommand)).success);
  const completions=other.h.sandbox.window.__fcProductionDiagnosticsV1.get(otherCommand.id).filter(r=>r.stage==='NATIVE_RENEWAL_RESULT');
  assert.equal(completions.length,1);assert.equal(completions[0].detail.success,false);
  assert.deepEqual(other.counts(),{renewals:1,telemetry:0,sends:1});cases++;
  for(const options of [{},{http:461,service:403}]){
    const h=setup(1),prior=await seed(h);h.setOptions({...options,doReauthDefault:true});
    const bid=await h.execute(h.command('bid',{target:prior.targets[0],amount:500,minimum:500,cap:1000,
      deadline:new Date(Date.parse(prior.v.observed_at)+200000).toISOString(),status_read_id:prior.v.command_id,batch_id:'b'.repeat(32),decision_id:'d'.repeat(32)}));
    const request=h.requests.at(-1);assert.equal(request.doReauth,false);assert.equal(request.doRetry,false);
    if(options.http)assert.equal(bid.success,false);else assert(bid.success);cases++;
  }
  for(const op of ['search','watched','unassigned','caps']){
    const h=sharedSetup(),q=h.enableControllerQueue({defaultReauth:true});
    const params=op==='search'?{purpose:'pricing',page:1,count:21,fresh:true,definition_id:7654321,max_buy:10000}:op==='caps'?{definition_id:7654321}:{};
    const r=await h.api.executeReadController(h.command(op,params));assert(r.result.success,JSON.stringify(r));
    assert(q.requests.length);for(const request of q.requests){assert.equal(request.doReauth,true);assert.equal(request.doRetry,false);assert.equal(request.count,1);}cases++;
  }
  console.log('PASS '+cases+' native renewal cases: read failure retained, next read recovery, native opt-out, renewal failure, no replay or mutation renewal');
}
if(require.main===module)suite().catch(e=>{console.error(e);process.exitCode=1;});
module.exports={suite};

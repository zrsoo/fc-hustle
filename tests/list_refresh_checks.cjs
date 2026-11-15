'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {fixture}=require('./resale_native_checks.cjs');
const samples=[];
(async()=>{
 for(const mode of ['ok','background','wrong-trade','duplicate-read','duplicate-write','foreign-write','wrong-host','read-body']){
  const f=await fixture();
  assert((await f.h.execute(f.h.command('move',f.params))).result.success);
  const before=await f.read('transfer_list'),caps=await f.read('caps',{definition_id:7654321});
  const original=f.h.sandbox.services.Item.list;
  f.h.sandbox.services.Item.list=(...args)=>({observe(owner,cb){
   original(...args).observe(owner,(sender,result)=>{
    function wire(method,path,query={},body){
     const xhr=new f.h.sandbox.XMLHttpRequest();
     xhr.open(method,'https://'+(mode==='wrong-host'?'other.invalid':'utas.test.ea.com')+'/ut/game/fc27/'+path+'?'+new URLSearchParams(query));
     xhr.setRequestHeader('X-UT-SID','PRIVATE-LIST-REFRESH-CANARY');xhr.send(body);
    }
    const raw=f.h.sandbox.repositories.Item.getTransferItems()[0];
    const id=raw.getAuctionData().tradeId;
    if(mode==='duplicate-write')wire('POST','auctionhouse');
    else if(mode==='foreign-write')wire('PUT','item');
    else{
     wire('GET','trade/status/lite',{tradeIds:mode==='wrong-trade'?'999999':id},mode==='read-body'?'unexpected':undefined);
     if(mode==='duplicate-read')wire('GET','trade/status/lite',{tradeIds:id});
     if(mode==='background')wire('GET','objective/progress',{private:'PRIVATE-LIST-REFRESH-CANARY'});
    }
    cb(sender,result);
   });
  },unobserve(){}});
  const c=f.h.command('list',{...f.params,owned_read_id:before.c.id,caps_read_id:caps.c.id});
  const v=await f.h.execute(c);
  if(['ok','background'].includes(mode)){
   assert(v.result.success,JSON.stringify(v));assert.equal(v.freshness.request_count,2);
   assert.equal(v.result.network[1].path,'/ut/game/fc27/trade/status/lite');
   assert.deepEqual(v.result.network[1].query,{item_id:c.params.item_id});
   assert(!JSON.stringify(v).includes('PRIVATE-LIST-REFRESH-CANARY'));
   samples.push({command:c,response:v,now:f.h.now()});
  }else{assert(!v.result.success,mode);assert.equal(v.result.network.filter(n=>n.method==='POST').length,1);}
  assert.deepEqual(f.writes,['move','list']);
 }
 if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify({evidence_class:'OFFLINE_DOUBLE',samples}));
 console.log('PASS exact post-list native refresh, redaction, auxiliary count and no duplicate/wrong mutation handoff');
})().catch(e=>{console.error(e);process.exitCode=1;});

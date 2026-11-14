'use strict';
const {setup,pricing}=require('./production_page_checks.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const samples=[];
 for(const [mode,ok,error] of [['metadata',true,null],['metadataWrongVersion',false,'schema_unrecognized'],
  ['metadataDuplicate',false,'ambiguous_network'],['unknownRead',false,'ambiguous_network'],
  ['unexpectedWrite',false,'ambiguous_network'],['fanout',false,'ambiguous_network']]){
  const h=setup(mode),c=h.command('search',pricing),r=await h.execute(c);
  assert.equal(r.result.success,ok,mode);assert.equal(r.result.error,error,mode);
  assert.equal(r.freshness.request_count,r.result.network.length);
  assert.equal(h.calls.filter(x=>x==='search').length,1);
  if(ok){
   assert.equal(r.result.network.length,2);
   assert.equal(r.result.network[1].path,'/ut/game/fc27/attributes/metadata');
   assert.deepEqual(r.result.network[1].query,{defIds:[7654321]});
   assert.equal(r.result.auctions[0].item.definition_id,7654321);
  }
  samples.push({command:c,response:r,now:h.now()});
 }
 if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(samples));
 console.log('PASS native metadata fanout: two truthful GETs, exact version correlation, duplicate/unknown/write rejection, single dispatch');
})().catch(e=>{console.error(e);process.exitCode=1;});

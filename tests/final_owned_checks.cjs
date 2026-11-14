'use strict';
// Native page VM only. Never invokes Edge, EA, or the live evidence collector.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {setup}=require('./production_page_checks.cjs');
(async()=>{
 const h=setup(),samples=[];
 h.setAuction({tradeState:'closed',bidState:'highest',currentBid:7700,expires:-1,isWon:()=>true});
 let calls=0;
 h.sandbox.services.Item.requestItemsById=ids=>{
   calls++;assert.deepEqual(Array.from(ids),['10000000000000000001']);
   return h.response('owned_item',{items:[h.raw()]},{idList:'10000000000000000001'});
 };
 const watched=h.command('watched'),w=await h.execute(watched),a=w.result.auctions[0];
 samples.push({command:watched,response:w,now:h.now()});
 const c=h.command('owned_item',{trade_id:a.trade_id,item_id:a.item.item_id,definition_id:a.item.definition_id});
 const r=await h.execute(c);assert(r.result.success,JSON.stringify(r));assert.equal(calls,1);
 assert.equal(r.result.items[0].item_id,a.item.item_id);assert.equal(r.result.items[0].last_sale_price,7700);
 assert.deepEqual(r.result.network[0].query,{item_id:a.item.item_id});
 assert.equal(r.result.network[0].method,'GET');assert.equal(r.result.network[0].path,'/ut/game/fc27/item');
 assert(!JSON.stringify(r).includes('10000000000000000001'));
 samples.push({command:c,response:r,now:h.now()});
 const wrong=h.command('owned_item',{...c.params,item_id:'item:'+'a'.repeat(24)});
 assert(!(await h.execute(wrong)).result.success);assert.equal(calls,1);
 const notWon=setup();let unwonCalls=0;notWon.sandbox.services.Item.requestItemsById=()=>{unwonCalls++;throw Error('must not query unowned candidate');};
 const v=await notWon.execute(notWon.command('watched')),row=v.result.auctions[0];
 assert(!(await notWon.execute(notWon.command('owned_item',{trade_id:row.trade_id,item_id:row.item.item_id,definition_id:row.item.definition_id}))).result.success);
 assert.equal(unwonCalls,0);
 if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify({evidence_class:'OFFLINE_DOUBLE',samples}),{flag:'wx'});
 console.log('PASS exact won-item lookup: fresh retained selector, one independent GET, private IDs redacted, unwon/wrong identity rejected');
})().catch(e=>{console.error(e);process.exitCode=1;});

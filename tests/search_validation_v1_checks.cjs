'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const source=fs.readFileSync('experiments/search_validation_v1/browser/page.js','utf8');
async function run(params,options={}){
 const wire=[{tradeId:'1234567890123',startingBid:150,currentBid:950,buyNowPrice:10500,expires:60,tradeState:'active',bidState:'outbid',itemData:{id:'123456789',definitionId:42,assetId:9,rareflag:1,untradeable:false}}];
 let calls=0,criteria,page;
 class XHR{constructor(){this.events={};this.status=200;this.responseText=JSON.stringify({auctionInfo:options.empty?[]:wire});}open(m,u){}setRequestHeader(n,v){}addEventListener(k,f){this.events[k]=f;}send(){this.events.loadend();}}
 const native=(options.empty?[]:wire).map(a=>({...a.itemData,getAuctionData:()=>a,getPriceLimits:()=>({minimum:150,maximum:20000})}));
 const context={window:{__fcDiscoveryPersonaFollowupV1:{inspect:()=>({accepted:true,selected_platform:'pc'})}},crypto:webcrypto,TextEncoder,URL,location:{protocol:'https:',hostname:'www.ea.com',pathname:'/ea-sports-fc/ultimate-team/web-app/',href:'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/'},performance,Date,setTimeout,clearTimeout,XMLHttpRequest:XHR,UTSearchCriteriaDTO:class{},services:{Item:{clearTransferMarketCache(){},searchTransferMarket(c,p){calls++;criteria=c;page=p;return {observe(owner,cb){const x=new XHR();x.open('GET',`https://utas.mob.v1.ea.com/ut/game/fc27/transfermarket?macr=1000&minb=10500&start=${p===1?0:20}&num=21&secret=discard`);x.setRequestHeader('X-UT-SID','NEVER_EXPORT');x.send();cb(null,{success:true,status:200,data:{items:native,hasMore:!options.empty}});}};}}}};
 const original={open:XHR.prototype.open,send:XHR.prototype.send,header:XHR.prototype.setRequestHeader};
 vm.runInNewContext(source,context);
 const out=await context.window.__fcSearchValidationV3.read({id:'a'.repeat(32),evidence_key:'b'.repeat(32),params});
 assert.equal(XHR.prototype.open,original.open);assert.equal(XHR.prototype.send,original.send);assert.equal(XHR.prototype.setRequestHeader,original.header);
 assert.ok(!JSON.stringify(out).includes('NEVER_EXPORT'));assert.ok(!JSON.stringify(out).includes('secret'));
 return {out,calls,criteria,page};
}
(async()=>{
 const p={page:1,count:21,max_bid:1000,min_buy:10500};const {out,calls,criteria}=await run(p);
 assert.equal(calls,1);assert.equal(criteria.maxBid,1000);assert.equal(criteria.minBuy,10500);assert.equal(out.network[0].query.macr,1000);assert.equal(out.network[0].query.minb,10500);
 assert.equal(out.rows[0].current_bid,950);assert.equal(out.rows[0].starting_bid,150);assert.equal(out.rows[0].buy_now_price,10500);
 for(const key of ['trade_id','item_id','definition_id','starting_bid','current_bid','buy_now_price'])assert.equal(out.rows[0][key],out.wire_rows[0][key]);
 assert.match(out.rows[0].trade_id,/^trade:[a-f0-9]{24}$/);
 const empty=await run(p,{empty:true});assert.equal(empty.out.rows.length,0);assert.equal(empty.out.wire_rows.length,0);assert.equal(empty.out.success,true);
 const second=await run({...p,page:2});assert.equal(second.page,2);assert.equal(second.out.network[0].query.start,20);
 const exact=await run({page:1,count:21,definition_id:42,max_buy:1000});assert.equal(exact.criteria.defId[0],42);assert.equal(exact.criteria.maxBuy,1000);
 for(const bad of [{...p,page:3},{...p,max_bid:true},{...p,password:123},{...p,definition_id:0}]){const r=await run(bad);assert.equal(r.calls,0);assert.equal(r.out.success,false);}
 console.log('PASS search DTO mapping, paging, independent wire projection, empty results, privacy, fail-closed inputs, hook restoration');
})().catch(e=>{console.error(e);process.exitCode=1;});

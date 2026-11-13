// Native browser adapter behavior under explicit simulated EA responses.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const source=fs.readFileSync('browser/e2e-live-v2/page.js','utf8');
let writes=0,reads=0;
const auction={tradeId:'123456789012345',startingBid:700,currentBid:0,buyNowPrice:10500,expires:100,tradeState:'active',bidState:'none'};
const raw={id:'123456789',definitionId:261855,tradable:true,getAuctionData:()=>auction};
class XHR{open(method,url){this.method=method;this.url=url;}setRequestHeader(){}addEventListener(_,cb){this.cb=cb;}send(){this.status=200;this.responseText=JSON.stringify({auctionInfo:[]});this.cb?.();}}
function native(path,data,amount=null){return {observe(owner,cb){const xhr=new XHR();xhr.open(path.includes('/bid')?'PUT':'GET','https://utas.external.ea.com/ut/game/fc27/'+path);xhr.setRequestHeader('X-UT-SID','fixture-never-retained');xhr.send(amount===null?null:JSON.stringify({bid:amount}));queueMicrotask(()=>cb(null,{success:true,status:200,data}));},unobserve(){}};}
const ctx={console,crypto:webcrypto,TextEncoder,URL,Date,Map,Set,Object,Number,String,Array,Promise,performance,setTimeout,clearTimeout,queueMicrotask,XMLHttpRequest:XHR,location:{protocol:'https:',hostname:'www.ea.com',pathname:'/ea-sports-fc/ultimate-team/web-app/'},window:{__fcDiscoveryPersonaFollowupV1:{inspect:()=>({accepted:true})}},UTSearchCriteriaDTO:class{},UTCurrencyInputControl:{getIncrementAboveVal:v=>v+(v<1000?50:100),PRICE_TIERS:[]},ItemPile:{INBOX:1},repositories:{Item:{setDirty(){}}},services:{Item:{clearTransferMarketCache(){},searchTransferMarket(){reads++;return native('transfermarket',{items:[raw]});},requestWatchedItems(){reads++;return native('watchlist',{items:[raw]});},bid(item,amount){assert.equal(item,raw);assert.ok([700,750].includes(amount));writes++;return native('trade/123456789012345/bid',{},amount);}}}};
vm.createContext(ctx);vm.runInContext(source,ctx);
const api=ctx.window.__fcE2ELiveV2,owner='a'.repeat(32),boot='b'.repeat(32),key='c'.repeat(32);
api.attach({owner,boot});let n=0;
const cmd=(operation,params={})=>({id:(++n).toString(16).padStart(32,'0'),boot,owner,evidence_key:key,operation,params});
(async()=>{
 const initial=await api.execute(cmd('search',{max_bid:1000,min_buy:10500}));assert.equal(initial.success,true);const a=initial.rows[0];
 const params={item_id:a.item_id,trade_id:a.trade_id,definition_id:261855,amount:700,cap:1500};
 let r=await api.execute({...cmd('bid',params),owner:'0'.repeat(32)});assert.equal(r.success,false);assert.equal(writes,0);
 r=await api.execute(cmd('bid',{...params,amount:750}));assert.equal(r.success,false);assert.equal(writes,0);
 const opening=cmd('bid',params);r=await api.execute(opening);assert.equal(r.success,true);assert.equal(writes,1);assert.equal(r.network.length,1);assert.equal(r.network[0].bid_amount,700);
 r=await api.execute(opening);assert.equal(r.success,false);assert.equal(writes,1);
 auction.currentBid=700;auction.bidState='highest';await api.execute(cmd('watched'));
 r=await api.execute(cmd('bid',{...params,amount:750}));assert.equal(r.success,false);assert.equal(writes,1);
 auction.bidState='outbid';await api.execute(cmd('watched'));
 r=await api.execute(cmd('bid',{...params,amount:750,cap:700}));assert.equal(r.success,false);assert.equal(writes,1);
 r=await api.execute(cmd('bid',{...params,amount:750}));assert.equal(r.success,true);assert.equal(writes,2);assert.equal(r.network[0].bid_amount,750);
 auction.expires=0;await api.execute(cmd('watched'));
 r=await api.execute(cmd('bid',{...params,amount:750}));assert.equal(r.success,false);assert.equal(writes,2);
 assert.equal(reads,4);console.log('PASS: native opening, HOLD zero writes, minimum rebid, cap, expiry, duplicate and owner fences (SIMULATION ONLY)');
})().catch(e=>{console.error(e);process.exitCode=1;});

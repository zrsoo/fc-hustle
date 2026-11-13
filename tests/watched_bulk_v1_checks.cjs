/* Real page probe in a VM, synthetic native services; no live requests. */
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),{webcrypto}=require('node:crypto');
const secret='DO_NOT_EXPORT_AUTH_VALUE';
function setup(mode='network',count=0){
 class XHR {
  constructor(){this.status=200;this.responseType='';this.responseText=JSON.stringify({auctionInfo:[],untrusted:secret});this.listeners=[];}
  open(method,url){this.method=method;this.url=url;}
  setRequestHeader(){}
  addEventListener(name,cb){if(name==='loadend')this.listeners.push(cb);}
  send(){setTimeout(()=>this.listeners.forEach(cb=>cb()),0);}
 }
 const original={...Object.fromEntries(['open','send','setRequestHeader'].map(k=>[k,XHR.prototype[k]]))};
 let calls=0;
 const context=vm.createContext({console,URL,TextEncoder,crypto:webcrypto,performance,setTimeout,clearTimeout,XMLHttpRequest:XHR,
  location:{protocol:'https:',hostname:'www.ea.com',pathname:'/en-gb/ea-sports-fc/ultimate-team/web-app/'},window:{},
  GamePlatform:{PC:'PC'},ItemPile:{INBOX:5},UTServerSettingsRepository:{KEY:{PLATFORM_SPLIT_FOR_TRANSFER_MARKET:'split',TRANSFER_TARGET_SIZE:'capacity'}},
  repositories:{Item:{getPileSize:()=>30,getWatchedItems:()=>[],isDirty:()=>false,setDirty(p){assert.equal(p,5);}},ServerSettings:{getSettingByKey:()=>30}},
  services:{Configuration:{checkFeatureEnabled:()=>false},User:{getUser:()=>({getSelectedPersona:()=>({platform:'PC',isPC:true})})},Item:{requestWatchedItems(){
   calls++;
   if(mode!=='cached'){
    const x=new XHR();if(mode==='failed')x.status=500;
    x.open('GET','https://utas.mob.v1.ea.com/ut/game/fc27/'+(mode==='other'?'newroute':'watchlist')+'?secret='+secret);
    x.setRequestHeader('X-UT-SID',secret);x.send();
   }
   return {observe(owner,cb){setTimeout(()=>cb(null,{status:mode==='cached'?304:mode==='failed'?500:200,success:mode!=='failed',
    response:{items:Array.from({length:count},(_,n)=>({id:String(900000+n),definitionId:123,
     getAuctionData:()=>({tradeId:String(800000+n),currentBid:150,startingBid:150,buyNowPrice:20000,expires:90+n,bidState:n%2?'outbid':'highest',tradeState:'active'})}))}}),0);}};
  }}}});
 for(const f of ['persona.js','page.js'])vm.runInContext(fs.readFileSync('experiments/watched_bulk_v1/browser/'+f,'utf8'),context);
 return {context,original,XHR,get calls(){return calls;},read:op=>context.window.__fcWatchedBulkV2.read({operation:op,id:'a'.repeat(32),evidence_key:'b'.repeat(32)})};
}
async function run(mode,count){
 const s=setup(mode,count),r=JSON.parse(JSON.stringify(await s.read('watched')));
 for(const k of Object.keys(s.original))assert.equal(s.XHR.prototype[k],s.original[k],'hooks restored');
 assert(!JSON.stringify(r).includes(secret),'auth/query/native extra field leak');
 return {s,r};
}
(async()=>{
 let {r,s}=await run('network',0);assert.equal(s.calls,1);assert.equal(r.schema,2);assert(r.cache_invalidated);assert.equal(r.account.inbox_capacity,30);assert.equal(r.request_count,1);assert(r.network_at);assert.equal(r.network[0].route,'/ut/game/fc27/watchlist');assert(r.network[0].payload_bytes>0);assert.deepEqual(r.auctions,[]);
 const paced=await s.read('watched');assert.equal(paced.error,'experiment_pacing');assert.equal(s.calls,1);
 ({r}=await run('cached',0));assert.equal(r.status,304);assert(r.success);assert.equal(r.request_count,0);assert.equal(r.network_at,null);
 ({r}=await run('failed',0));assert(!r.success);assert.equal(r.error,'service_failed');assert.equal(r.network_at,null);
 ({r}=await run('other',0));assert.equal(r.network[0].route,'/ut/game/fc27/:unrecognized');assert.equal(r.network_at,null);
 ({r}=await run('network',50));assert.equal(r.auctions.length,50);assert.equal(r.request_count,1);assert.equal(new Set(r.auctions.map(a=>a.trade_id)).size,50);assert(r.auctions.every(a=>/^item:[a-f0-9]{24}$/.test(a.item_id)));
 ({r}=await run('network',201));assert.equal(r.error,'schema_unrecognized');assert(!r.success);
 s=setup();s.context.location.hostname='untrusted.example';r=await s.read('watched');assert.equal(r.error,'wrong_page');assert.equal(s.calls,0);
 s=setup();r=await s.read('bid');assert.equal(r.error,'invalid_command');assert.equal(s.calls,0);
 console.log('watched bulk page: network, cache, failure, unknown route, 50 rows, privacy, bounds, pacing and read-only guards passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

'use strict';
// Execute shipped adapter/page code. Only native observable, queue and XHR are synthetic.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
const hex=n=>n.toString(16).padStart(32,'0'),ctx={account:hex(1),persona:hex(2),identity_namespace:hex(3),game:'fc27',platform:'pc'};
const samples=[];
function setup(count=10){
  let sequence=10,options={},persona={platform:'PC',isPC:true,name:'Fixture PC alias'},now=Date.parse('2030-01-01T00:00:00Z');
  const user={getSelectedPersona:()=>persona},calls=[],requests=[],late=[];
  for(const k of ['token','sid','credentials'])Object.defineProperty(user,k,{get(){throw Error('secret accessed');}});
  class Clock extends Date{constructor(...a){super(...(a.length?a:[now]));}static now(){return now;}}
  class XHR{
    constructor(){this.listeners=[];this.status=200;}
    open(method,url){this.method=method;this.url=url;}
    setRequestHeader(){}
    addEventListener(_,f){this.listeners.push(f);}
    removeEventListener(_,f){this.listeners=this.listeners.filter(x=>x!==f);}
    send(body){calls.push({method:this.method,url:this.url,body});for(const f of [...this.listeners])f();}
  }
  const originals={open:XHR.prototype.open,send:XHR.prototype.send,header:XHR.prototype.setRequestHeader};
  const raw=Array.from({length:count},(_,i)=>{let a={tradeId:String(20000000000000000000n+BigInt(i+1)),startingBid:500,currentBid:0,
    buyNowPrice:15000,expires:300,tradeState:'active',bidState:'none',isValid:()=>true,isStale:()=>false,isWon:()=>false};
    return {id:String(10000000000000000000n+BigInt(i+1)),definitionId:700000+i,untradeable:false,getAuctionData:()=>a,setAuctionData:value=>{a=value;}};});
  const queue={queue:[],currentRequests:[],send(request){
    requests.push(request);
    if(options.delayedSend){this.queue.push({request});return request;}
    if(options.queueDelay){setTimeout(()=>{background();request.send();request.release?.();},0);return request;}
    request.send();return request;
  }};
  const background=()=>{const x=new XHR();x.open('GET','https://utas.test.ea.com/ut/game/fc27/trade/status/lite?tradeIds=PRIVATE');x.setRequestHeader('X-UT-SID','CANARY');x.send();};
  function response(op,items,input,amount){
    const o={...options};
    let callback,nativeResponse;
    const request={doReauth:o.doReauthDefault,doRetry:true,send(){
      const x=new XHR();x.status=o.http??200;x.responseText=JSON.stringify(op==='balance'?
        (Object.hasOwn(o,'balanceWire')?o.balanceWire:{currencies:[{name:'COINS',funds:o.balanceAmount??90000}]}):
        (o.wire??{auctionInfo:o.empty?[]:items,code:o.rejection?402:null}));
      if(o.responseType==='json'){x.responseType='json';x.response=JSON.parse(x.responseText);}
      if(o.responseType==='arraybuffer'){x.responseType='arraybuffer';x.response=new TextEncoder().encode(x.responseText).buffer;}
      const path=op==='status_batch'?'trade/status/lite?tradeIds='+input.map(x=>x.getAuctionData().tradeId).join(','):
        op==='bid'?'trade/'+input.getAuctionData().tradeId+'/bid':op==='watched'?'watchlist':
        op==='search'?'transfermarket?start=0&num=21&macr=1000&minb=11000':
        op==='owned_item'?'item?idList='+input[0]:'user/credits';
      x.open(o.method??(op==='bid'?'PUT':'GET'),o.url??'https://utas.test.ea.com/ut/game/fc27/'+path);
      if(!o.noAuth)x.setRequestHeader('X-UT-SID','CANARY');
      x.send(op==='bid'?JSON.stringify(o.body??{bid:amount}):undefined);
      if(o.retry)request.send();
    },abort(){this.aborted=true;},observe(owner,cb){callback=cb;
      const done=()=>{if(o.interleave)background();if(o.switchPersona)persona={platform:'PC',isPC:true};now+=8;
        cb({unobserve(){}},nativeResponse);};
      if(o.timeout || o.delayedSend)late.push(done);else if(o.queueDelay)request.release=done;else if(o.async)setTimeout(done,0);else done();
      o.onObserve?.();
    },unobserve(){}};
    let rows=o.empty || o.rejection?[]:items;
    if(op==='status_batch'){
      rows=(o.empty?[]:items).map(x=>({...x,definitionId:Object.hasOwn(o,'version')?o.version:0,getAuctionData:()=>({...x.getAuctionData(),...(o.auction??{})})}));
      if(o.partial)rows=rows.slice(0,1);if(o.duplicate)rows=[rows[0],rows[0]];
      if(o.wrongItem)rows[0]={...rows[0],id:'999'};
      if(o.unexpected){const base=rows[0];rows[0]={...base,getAuctionData:()=>({...base.getAuctionData(),tradeId:'999'})};}
      if(o.malformed)rows=[null];
    }
    nativeResponse={success:!o.rejection,status:o.http??200,
      ...(op==='balance'?{data:Object.hasOwn(o,'balanceData')?o.balanceData:{coins:{type:'COINS',amount:o.balanceAmount??90000,value(){return this.amount;}}}}:
        {response:o.data??{items:rows}}),error:o.rejection?{code:402}:undefined};
    request.originalSend=request.send;request.originalObserve=request.observe;
    if(!o.zeroOwned)queue.send(request);
    return request;
  }
  const services={User:{getUser:()=>user,requestCurrencies:()=>response('balance')},UTUtasRequestQueue:queue,Item:{
    itemDao:{searchTransferMarket:q=>response('search',raw),getItemDataById:ids=>response('owned_item',raw.filter(r=>ids.includes(r.id)),ids),
      getWatchPile:()=>response('watched',raw)},
    clearTransferMarketCache(){},
    searchTransferMarket(q,page){assert.equal(q.type,'player');assert.equal(q.count,21);assert.equal(page,1);
      assert.equal(q.maxBid,1000);assert.equal(q.minBuy,11000);return this.itemDao.searchTransferMarket(q);},
    requestItemsById(ids){return this.itemDao.getItemDataById(ids);},
    requestWatchedItems(){return this.itemDao.getWatchPile();},transfersDao:{
      getAuctionData(items){assert(items.length<=10);assert(items.every(x=>raw.includes(x)));return response('status_batch',items,items);},
      bid(input,amount){const accepted={...input,getAuctionData:()=>({...input.getAuctionData(),bidState:'highest',currentBid:amount})};
        return response('bid',options.empty?[]:[accepted],input,amount);}
    },bid(input,amount){return this.transfersDao.bid(input,amount);}
  }};
  const originalQueue=queue.send,originalBid=services.Item.transfersDao.bid;
  const sandbox=vm.createContext({window:{},crypto:webcrypto,TextEncoder,TextDecoder,URL,services,Date:Clock,
    performance:{now:()=>now},XMLHttpRequest:XHR,UTSearchCriteriaDTO:class{},repositories:{Item:{setDirty(){},isPileFull:()=>options.watchFull===true,
      getPileSize:()=>50,getWatchedItems:()=>raw}},ItemPile:{INBOX:1},GamePlatform:{PC:'PC'},GameCurrency:{COINS:'COINS'},
    UTCurrencyInputControl:{getIncrementAboveVal:v=>v+100,getIncrementBelowVal:v=>Math.max(0,v-100)},UtasErrorCode:{NOT_ENOUGH_CREDIT:402},
    location:{protocol:'https:',hostname:'www.ea.com',pathname:'/ea-sports-fc/ultimate-team/web-app/',href:'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/'},
    setTimeout:(fn,delay)=>setTimeout(fn,delay===15000?20:delay),clearTimeout});
  for(const file of ['persona.js','diagnostics.js','controller.js','page.js'])vm.runInContext(fs.readFileSync('browser/production-v1/'+file,'utf8'),sandbox);
  const api=sandbox.window.__fcProductionV1,fences={owner:hex(4),epoch:1,host_epoch:hex(5),worker_epoch:hex(6),document:api.document};
  assert(api.attach(ctx,fences));
  const command=(operation,params={})=>({schema:4,id:hex(++sequence),operation,params,context:{...ctx},fences:{...fences}});
  async function execute(c){const result=JSON.parse(JSON.stringify(await api.executeController(c)));
    assert.equal(XHR.prototype.open,originals.open);assert.equal(XHR.prototype.send,originals.send);assert.equal(XHR.prototype.setRequestHeader,originals.header);
    assert.equal(queue.send,originalQueue);assert.equal(services.Item.transfersDao.bid,originalBid);
    for(const request of requests){assert.equal(request.send,request.originalSend);assert.equal(request.observe,request.originalObserve);}
    assert(!JSON.stringify(result).includes('CANARY'));assert(!JSON.stringify(result).includes('20000000000000000001'));
    samples.push({command:c,response:result,now:new Clock().toISOString()});return result;
  }
  return {sandbox,api,fences,command,execute,calls,raw,requests,late,queue,setOptions:o=>{options=o;},advance:n=>{now+=n;}};
}
const targets=v=>v.auctions.map(r=>({trade_id:r.trade_id,item_id:r.item.item_id,definition_id:r.item.definition_id}));
async function seed(h){const v=await h.execute(h.command('watched'));assert(v.success,JSON.stringify(v));return {v,targets:targets(v)};}
async function suite(){
  let h=setup(),seeded=await seed(h),t=seeded.targets;
  const count=h.calls.length;
  let c=h.command('status_batch',{targets:t}),r=await h.execute(c);
  assert(r.success,JSON.stringify(r));assert.equal(h.calls.length-count,1);assert.equal(r.network.length,1);assert.equal(r.auctions.length,10);
  assert.equal(new URL(h.calls.at(-1).url).searchParams.get('tradeIds'),h.raw.map(x=>x.getAuctionData().tradeId).join(','));
  assert(r.links.every(x=>!x.version_observed && x.full_read_id===seeded.v.command_id));assert.equal(r.auctions[0].item.definition_id,0);
  assert((await h.execute(h.command('balance'))).success);
  // Identity is the explicitly bound native object, not its display name.
  // Execute the captured official array DAO unchanged, with synthetic native dependencies.
  h=setup();t=(await seed(h)).targets;
  const b=h.sandbox;
  b.EAObservable=class{notify(v){this.value=v;}observe(owner,cb){cb(this,this.value);}unobserve(){}};
  b.UTHttpResponseDTO=class{};b.GAME_NAME='fc27';b.DebugUtils={Assert:v=>assert(v)};
  b.JSUtils={assignPropertyValues:(a,b)=>Object.assign(b,a),isObject:v=>v && typeof v==='object'};
  b.factories={Item:{generateItemsFromAuctionData:rows=>rows}};
  b.UTHttpRequest=class extends b.EAObservable{
    constructor(){super();this.originalSend=this.send;this.originalObserve=this.observe;}
    setPath(path){this.path=path;}setUrlVariables(query){this.query=query;}
    send(){assert.equal(this.cache,false);const x=new b.XMLHttpRequest();x.open('GET','https://utas.test.ea.com'+this.path+'?'+new URLSearchParams(this.query));
      x.setRequestHeader('X-UT-SID','CANARY');x.send();
      this.notify({success:true,status:200,response:{auctionInfo:h.raw.map(r=>({...r,definitionId:0}))}});
    }abort(){}
  };
  b.services.Item.transfersDao.requestDelegate=b.services.UTUtasRequestQueue;
  b.services.Item.transfersDao.getAuctionData=vm.runInContext('('+JSON.parse(fs.readFileSync('docs/research/001c/001c-06-resume-01/source-contract.json','utf8')).function_source+')',b);
  r=await h.execute(h.command('status_batch',{targets:t}));assert(r.success,JSON.stringify(r));assert.equal(r.auctions.length,10);assert.equal(r.network.length,1);
  for(const version of [null,undefined,t[0].definition_id]){
    h=setup(1);t=(await seed(h)).targets;h.setOptions({version:version===700000?t[0].definition_id:version});
    r=await h.execute(h.command('status_batch',{targets:t}));assert(r.success,JSON.stringify(r));
  }
  for(const options of [{partial:true},{empty:true}]){
    h=setup();t=(await seed(h)).targets;h.setOptions(options);r=await h.execute(h.command('status_batch',{targets:t}));
    assert(r.success);assert.equal(r.missing.length,options.partial?9:10);assert.equal(r.links.length,options.partial?1:0);
  }
  for(const options of [{duplicate:true},{wrongItem:true},{unexpected:true},{version:99},{version:false},{version:'0'},{malformed:true},{data:{}},
    {auction:{currentBid:-1}},{auction:{bidState:'mystery'}},{url:'https://utas.test.ea.com/ut/game/fc27/trade/status/lite?tradeIds=999'},
    {url:'https://utas.test.ea.com/ut/game/fc27/watchlist'},{method:'PUT'},{noAuth:true},{http:401},{zeroOwned:true},{retry:true},{switchPersona:true}]){
    h=setup();t=(await seed(h)).targets;h.setOptions(options);r=await h.execute(h.command('status_batch',{targets:t}));assert(!r.success,JSON.stringify(options));
    h.setOptions({});if(!options.switchPersona)assert((await h.execute(h.command('balance'))).success,'new mode poisoned');
  }
  for(const change of [ts=>[],ts=>[...ts,ts[0]],ts=>ts.map((t,i)=>i? t:{...t,item_id:'item:'+'e'.repeat(24)}),ts=>ts.map((t,i)=>i?t:{...t,definition_id:99})]){
    h=setup();t=(await seed(h)).targets;const before=h.calls.length;r=await h.execute(h.command('status_batch',{targets:change(t)}));assert(!r.success);assert.equal(h.calls.length,before);
  }
  h=setup();t=(await seed(h)).targets;h.raw[0].id='999';r=await h.execute(h.command('status_batch',{targets:t}));assert.equal(r.error,'known_identity_unavailable');
  h=setup();t=(await seed(h)).targets;h.setOptions({interleave:true,async:true});r=await h.execute(h.command('status_batch',{targets:t}));
  assert(r.success);assert.equal(r.network.length,1);assert.equal(r.background.length,1);
  h.setOptions({queueDelay:true});r=await h.execute(h.command('status_batch',{targets:t}));
  assert(r.success);assert.equal(r.network.length,1);assert.equal(r.background.length,1,'delayed request owns its XHR, earlier background does not');
  h.setOptions({interleave:true,zeroOwned:true});r=await h.execute(h.command('status_batch',{targets:t}));assert(!r.success);assert.equal(r.network.length,0);assert.equal(r.background.length,1);
  for(const options of [{timeout:true},{delayedSend:true}]){
    h=setup();t=(await seed(h)).targets;h.setOptions(options);r=await h.execute(h.command('status_batch',{targets:t}));assert.equal(r.error,'service_timeout');
    const before=JSON.stringify(r);h.late.forEach(f=>f());assert.equal(JSON.stringify(r),before);assert.equal(h.queue.queue.length,0);
    h.setOptions({async:true});const next=h.execute(h.command('balance'));h.late.forEach(f=>f());assert((await next).success);
  }
  h=setup();t=(await seed(h)).targets;let started;const observed=new Promise(r=>{started=r;});h.setOptions({timeout:true,onObserve:started});const running=h.execute(h.command('status_batch',{targets:t}));
  await observed;h.api.interruptController();assert.equal((await running).error,'interrupted');
  h.late.forEach(f=>f());h.setOptions({});assert((await h.execute(h.command('balance'))).success);
  // Explicit scope/epoch failure before any request, and mapping loss on reattach.
  h=setup();t=(await seed(h)).targets;c=h.command('status_batch',{targets:t});c.context.persona=hex(99);assert(!(await h.execute(c)).success);
  const old=h.command('status_batch',{targets:t});h.fences.epoch++;assert(h.api.attach(ctx,h.fences));assert(!(await h.execute(old)).success);
  assert.equal((await h.execute(h.command('status_batch',{targets:t}))).error,'known_identity_unavailable');
  // Actual native bid receipt, exact body, zero-owned and unknown paths remain non-blocking.
  for(const options of [{},{empty:true},{timeout:true},{rejection:true,http:403},{body:{bid:999}},{body:{bid:500,extra:true}},{zeroOwned:true}]){
    h=setup(1);const full=await seed(h);t=full.targets;
    const params={target:t[0],amount:500,minimum:500,cap:1000,deadline:'2030-01-01T00:03:00Z',status_read_id:full.v.command_id,batch_id:hex(77),decision_id:hex(78)};
    c=h.command('bid',params);h.setOptions(options);r=await h.execute(c);
    if(!Object.keys(options).length){assert(r.success,JSON.stringify(r));assert.equal(r.receipt.verdict,'ACCEPTED');
      h.raw[0].getAuctionData().bidState='highest';h.raw[0].getAuctionData().currentBid=500;
      h.advance(1);
      assert((await h.execute(h.command('status_batch',{targets:t}))).success);
    }
    else if(options.rejection){assert.equal(r.receipt.verdict,'REJECTED');assert.equal(r.error,'bid_rejected');}
    else assert(!r.success);
    const before=h.calls.length;assert(!(await h.execute(c)).success);assert.equal(h.calls.length,before);
    h.late.forEach(f=>f());h.setOptions({});assert((await h.execute(h.command('balance'))).success);
  }
  for(const version of [0,null]){
    h=setup(1);const full=await seed(h);t=full.targets;
    h.setOptions({version,auction:{currentBid:600,bidState:'outbid'}});
    const status=await h.execute(h.command('status_batch',{targets:t}));assert(status.success);
    assert.equal(full.v.auctions[0].current_bid,0,'original full response is unchanged');
    assert.equal(status.auctions[0].item.definition_id,version,'original lite version is unchanged');
    assert.equal(h.raw[0].definitionId,t[0].definition_id,'retained current DTO keeps full version');
    assert.equal(h.raw[0].getAuctionData().currentBid,600,'genuine returned auction is attached to current DTO');
    h.setOptions({});
    r=await h.execute(h.command('bid',{target:t[0],amount:700,minimum:700,cap:1000,deadline:'2030-01-01T00:03:00Z',
      status_read_id:status.command_id,batch_id:hex(777),decision_id:hex(778)}));
    assert(r.success,JSON.stringify(r));assert.equal(r.receipt.before_bid_state,'outbid');assert.equal(r.receipt.verdict,'ACCEPTED');
  }
  h=setup(1);t=(await seed(h)).targets;delete h.raw[0].setAuctionData;
  r=await h.execute(h.command('status_batch',{targets:t}));assert(!r.success);assert.equal(r.error,'known_identity_unavailable');
  assert((await h.execute(h.command('balance'))).success);
  if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(samples));
  console.log('PASS controller native contracts: actual page, ten targets, ownership, versions, cleanup, receipts and no replay');
}
if(require.main===module)suite().catch(e=>{console.error(e);process.exitCode=1;});
module.exports={setup,seed,targets,hex,ctx,suite};

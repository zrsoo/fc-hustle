'use strict';
// Real production page code in a VM; native DTO/service/XHR doubles only.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const secret='CREDENTIAL-CANARY-DO-NOT-RETAIN',hex=n=>n.toString(16).padStart(32,'0');
const ctx={account:hex(1),persona:hex(2),game:'fc27',platform:'pc',identity_namespace:hex(3)};
const samples=[];
function setup(mode='ok'){
  let time=Date.parse('2030-01-01T00:00:00Z'),sequence=10,persona={platform:'PC',isPC:true},captured=null;
  const events=[],timers=[],calls=[];
  class Clock extends Date{constructor(...args){super(...(args.length?args:[time]));}static now(){return time;}}
  class XHR{
    constructor(){this.listeners=[];this.status=mode==='http401'?401:200;}
    open(m,u){} setRequestHeader(n,v){} // Never retain secret values.
    addEventListener(e,f){assert.equal(e,'loadend');this.listeners.push(f);}
    send(){for(const f of this.listeners)f();}
  }
  const originals={open:XHR.prototype.open,header:XHR.prototype.setRequestHeader,send:XHR.prototype.send};
  const raw=()=>({id:'10000000000000000001',definitionId:mode==='wrongVersion'?999999:7654321,untradeable:false,lastSalePrice:7700,
    private:secret,getAuctionData:()=>({tradeId:'20000000000000000001',startingBid:2500,currentBid:0,buyNowPrice:15000,expires:300,tradeState:'active',bidState:'none',isWon:()=>false})});
  function response(op,data,query={}){
    calls.push(op);events.push(op);
    return {observe(owner,cb){
      if(mode==='timeout')return;
      const done=()=>{
        if(mode!=='cache'){
          const path={balance:mode==='currencies'?'user/currencies':'user/credits',watched:'watchlist',search:'transfermarket',unassigned:'purchased/items',transfer_list:'tradepile',caps:'marketdata/pricelimits',status:'trade/status/lite',bid:'trade/20000000000000000001/bid'}[op];
          const wire=()=>{const x=new XHR();x.open(op==='bid'?'PUT':'GET','https://utas.test.ea.com/ut/game/fc27/'+path+'?'+new URLSearchParams({...query,private:secret}));
            if(mode!=='noAuth')x.setRequestHeader('X-UT-SID',secret);x.send();};
          wire();if(mode==='fanout')wire();
        }
        time+=mode==='stale'?31000:8;
        if(mode==='switchDuring')persona={platform:'PC',isPC:true};
        cb({unobserve(){}},mode==='http401'?{success:false,status:401,error:{message:secret}}:{success:true,status:200,[['caps','status'].includes(op)?'response':'data']:mode==='malformed'?{session:secret}:data});
      };
      if(mode==='deferred')setTimeout(done,5);else done();
    },unobserve(){}};
  }
  const user={getSelectedPersona:()=>persona};
  for(const name of ['credentials','sid','token','cookies'])Object.defineProperty(user,name,{get(){throw Error('secret field touched');}});
  const services={User:{getUser:()=>user,requestCurrencies:()=>response('balance',{credits:90000})},Item:{
    clearTransferMarketCache(){events.push('clear');},
    searchTransferMarket(q,page){
      captured={...q,...(q.defId===undefined?{}:{defId:Array.from(q.defId)}),page};
      if(mode==='broad')assert.equal(q.defId,undefined);else assert.deepEqual(Array.from(q.defId),[7654321]);
      assert.equal(q.count,21);assert.equal(page,1);assert.equal(q.type,'player');
      const wire={start:0,num:21};if(q.defId!==undefined)wire.definitionId=q.defId[0];
      if(q.maxBid!==undefined)wire.macr=q.maxBid;if(q.minBuy!==undefined)wire.minb=q.minBuy;
      if(q.maxBuy!==undefined)wire[mode==='wrongMaxBuy'?'macr':'maxb']=q.maxBuy;
      // Native maxBuy is inclusive: include the equality row in the response.
      const rows=[raw()];if(mode==='broad')rows.push({...raw(),id:'10000000000000000002',definitionId:7654322,
        getAuctionData:()=>({...raw().getAuctionData(),tradeId:'20000000000000000002'})});
      return response('search',{items:rows,hasMore:false},wire);
    },
    requestWatchedItems:()=>response('watched',{items:[raw()],hasMore:false}),
    requestUnassignedItems:()=>response('unassigned',{items:[raw()]}),
    requestTransferItems:()=>response('transfer_list',{items:[raw()]}),
    transfersDao:{getItemMarketDataByDefId(ids){assert.deepEqual(Array.from(ids),[7654321]);return response('caps',{marketData:[{defId:7654321,priceLimits:{minimum:150,maximum:50000}}]},{defId:7654321});}},
    bid(raw,amount){assert.equal(amount,2500);return response('bid',{});}
  }};
  const sandbox=vm.createContext({window:{},services,crypto:webcrypto,TextEncoder,URL,GamePlatform:{PC:'PC'},
    // Fixture reproduces the retained official helper formulas, including rounding.
    UTCurrencyInputControl:{
      PRICE_TIERS:[{min:100000,inc:1000},{min:50000,inc:500},{min:10000,inc:250},{min:1000,inc:100},{min:150,inc:50},{min:0,inc:150}],
      getIncrementAboveVal(v){const t=this.PRICE_TIERS.find(t=>v>=t.min);return v+ t.inc<15000000?Math.round((v+t.inc)/t.inc)*t.inc:15000000;},
      getIncrementBelowVal(v){if(v<=0)return 0;const t=this.PRICE_TIERS.find(t=>v>t.min);return v-t.inc>0?Math.round((v-t.inc)/t.inc)*t.inc:0;}
    },
    location:{protocol:'https:',hostname:'www.ea.com',pathname:'/ea-sports-fc/ultimate-team/web-app/',href:'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/'},
    Date:Clock,performance:{now:()=>time},XMLHttpRequest:XHR,UTSearchCriteriaDTO:function(){},
    repositories:{Item:{setDirty(pile){events.push('dirty:'+pile);}}},ItemPile:{INBOX:1,PURCHASED:2,TRANSFER:3},
    setTimeout(fn,delay){timers.push(delay);return setTimeout(fn,delay===15000?25:0);},clearTimeout});
  for(const file of ['persona.js','page.js'])vm.runInContext(fs.readFileSync('browser/production-v1/'+file,'utf8'),sandbox);
  const api=sandbox.window.__fcProductionV1;
  const fences={owner:hex(4),epoch:1,host_epoch:hex(5),worker_epoch:hex(6),document:api.document};
  assert(api.attach(ctx,fences));
  const command=(operation,params={})=>({schema:2,id:hex(++sequence),operation,params,context:{...ctx},fences:{...fences}});
  async function execute(c){
    const r=JSON.parse(JSON.stringify(await api.execute(c)));
    assert(!JSON.stringify(r).includes(secret));assert(!JSON.stringify(r).includes('10000000000000000001'));assert(!JSON.stringify(r).includes('20000000000000000001'));
    for(const [k,n]of [['open','open'],['header','setRequestHeader'],['send','send']])assert.equal(XHR.prototype[n],originals[k]);
    return r;
  }
  return {api,command,execute,sandbox,fences,events,calls,timers,response,raw,get captured(){return captured;},now:()=>new Clock().toISOString(),advance:ms=>{time+=ms;},switchPersona:p=>{persona=p;}};
}
const pricing={purpose:'pricing',definition_id:7654321,page:1,count:21,fresh:true};
const discovery={...pricing,purpose:'discovery',max_bid:1000,min_buy:11000};
if(require.main===module)(async()=>{
  const wide=setup('broad'),broad=wide.command('search',{purpose:'discovery',page:1,count:21,fresh:true,max_bid:1000,min_buy:11000});
  const wideResult=await wide.execute(broad);assert(wideResult.result.success,JSON.stringify(wideResult));
  assert.deepEqual(wideResult.result.network[0].query,{start:0,num:21,macr:1000,minb:11000});
  assert.deepEqual(wideResult.result.auctions.map(a=>a.item.definition_id),[7654321,7654322]);
  assert.equal((await wide.execute(wide.command('search',{purpose:'pricing',page:1,count:21,fresh:true}))).result.error,'invalid_command');
  let h=setup();
  for(const [op,params,field] of [['search',discovery,'auctions'],['search',pricing,'auctions'],['search',{...pricing,max_buy:15000},'auctions'],
    ['watched',{},'auctions'],['balance',{},'credits'],['unassigned',{},'items'],['transfer_list',{},'auctions'],['caps',{definition_id:7654321},'caps']]){
    const c=h.command(op,params),r=await h.execute(c);assert(r.result.success,JSON.stringify(r));assert(r.result[field]!==null);
    assert.equal(r.freshness.request_count,1);assert.equal(r.freshness.read_id,c.id);assert.equal(r.fences.document,h.api.document);
    samples.push({command:c,response:r,now:h.now()});
  }
  assert.deepEqual(h.captured,{type:'player',defId:[7654321],count:21,maxBuy:15000,page:1});
  const second=samples[2].response;assert.equal(second.result.network[0].query.maxb,15000);assert.equal(second.result.auctions[0].buy_now_price,15000);
  assert(!Object.hasOwn(second.result.network[0].query,'macr'));assert(!Object.hasOwn(second.result.network[0].query,'minb'));
  assert.equal(samples[4].response.result.network[0].path,'/ut/game/fc27/user/credits');
  for(const [dirty,op]of [['dirty:1','watched'],['dirty:2','unassigned'],['dirty:3','transfer_list']])assert.equal(h.events[h.events.indexOf(op)-1],dirty);
  // Arbitrary card/version and >1000 bid survive the production native route.
  const sc=h.command('watched'),bc=h.command('balance');
  const s={command:sc,response:await h.execute(sc),now:h.now()},b={command:bc,response:await h.execute(bc),now:h.now()};
  samples.push(s,b);const a=s.response.result.auctions[0];
  const bid=h.command('bid',{trade_id:a.trade_id,item_id:a.item.item_id,definition_id:a.item.definition_id,amount:2500,minimum:2500,cap:9000,
    deadline:'2030-01-01T00:01:00Z',status_read_id:s.command.id,balance_read_id:b.command.id});
  let r=await h.execute(bid);assert(r.result.success);samples.push({command:bid,response:r,now:h.now()});
  r=await h.execute(bid);assert(!r.result.success);assert.equal(h.calls.filter(x=>x==='bid').length,1);
  // Mismatched ownership, complete context, schema, worker/host/document epochs.
  h=setup();const before=h.calls.length;
  for(const k of ['account','persona','game','platform','identity_namespace']){
    const c=h.command('balance');c.context[k]=k==='game'?'fc26':k==='platform'?'ps5':hex(99);
    assert.equal((await h.execute(c)).result.error,'invalid_command');
  }
  for(const k of Object.keys(h.fences)){
    const c=h.command('balance');c.fences[k]=k==='epoch'?0:hex(99);
    assert.equal((await h.execute(c)).result.error,'invalid_command');
  }
  for(const c of [{...h.command('balance'),schema:1},{...h.command('balance'),secret},h.command('balance',{secret}),
    h.command('search',{...pricing,max_bid:1000}),h.command('search',{...pricing,max_buy:0}),h.command('search',{...pricing,page:2}),h.command('search',{...pricing,count:20}),h.command('search',{...discovery,min_buy:10500}),h.command('move',{}),
    {...bid,id:hex(999),operation:'toString',fences:h.fences}])assert.equal((await h.execute(c)).result.error,'invalid_command');
  assert.equal(h.calls.length,before);
  assert(!h.api.attach(ctx,{...h.fences,worker_epoch:hex(99)}));
  h.switchPersona({platform:'PSN',isPC:false});assert.equal((await h.execute(h.command('balance'))).result.error,'persona_unverified');assert.equal(h.calls.length,before);
  // Same platform, different selected persona object also fails.
  h=setup();h.switchPersona({platform:'PC',isPC:true});assert.equal((await h.execute(h.command('balance'))).result.error,'persona_unverified');assert.equal(h.calls.length,0);
  for(const [mode,error]of [['cache','ambiguous_network'],['currencies','ambiguous_network'],['fanout','ambiguous_network'],['noAuth','unauthenticated'],['http401','service_failed'],
    ['malformed','schema_unrecognized'],['wrongVersion','schema_unrecognized'],['wrongMaxBuy','schema_unrecognized'],['switchDuring','persona_unverified'],['stale','stale_source'],['timeout','service_timeout']]){
    h=setup(mode);const c=h.command(mode==='wrongVersion'||mode==='wrongMaxBuy'?'search':'balance',mode==='wrongVersion'||mode==='wrongMaxBuy'?{...pricing,max_buy:15000}:{});
    r=await h.execute(c);assert.equal(r.result.error,error,mode);assert(!r.result.success);
    if(mode==='timeout'){assert(h.timers.includes(15000));assert.equal((await h.execute(h.command('balance'))).result.error,'bridge_busy');}
  }
  h=setup('deferred');const pending=h.api.execute(h.command('balance'));
  assert.equal((await h.api.execute(h.command('balance'))).result.error,'bridge_busy');assert((await pending).result.success);assert.equal(h.calls.length,1);
  h=setup();h.sandbox.window.__fcDurablePageV1={};assert(!h.api.attach(ctx,h.fences));
  // A different namespace produces different pseudonyms; no stable ID inference.
  h=setup();const first=await h.execute(h.command('watched'));
  const h2=setup(),other={...ctx,identity_namespace:hex(999)};
  // A new page gets an explicit new context, never rebind an existing namespace.
  assert(!h2.api.attach(other,h2.fences));
  const nativeId='10000000000000000001';
  const digest=async key=>'item:'+Buffer.from(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(key+'|item|'+nativeId))).toString('hex').slice(0,24);
  assert.equal(first.result.auctions[0].item.item_id,await digest(ctx.identity_namespace));
  assert.notEqual(await digest(ctx.identity_namespace),await digest(other.identity_namespace));
  if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(samples));
  console.log('PASS production page: routes, DTO/wire, inclusive maxb, ownership, persona, freshness, ambiguity, timeout, >1000 guarded bid, no secrets');
})().catch(e=>{console.error(e);process.exitCode=1;});
module.exports={setup,pricing,ctx,hex};

"use strict";
// Shipped page and captured official untarget/DAO methods, wholly synthetic XHR.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {setup,hex}=require('./controller_native_checks.cjs');
const methods=JSON.parse(fs.readFileSync('docs/research/005/stage14/public-watch-contract.json','utf8')).methods;
async function fixture(mode='ok'){
  const h=setup(3),b=h.sandbox;let removed=[];
  for(let i=0;i<3;i++)Object.assign(h.raw[i].getAuctionData(),{watched:true,tradeState:i<2?'closed':'active',bidState:i<2?'outbid':'none',expires:i<2?-1:300,isWon:()=>false});
  b._0x16df02=()=>{throw Error('unreviewed_decoder');};
  b.EAObservable=class{notify(v){this.value=v;this.ready=true;}observe(owner,cb){if(this.ready)cb(this,this.value);return this;}unobserve(){}};
  b.UTServiceResponseDTO=class{};b.UTHttpResponseDTO=class{};b.HttpRequestMethod={DELETE:'DELETE'};b.HttpStatusCode={BAD_REQUEST:400};b.GAME_NAME='fc27';b.TradeAccessLevel={BANNED:4};b.UtasErrorCode.LOCKED_TRANSFER_MARKET=487;
  b.JSUtils={valToArray:v=>Array.isArray(v)?v:[v],isObject:v=>v!==null&&typeof v==='object',assignPropertyValues:(a,c)=>Object.assign(c,a)};
  b.DebugUtils={Assert:v=>assert(v)};b.AppNotification={ITEM_UNWATCH:'UNWATCH'};b.getDefaultDispatcher=()=>({notify(){}});
  b.UTHttpRequest=class extends b.EAObservable{
    constructor(){super();this.doRetry=true;this.doReauth=true;this.originalSend=this.send;this.originalObserve=this.observe;}
    setPath(p){this.path=p;}setUrlVariables(v){this.query=v;}
    send(){
      assert.equal(this.doRetry,false);assert.equal(this.doReauth,false);
      const x=new b.XMLHttpRequest();x.status=mode==='denied'?403:200;
      let query=new URLSearchParams(this.query).toString();if(mode==='wrong_query')query+='&tradeId=999';
      x.open(mode==='wrong_method'?'PUT':this.requestType,'https://utas.test.ea.com'+(mode==='wrong_path'?'/ut/game/fc27/item':this.path)+'?'+query);
      if(mode!=='no_auth')x.setRequestHeader('X-UT-SID','CREDENTIAL-CANARY');
      x.send(mode==='body'?'unexpected':undefined);
      this.notify({success:mode!=='denied',status:x.status,error:mode==='denied'?{code:461}:undefined,response:{}});
    }
    abort(){}
  };
  b.services.Item.transfersDao.requestDelegate=b.services.UTUtasRequestQueue;
  b.services.Item.transfersDao.unwatchItems=vm.runInContext('('+methods.unwatchItems+')',b);
  b.services.Item.removeItems=r=>{removed.push(r.id);const i=h.raw.indexOf(r);if(i>=0)h.raw.splice(i,1);};
  b.services.Item.untarget=vm.runInContext('('+methods.untarget+')',b);
  const c={...h.command('watched'),schema:2};const before=await h.api.executeReadController(c);assert.equal(before.result.success,true,JSON.stringify(before));
  const targets=before.result.auctions.filter(r=>r.trade_state==='closed').map(r=>({trade_id:r.trade_id,item_id:r.item.item_id,definition_id:r.item.definition_id}));
  const command=h.command('clear_lost',{targets,before_read_id:c.id});
  return {h,b,before,command,removed};
}
(async()=>{
  let n=0;
  let f=await fixture();let before=f.h.calls.length,r=await f.h.execute(f.command);
  assert.equal(r.success,true,JSON.stringify({r,before:f.before,params:f.command.params}));assert.equal(r.network.length,1);assert.equal(r.network[0].method,'DELETE');assert.equal(r.network[0].targets.length,2);
  assert.equal(f.removed.length,2);assert.equal(f.h.raw.length,1);assert.equal(f.h.raw[0].getAuctionData().tradeState,'active');
  assert.equal(f.h.calls.length,before+1);assert.equal(r.receipt,null);assert.equal(r.auctions.length,0);n++;
  const count=f.h.calls.length;r=await f.h.execute({...f.command,id:hex(999)});assert.equal(r.success,false);assert.equal(f.h.calls.length,count);n++;
  for(const mode of ['wrong_query','wrong_method','wrong_path','body','no_auth','denied']){
    f=await fixture(mode);r=await f.h.execute(f.command);assert.equal(r.success,false,mode);assert.equal(f.removed.length,0);assert.equal(f.h.raw.length,3);n++;
  }
  for(const mode of ['stale','partial','winner','active','foreign_read','not_watched']){
    f=await fixture();before=f.h.calls.length;
    if(mode==='stale')f.h.advance(31001);
    if(mode==='partial')f.command.params.targets.pop();
    if(mode==='winner')f.h.raw[0].getAuctionData().isWon=()=>true;
    if(mode==='active')f.h.raw[0].getAuctionData().tradeState='active';
    if(mode==='foreign_read')f.command.params.before_read_id=hex(555);
    if(mode==='not_watched')f.h.raw[0].getAuctionData().watched=false;
    r=await f.h.execute(f.command);assert.equal(r.success,false,mode);assert.equal(f.h.calls.length,before,mode);assert.equal(f.removed.length,0);n++;
  }
  console.log('PASS '+n+' native lost-target contracts: captured methods, exact DELETE, no retry/renewal/replay or unrelated deletion');
})().catch(e=>{console.error(e);process.exitCode=1;});

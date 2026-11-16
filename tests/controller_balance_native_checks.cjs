'use strict';
// Shipped bridge + captured official DAO/service/VO; only HTTP/observable/user are fixtures.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {setup}=require('./controller_native_checks.cjs');
const contract=JSON.parse(fs.readFileSync('docs/research/004/bridge-audit/native-currency-contract.json','utf8'));
function nativeScene(funds=54321){
  const h=setup(1),b=h.sandbox,user=b.services.User.getUser(),values=new Map();
  b.GameCurrency={COINS:'COINS',POINTS:'POINTS',DRAFT_TOKEN:'DRAFT_TOKEN'};
  b.a0_0x351b=b.a0_0x3d0bf6=b._0x40544c=b._0x250f6e=()=>{throw Error('unresolved_static_projection');};
  b.EAObject=function(){};
  b.__extends=(child,parent)=>{child.prototype=Object.create(parent.prototype);child.prototype.constructor=child;};
  b.UTCurrencyVO=vm.runInContext('('+contract.methods.currencyVOFactory+')(EAObject)',b);
  for(const type of Object.values(b.GameCurrency))values.set(type,new b.UTCurrencyVO(type,type==='COINS'?17:0));
  user.getCurrency=type=>values.get(type);
  user.setCurrency=(type,amount)=>values.set(type,new b.UTCurrencyVO(type,amount));
  b.EAObservable=class {
    notify(value){this.ready=true;this.value=value;for(const [owner,cb]of this.listeners??[])cb(this,value);}
    observe(owner,cb){if(this.ready)cb(this,this.value);else (this.listeners??=[]).push([owner,cb]);return this;}
    unobserve(owner){this.listeners=(this.listeners??[]).filter(([o])=>o!==owner);}
  };
  b.UTServiceResponseDTO=class{};b.UTHttpResponseDTO=class{};b.GAME_NAME='fc27';
  b.DebugUtils={Assert:value=>assert(value)};
  b.JSUtils={isValid:v=>v!=null,isObject:v=>v!==null&&typeof v==='object',assignPropertyValues:(a,z)=>Object.assign(z,a)};
  b.UTHttpRequest=class extends b.EAObservable {
    constructor(){super();this.originalSend=this.send;this.originalObserve=this.observe;}
    setPath(value){this.path=value;}
    send(){
      assert.equal(this.doRetry,false);assert.equal(this.doReauth,false);
      const response={currencies:[{name:'COINS',funds},{name:'POINTS',funds:0},{name:'DRAFT_TOKEN',funds:0}],
        unopenedPacks:{preOrderPacks:0,recoveredPacks:0}};
      const x=new b.XMLHttpRequest();x.status=200;x.responseType='json';x.response=response;
      x.open('GET','https://utas.test.ea.com'+this.path);x.setRequestHeader('X-UT-SID','CANARY');x.send();
      this.notify({success:true,status:200,response});
    }
    abort(){}
  };
  const service=b.services.User;
  service.userDao={requestDelegate:b.services.UTUtasRequestQueue,
    getCurrencies:vm.runInContext('('+contract.methods.getCurrencies+')',b)};
  service.processCurrencyUpdate=(u,type,amount)=>u.setCurrency(type,amount);
  service.requestCurrencies=vm.runInContext('('+contract.methods.requestCurrencies+')',b);
  return {h,user};
}
async function suite(){
  let cases=0;
  for(const amount of [0,54321]){
    const {h,user}=nativeScene(amount),before=h.calls.length;
    assert.equal(user.getCurrency('COINS').value(),17);
    const result=await h.execute(h.command('balance'));assert(result.success,JSON.stringify(result));
    assert.equal(result.credits,amount);assert.equal(user.getCurrency('COINS').value(),amount);
    assert.equal(h.calls.length-before,1);assert.equal(result.network.length,1);cases++;
  }
  for(const responseType of ['text','json','arraybuffer']){
    const h=setup(1);h.setOptions({responseType,balanceAmount:0});
    const result=await h.execute(h.command('balance'));assert(result.success,JSON.stringify(result));
    assert.equal(result.credits,0);assert.equal(h.calls.length,1);cases++;
  }
  const coin=amount=>({type:'COINS',amount,value(){return this.amount;}});
  const invalid=[
    {balanceData:{}},{balanceData:null},{balanceData:{credits:90000}},
    {balanceData:{coins:{type:'POINTS',value:()=>90000}}},
    {balanceData:{coins:{type:'COINS',amount:90000}}},
    {balanceData:{coins:{type:'COINS',value(){throw Error('PRIVATE_CANARY');}}}},
    {balanceWire:{}},{balanceWire:{currencies:[]}},
    {balanceWire:{currencies:[{name:'POINTS',funds:90000}]}},
    {balanceWire:{currencies:[{name:'COINS',funds:90000},{name:'COINS',funds:90000}]}},
    {balanceWire:{currencies:[{name:'COINS',funds:100}]},balanceData:{coins:coin(90000)}}
  ];
  for(const amount of [-1,1.5,'90000',false,null,NaN,Infinity,2**53]){
    invalid.push({balanceData:{coins:coin(amount)}});
    invalid.push({balanceWire:{currencies:[{name:'COINS',funds:amount}]}});
  }
  for(const options of invalid){
    const h=setup(1);h.sandbox.services.User.getUser().coins={amount:90000};h.setOptions(options);
    const result=await h.execute(h.command('balance'));assert(!result.success,JSON.stringify(options));
    assert.equal(result.credits,null);assert.equal(result.network.length,1);assert.equal(h.calls.length,1);
    h.setOptions({});assert((await h.execute(h.command('balance'))).success,'bad data must not poison later distinct reads');cases++;
  }
  for(const options of [{http:401},{noAuth:true},{zeroOwned:true},{timeout:true},{retry:true},{switchPersona:true}]){
    const h=setup(1);h.setOptions(options);const result=await h.execute(h.command('balance'));
    assert(!result.success);assert.equal(result.credits,null);h.late.forEach(f=>f());cases++;
  }
  const h=setup(1);h.setOptions({interleave:true,async:true});const result=await h.execute(h.command('balance'));
  assert(result.success);assert.equal(result.network.length,1);assert.equal(result.background.length,1);cases++;
  console.log('PASS '+cases+' balance cases: captured official DAO/service/VO, one owned GET, fresh matching coins, invalid data, cleanup and no cached fallback');
}
if(require.main===module)suite().catch(e=>{console.error(e);process.exitCode=1;});
module.exports={nativeScene,suite};

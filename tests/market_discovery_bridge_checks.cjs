"use strict";
const fs=require("node:fs"), vm=require("node:vm"), assert=require("node:assert/strict");
const {webcrypto}=require("node:crypto"), {performance}=require("node:perf_hooks");
const pageSource=fs.readFileSync("experiments/market_discovery/browser/page.js","utf8");
const workerSource=fs.readFileSync("experiments/market_discovery/browser/worker.js","utf8");
const privateValue="PRIVATE-CREDENTIAL-CANARY";
const calls=[];
let mode="normal", isPC=true;
class XHR {
  constructor(){this.listeners={};this.status=200;}
  open(method,url){assert.equal(method,"GET");this.url=url;}
  setRequestHeader(name,value){this.value=value;}
  addEventListener(event,fn){this.listeners[event]=fn;}
  send(){this.listeners.loadend?.();}
}
const originals={open:XHR.prototype.open,header:XHR.prototype.setRequestHeader,send:XHR.prototype.send};
const rawItem={id:"12345678901234567890",definitionId:50596300,assetId:233731,teamId:9,leagueId:13,email:privateValue};
const auction={tradeId:"22222222222222222222",buyNowPrice:6500,startingBid:6400,currentBid:0,expires:200,tradeState:"active",bidState:"none"};
function observable(criteria,page){
  calls.push({operation:"search",criteria,page});
  return {observe(owner,cb){
    const x=new XHR();x.open("GET","https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket?secret="+privateValue);
    x.setRequestHeader("X-UT-SID",privateValue);x.send();assert.equal(x.value,privateValue);
    const item={...rawItem,getAuctionData:()=>auction};
    if(mode==="unsafe")item.id=2**53;
    if(mode==="throw")throw new Error(privateValue);
    const response=mode==="failure"?{success:false,status:461,error:{code:461,message:privateValue}}:
      {success:true,status:200,data:{items:mode==="too-many"?Array(22).fill(item):mode==="empty"?[]:[item],hasMore:true,token:privateValue}};
    if(mode!=="never")setTimeout(()=>cb({unobserve(){}},response),1);
  },unobserve(){}};
}
const allowedItem={searchTransferMarket:observable,clearTransferMarketCache(){calls.push({operation:"invalidate"});}};
const services={User:{getUser:()=>({getSelectedPersona:()=>({platform:isPC?"pc":"ps5",isPC,name:privateValue}),token:privateValue})},
  Item:new Proxy(allowedItem,{get(target,key){if(!(key in target))throw new Error("Mutation/unknown service method attempted: "+String(key));return target[key];}})};
const location={protocol:"https:",hostname:"www.ea.com",pathname:"/ea-sports-fc/ultimate-team/web-app/",href:"https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"};
const context=vm.createContext({window:{},location,services,UTSearchCriteriaDTO:function(){},XMLHttpRequest:XHR,
  crypto:webcrypto,TextEncoder,URL,performance,setTimeout:(fn,delay)=>setTimeout(fn,delay===15000?15:delay),clearTimeout});
vm.runInContext(pageSource,context);
const valid={id:"a".repeat(32),evidence_key:"b".repeat(32),operation:"search",
  params:{definition_id:50596300,page:1,count:21,fresh:true,max_buy:7000,club:9,league:13}};
async function read(c=valid){
  const value=await context.window.__fcDiscoverySearchV1.search(c,performance.timeOrigin+performance.now());
  const serialized=JSON.stringify(value);
  assert(!serialized.includes(privateValue));assert(!serialized.includes(rawItem.id));assert(!serialized.includes(auction.tradeId));
  assert.equal(XHR.prototype.open,originals.open);assert.equal(XHR.prototype.send,originals.send);assert.equal(XHR.prototype.setRequestHeader,originals.header);
  return JSON.parse(serialized);
}
async function worker(modeName){
  const listeners={},requests=[],injections=[],alarms=[],badges=[];
  let nextCount=0;
  const chrome={storage:{session:{async get(){return {discoveryTab:7};},async set(v){assert.equal(v.discoveryTab,7);}}},
    scripting:{async executeScript(v){
      injections.push(v);
      if(v.files){assert.deepEqual(Array.from(v.files),["page.js"]);return [];}
      if(v.args){assert.equal(v.args[0].operation,"search");return [{result:await context.window.__fcDiscoverySearchV1.search(...v.args)}];}
      return [{result:true}];
    }},
    action:{onClicked:{addListener(fn){listeners.click=fn;}},async setBadgeText(v){badges.push(v.text);},async setTitle(){}},
    alarms:{onAlarm:{addListener(fn){listeners.alarm=fn;}},async clear(){},async create(name,options){alarms.push({name,options});}}};
  const fetch=async(url,options)=>{
    requests.push({url,options});
    assert(url.startsWith("http://127.0.0.1:8770/"));assert.equal(options.credentials,"omit");assert.equal(options.redirect,"error");assert.equal(options.method,"POST");
    assert(!JSON.stringify(options).includes(privateValue));
    if(url.endsWith("/next")){
      assert.deepEqual(JSON.parse(options.body),{protocol:1});
      if(++nextCount>1)throw new Error("synthetic stop");
      return {ok:true,async json(){return valid;}};
    }
    assert(url.endsWith("/result"));
    const body=JSON.parse(options.body);
    assert.equal(body.id,valid.id);assert.equal(body.result.success,true);
    assert(body.timing.native_service_ms>=0);assert(body.timing.worker_poll_to_native_ms>=0);
    return {ok:true,async json(){return {accepted:true};}};
  };
  const c=vm.createContext({chrome,fetch,performance,URL,AbortSignal});
  vm.runInContext(workerSource.replace('const TRANSPORT = "long_poll";',`const TRANSPORT = "${modeName}";`),c);
  // Worker validation is independent of page validation.
  for(const op of ["buy","buyNow","bid","move","list","relist","cancel","eval","coins"]){
    c.probe={...valid,operation:op};assert.equal(vm.runInContext("validCommand(probe)",c),false);
  }
  for(const bad of [{nation:46},{count:22},{page:3},{fresh:1},{token:privateValue}]){
    c.probe={...valid,params:{...valid.params,...bad}};assert.equal(vm.runInContext("validCommand(probe)",c),false);
  }
  await listeners.click({id:7,url:location.href});
  assert.equal(injections.filter(i=>i.args).length,1);
  assert(badges.includes("READ"));
  if(modeName==="alarm_30s"){
    assert.equal(alarms.length,1);assert.equal(alarms[0].options.periodInMinutes,.5);
    assert.equal(nextCount,1);
    listeners.alarm({name:"unrelated"});assert.equal(nextCount,1);
    listeners.alarm({name:"fc-discovery-baseline"});await new Promise(resolve=>setTimeout(resolve,5));
    assert.equal(nextCount,2);
  }else{assert.equal(alarms.length,0);assert.equal(nextCount,2);assert(badges.includes("WAIT"));}
  const before=injections.length;
  await listeners.click({id:7,url:"https://evil.invalid/ultimate-team/web-app/"});
  assert.equal(injections.length,before);
}
(async()=>{
  assert.deepEqual(Object.keys(context.window.__fcDiscoverySearchV1),["search"]);
  const out=await read();
  assert.equal(out.result.success,true);assert.equal(out.result.platform,"pc");
  assert.equal(out.result.auctions[0].item.definition_id,50596300);assert.equal(out.result.auctions[0].item.asset_id,233731);
  assert.match(out.result.auctions[0].trade_id,/^trade:[a-f0-9]{24}$/);assert.match(out.result.auctions[0].item.item_id,/^item:[a-f0-9]{24}$/);
  assert.deepEqual(out.result.network,[{host:"utas.mob.v1.prd.futc-ext.gcp.ea.com",path:"/ut/game/fc27/transfermarket",session_header_present:true,status:200}]);
  assert(out.timing.native_service_ms>=0);assert(out.timing.page_total_ms>=out.timing.native_service_ms);assert(out.timing.worker_poll_to_native_ms>=0);
  const native=calls.findLast(v=>v.operation==="search");
  assert.deepEqual(Array.from(native.criteria.defId),[50596300]);assert.equal(native.criteria.club,9);assert.equal(native.criteria.league,13);
  assert.equal(native.criteria.maxBuy,7000);assert.equal(native.criteria.type,"player");assert.equal(native.criteria.count,21);
  const before=calls.length;
  for(const op of ["buy","bid","move","list","relist","cancel","eval","coins","unassigned","transfer_list"])
    assert.equal((await read({...valid,operation:op})).result.error,"invalid_command");
  for(const bad of [{nation:46},{rarity:1},{position:"ST"},{page:3},{count:20},{fresh:1},{definition_id:true},{max_buy:-1},{min_buy:8000}])
    assert.equal((await read({...valid,params:{...valid.params,...bad}})).result.error,"invalid_command");
  assert.equal(calls.length,before,"rejected commands cause no native calls");
  isPC=false;assert.equal((await read()).result.error,"schema_unrecognized");assert.equal(calls.length,before);isPC=true;
  for(const [m,error]of [["failure","service_failed"],["unsafe","unsafe_integer"],["too-many","schema_unrecognized"],["throw","internal_error"],["never","service_timeout"]]){
    mode=m;const v=await read();assert.equal(v.result.error,error);assert.equal(v.result.success,false);
  }
  mode="empty";assert.deepEqual((await read()).result.auctions,[]);mode="normal";
  const again=await read();assert.equal(again.result.auctions[0].trade_id,out.result.auctions[0].trade_id);
  await worker("alarm_30s");await worker("long_poll");
  assert(calls.every(c=>["search","invalidate"].includes(c.operation)));
  process.stdout.write("Discovery page, rejection paths, privacy and both workers verified; synthetic only.\n");
})().catch(e=>{process.stderr.write(e.stack+"\n");process.exitCode=1;});

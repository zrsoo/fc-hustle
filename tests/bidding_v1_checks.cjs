"use strict";
// Synthetic native-services contract tests. No real browser or EA requests.
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const {webcrypto} = require("node:crypto");
const secret = "PRIVATE-CREDENTIAL-CANARY";
let now = Date.parse("2030-01-01T00:00:00Z"), persona = {platform:"PC", isPC:true};
let mode = "ok", current = 0, bidState = "none", watches = 50;
const calls = [], timers = [];
const scope = "a".repeat(32), owner = "b".repeat(32), key = "c".repeat(32);
const hex = n => n.toString(16).padStart(32,"0");
class FakeDate extends Date {constructor(...args) {super(...(args.length ? args : [now]));} static now() {return now;}}
class XHR {
  constructor() {this.listeners = []; this.status = mode === "401" ? 401 : 200;}
  open(method, url) {this.method = method; this.url = url;}
  setRequestHeader(name, value) {} // Deliberately never retain the value.
  addEventListener(event, callback) {assert.equal(event,"loadend"); this.listeners.push(callback);}
  send() {for (const fn of this.listeners) fn();}
}
const originals = {open:XHR.prototype.open, send:XHR.prototype.send, header:XHR.prototype.setRequestHeader};
function raw(n=1) {
  return {id:(10000000000000000000n+BigInt(n)).toString(), definitionId:123, untradeable:false, name:secret,
    getAuctionData:() => ({tradeId:(20000000000000000000n+BigInt(n)).toString(), startingBid:150,
      currentBid:current, buyNowPrice:20000, expires:300, tradeState:"active", bidState})};
}
function response(operation, payload) {
  calls.push(operation);
  return {observe(o, cb) {
    if (mode === "timeout") return;
    if (mode !== "cache") {
      const route = {search:"transfermarket", watched:"watchlist", balance:"user/currencies", bid:"trade/20000000000000000001/bid"}[operation];
      const x = new XHR(); x.open(operation === "bid" ? "PUT" : "GET", "https://utas.test.ea.com/ut/game/fc27/"+route+"?private="+secret);
      x.setRequestHeader("X-UT-SID",secret); x.send();
    }
    now += 12;
    cb({unobserve() {}}, mode === "401" ? {success:false,status:401,error:{code:401,message:secret}} :
      {success:true,status:200,data:payload});
  }, unobserve() {}};
}
const user = {getSelectedPersona:() => persona};
Object.defineProperty(user,"credentials",{get() {throw new Error("credential access forbidden");}});
const allowed = {
  clearTransferMarketCache() {},
  searchTransferMarket(criteria, page) {
    assert.equal(criteria.type,"player"); assert.equal(criteria.count,21); assert.equal(page,2);
    assert.deepEqual(Array.from(criteria.defId),[123]);
    assert.equal(criteria.maxBid,1000); assert.equal(criteria.minBuy,10500);
    assert.equal(criteria.minBid,undefined); assert.equal(criteria.maxBuy,undefined);
    return response("search",{items:[mode === "unsafe" ? {...raw(),id:2**53} : raw()],hasMore:true});
  },
  requestWatchedItems() {return response("watched",{items:Array.from({length:watches},(_,n) => raw(n+1)),hasMore:false});},
  bid(item, amount) {
    assert.equal(item.definitionId,123); assert.equal(typeof item.id,"string");
    assert([150,200,250].includes(amount));
    return response("bid",{});
  }
};
const services = {User:{getUser:() => user, requestCurrencies:() => response("balance",{currencies:[{name:"COINS",funds:50000}]})},
  Item:new Proxy(allowed,{get(target,name) {assert(name in target,"unreviewed native operation"); return target[name];}})};
const location = {protocol:"https:",hostname:"www.ea.com",pathname:"/ea-sports-fc/ultimate-team/web-app/",
  href:"https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"};
const context = vm.createContext({window:{},services,GamePlatform:{PC:"PC"},location,Date:FakeDate,
  performance:{now:() => now}, UTSearchCriteriaDTO:function() {}, XMLHttpRequest:XHR,
  crypto:webcrypto,TextEncoder,URL,
  setTimeout(fn, delay) {timers.push(delay); return setTimeout(fn,delay === 15000 ? 20 : 0);},clearTimeout});
for (const file of ["persona.js","page.js"]) vm.runInContext(fs.readFileSync("browser/bidding-v1/"+file,"utf8"),context);
const api = context.window.__fcBiddingV1;
let epoch = 1;
function command(id, operation, params={}) {
  return {schema:1,id:hex(id),operation,params,evidence_key:key,scope,owner,epoch};
}
async function execute(c) {
  const out = JSON.parse(JSON.stringify(await api.execute(c)));
  const text = JSON.stringify(out);
  for (const value of [secret,"10000000000000000001","20000000000000000001"]) assert(!text.includes(value),"private data leaked");
  assert.equal(XHR.prototype.open,originals.open); assert.equal(XHR.prototype.send,originals.send);
  assert.equal(XHR.prototype.setRequestHeader,originals.header);
  return out;
}
const query = {page:2,count:21,fresh:true,definition_id:123,max_bid:1000,min_buy:10500};
(async () => {
  assert(api.attach(scope,owner,epoch));
  assert(!api.attach(scope,owner,epoch));
  const helper = context.window.__fcDiscoveryPersonaFollowupV1;
  class Persona {get platform() {return "PC";} get isPC() {return true;}}
  assert.equal(helper.classify(new Persona(),"PC"),"pc");
  for (const value of [{platform:"PC"}, {platform:"PSN",isPC:true}, {platform:"PC",isPC:false},
                       {platform:"PC",isPC:"true"}, {platform:secret,isPC:true}]) assert.equal(helper.classify(value,"PC"),null);
  let out = await execute(command(1,"search",query));
  assert(out.result.success); assert.equal(out.result.platform,"pc");
  assert.equal(out.result.auctions[0].item.definition_id,123);
  assert.equal(out.coverage.has_more,true); assert(!out.coverage.complete);
  assert.equal(out.freshness.request_count,1); assert(out.freshness.network_at);
  const target = out.result.auctions[0];
  out = await execute(command(2,"watched"));
  assert.equal(out.result.auctions.length,50); assert.equal(out.freshness.request_count,1);
  assert.equal(out.coverage.account_capacity,null); assert(!out.coverage.complete);
  out = await execute(command(3,"balance")); assert.equal(out.result.credits,50000);
  const bid = {trade_id:target.trade_id,item_id:target.item.item_id,definition_id:123,amount:150,minimum:150,cap:1000,
    deadline:new FakeDate(now+60000).toISOString()};
  let before = calls.filter(x => x === "bid").length;
  for (const p of [{...bid,amount:200}, {...bid,cap:100}, {...bid,definition_id:124},
                   {...bid,deadline:new FakeDate(now).toISOString()}, {...bid,item_id:"item:"+"0".repeat(24)}]) {
    assert.equal((await execute(command(90,"bid",p))).result.error,"invalid_command");
  }
  assert.equal(calls.filter(x => x === "bid").length,before);
  out = await execute(command(100,"bid",bid)); assert(out.result.success);
  assert.equal(out.result.network[0].path,"/ut/game/fc27/trade/:trade/bid");
  assert.equal((await execute(command(100,"bid",bid))).result.error,"invalid_command");
  assert.equal((await execute(command(101,"bid",bid))).result.error,"invalid_command");
  assert.equal(calls.filter(x => x === "bid").length,before+1);
  assert(api.reconciled(scope,owner,epoch,key,target.trade_id));
  current = 150; bidState = "outbid";
  await execute(command(4,"watched"));
  const rebid = {...bid,amount:200,minimum:200};
  mode = "timeout";
  assert.equal((await execute(command(102,"bid",rebid))).result.error,"service_timeout");
  mode = "ok";
  await execute(command(5,"watched"));
  assert.equal((await execute(command(103,"bid",rebid))).result.error,"invalid_command");
  assert(api.reconciled(scope,owner,epoch,key,target.trade_id));
  assert.equal((await execute(command(102,"bid",rebid))).result.error,"invalid_command","same command never retried after reconciliation");
  bidState = "highest";
  await execute(command(6,"watched"));
  assert.equal((await execute(command(104,"bid",rebid))).result.error,"invalid_command");
  bidState = "outbid";
  await execute(command(7,"watched"));
  now += 31000;
  assert.equal((await execute(command(105,"bid",rebid))).result.error,"invalid_command");
  mode = "cache";
  out = await execute(command(8,"watched"));
  assert(out.result.success); assert.equal(out.freshness.request_count,0); assert.equal(out.freshness.network_at,null);
  assert.equal((await execute(command(106,"bid",{...rebid,deadline:new FakeDate(now+60000).toISOString()}))).result.error,"invalid_command");
  mode = "ok"; watches = 0;
  out = await execute(command(9,"watched")); assert.deepEqual(out.result.auctions,[]);
  assert(out.freshness.network_at); assert(!out.coverage.complete);
  mode = "401";
  out = await execute(command(10,"watched")); assert.equal(out.result.status,401); assert.equal(out.freshness.network_at,null);
  mode = "unsafe";
  assert.equal((await execute(command(11,"search",query))).result.error,"unsafe_integer");
  mode = "ok";
  before = calls.length;
  for (const value of [{platform:"PSN",isPC:true}, {platform:"PC"}]) {
    persona = value;
    assert.equal((await execute(command(12,"watched"))).result.error,"schema_unrecognized");
  }
  persona = new Persona();
  for (const c of [{...command(13,"watched"),epoch:2}, {...command(13,"watched"),owner:"0".repeat(32)},
                   command(13,"move"), command(13,"search",{...query,token:secret}), command(13,"search",{...query,page:3})]) {
    assert.equal((await execute(c)).result.error,"invalid_command");
  }
  location.hostname = "attacker.invalid";
  assert.equal((await execute(command(14,"watched"))).result.error,"wrong_page");
  location.hostname = "www.ea.com";
  assert.equal(calls.length,before);
  assert(api.attach(scope,owner,++epoch));
  assert(!api.reconciled(scope,owner,1,key,target.trade_id));
  assert.equal((await execute(command(107,"bid",{...rebid,deadline:new FakeDate(now+60000).toISOString()}))).result.error,"invalid_command");
  assert(timers.every(n => n === 0 || n === 15000),"no hard-coded provider cadence");
  console.log("PASS: native maxBid/minBuy, PC, paging, 50-row bulk, balance, freshness/coverage, bid once, privacy and epochs (synthetic).");
})().catch(error => {console.error(error); process.exitCode = 1;});

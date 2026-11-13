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
  crypto:webcrypto,TextEncoder,URL,repositories:{Item:{setDirty(x){assert.equal(x,1);}}},ItemPile:{INBOX:1},
  setTimeout(fn, delay) {timers.push(delay); return setTimeout(fn,delay === 15000 ? 20 : 0);},clearTimeout});
for (const file of ["persona.js","page.js"]) vm.runInContext(fs.readFileSync("browser/durability-v1/"+file,"utf8"),context);
const api = context.window.__fcDurablePageV1;
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
  assert(api.attach(scope,owner,1));
  assert(api.attach(scope,owner,1),'same ownership attachment is idempotent');
  assert(!api.attach(scope,'d'.repeat(32),1));
  const first = api.document;
  assert(/^[a-f0-9]{32}$/.test(first));
  let out = await execute(command(1,'watched'));
  assert(out.result.success);assert.equal(out.result.auctions.length,50);
  assert(out.result.cache_invalidated);assert.equal(out.freshness.request_count,1);
  const target=out.result.auctions[0];
  const validBid={trade_id:target.trade_id,item_id:target.item.item_id,definition_id:123,
    amount:150,minimum:150,cap:1000,deadline:new FakeDate(now+60000).toISOString()};
  out=await execute(command(30,'bid',validBid));
  assert.equal(out.result.error,'invalid_command');assert.equal(out.freshness.request_count,0);
  const before=calls.length;
  for(const c of [{...command(2,'balance'),scope:'e'.repeat(32)}, {...command(3,'balance'),owner:'f'.repeat(32)},
    {...command(4,'balance'),epoch:0}, command(5,'bid',{})]) {
    out=await execute(c);assert.equal(out.result.error,'invalid_command');assert.equal(out.freshness.request_count,0);
  }
  assert.equal(calls.length,before);
  persona={platform:'PSN',isPC:false};
  out=await execute(command(6,'watched'));assert(!out.result.success);assert.equal(calls.length,before);
  persona={platform:'PC',isPC:true};
  assert(api.attach(scope,'d'.repeat(32),2));
  out=await execute(command(7,'watched'));assert.equal(out.result.error,'invalid_command');
  const owner2='d'.repeat(32);
  out=await execute({...command(8,'watched'),owner:owner2,epoch:2});assert(out.result.success);
  mode='cache';out=await execute({...command(9,'watched'),owner:owner2,epoch:2});
  assert.equal(out.freshness.network_at,null);assert.equal(out.freshness.request_count,0);
  mode='timeout';out=await execute({...command(10,'watched'),owner:owner2,epoch:2});
  assert.equal(out.result.error,'service_timeout');
  mode='ok';out=await execute({...command(11,'balance'),owner:owner2,epoch:2});assert(out.result.success);
  const saved=context.window;
  context.window={};
  for(const file of ['persona.js','page.js'])vm.runInContext(fs.readFileSync('browser/durability-v1/'+file,'utf8'),context);
  const after=context.window.__fcDurablePageV1;
  assert.notEqual(after.document,first);assert(after.attach(scope,owner2,2));
  assert.equal((await after.execute(command(12,'balance'))).result.error,'invalid_command');
  assert(!calls.includes('bid'));
  console.log('PASS: page reload, 50 rows, persona, ownership, epochs, cache, timeout and zero writes');
})().catch(e=>{console.error(e);process.exitCode=1;});

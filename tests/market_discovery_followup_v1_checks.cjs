"use strict";
// Synthetic regression fixtures only. Never connected to a user browser or EA.
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const {webcrypto} = require("node:crypto");
const root = "experiments/market_discovery_followup_v1/browser/";
const personaSource = fs.readFileSync(root + "persona.js", "utf8");
const pageSource = fs.readFileSync(root + "page.js", "utf8");
const workerSource = fs.readFileSync(root + "worker.js", "utf8");
const privateValue = "PRIVATE-CREDENTIAL-CANARY";
let persona = {platform: "PC", isPC: true}, clock = 100000, mode = "ok";
const submissions = [], waits = [];
class XHR {
  constructor() { this.listeners = []; this.status = mode === "401" ? 401 : 200; }
  open(method, url) { assert.equal(method, "GET"); this.url = url; }
  setRequestHeader(name, value) { this.header = value; }
  addEventListener(event, callback) { this.listeners.push(callback); }
  send() { for (const callback of this.listeners) callback(); }
}
const original = {open: XHR.prototype.open, send: XHR.prototype.send, header: XHR.prototype.setRequestHeader};
const raw = {id: "12345678901234567890", definitionId: 233731, resourceId: 233731, assetId: 233731,
  getAuctionData: () => ({tradeId: "22222222222222222222", buyNowPrice: 6500, startingBid: 6400,
    currentBid: 0, expires: 300, tradeState: "active", bidState: "none"}), name: privateValue};
const user = {getSelectedPersona: () => persona};
Object.defineProperty(user, "credentials", {get() { throw new Error("must never inspect credentials"); }});
const allowed = {
  clearTransferMarketCache() {},
  searchTransferMarket(criteria, page) {
    submissions.push(clock);
    assert.equal(criteria.count, 21); assert.equal(criteria.type, "player");
    assert.deepEqual(Array.from(criteria.defId), [233731]); assert.equal(page, 1);
    return {observe(owner, callback) {
      const x = new XHR(); x.open("GET", "https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket?private=" + privateValue);
      x.setRequestHeader("X-UT-SID", privateValue); x.send();
      const response = mode === "401" ? {success: false, status: 401, error: {code: 401, message: privateValue}} :
        {success: true, status: 200, data: {items: [mode === "unsafe" ? {...raw, id: 2**53} : raw]}};
      setTimeout(() => { clock += 12; callback({unobserve() {}}, response); }, 0);
    }, unobserve() {}};
  }
};
const services = {User: {getUser: () => user}, Item: new Proxy(allowed, {
  get(target, name) { assert(name in target, "unknown or mutation method accessed"); return target[name]; }
})};
const performance = {timeOrigin: 1700000000000, now: () => clock};
const location = {protocol: "https:", hostname: "www.ea.com", pathname: "/ea-sports-fc/ultimate-team/web-app/",
  href: "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"};
const context = vm.createContext({window: {}, services, GamePlatform: {PC: "PC", PSN: "PSN", XBL: "XBL", SWI: "SWI"},
  performance, location, UTSearchCriteriaDTO: function() {}, XMLHttpRequest: XHR, crypto: webcrypto, TextEncoder, URL,
  setTimeout(fn, delay) {
    if (delay === 15000) return setTimeout(fn, 50);
    if (delay > 0) { waits.push(delay); clock += delay; }
    return setTimeout(fn, 0);
  }, clearTimeout});
vm.runInContext(personaSource, context);
vm.runInContext(pageSource, context);
const helper = context.window.__fcDiscoveryPersonaFollowupV1;
const command = {id: "a".repeat(32), evidence_key: "b".repeat(32), operation: "search",
  params: {page: 1, count: 21, fresh: true, definition_id: 233731, max_buy: 7000}};
async function search(value = command) {
  const out = await context.window.__fcDiscoverySearchFollowupV1.search(value, performance.timeOrigin + clock);
  const text = JSON.stringify(out);
  assert(!text.includes(privateValue)); assert(!text.includes(raw.id)); assert(!text.includes("22222222222222222222"));
  assert.equal(XHR.prototype.open, original.open); assert.equal(XHR.prototype.send, original.send);
  assert.equal(XHR.prototype.setRequestHeader, original.header);
  return JSON.parse(text);
}
(async () => {
  class NativePersona { get platform() { return "PC"; } get isPC() { return true; } }
  for (const value of [new NativePersona(), {platform: "pc"}, {platform: "pc", isPC: true},
    {platform: null, isPC: true}, {isPC: true}]) assert.equal(helper.classify(value, "PC"), "pc");
  for (const platform of ["PSN", "XBL", "SWI", "ps3", "ps4", "ps5", "xboxone", "xbsx", "switch", "UNKNOWN", "", 1, [], {}]) {
    assert.equal(helper.classify({platform, isPC: true}, "PC"), null, "true isPC cannot override explicit non-PC");
  }
  for (const value of [null, undefined, [], "PC", true, 1, {}, new Date(), new Map(),
    {platform: "PC"}, {platform: "PC", isPC: false}, {platform: "pc", isPC: false},
    {platform: "PC", isPC: "true"}, {platform: "pc", isPC: null}, {platform: null, isPC: false},
    {get platform() { throw new Error(privateValue); }, isPC: true}]) assert.equal(helper.classify(value, "PC"), null);
  assert.equal(helper.classify(new NativePersona(), undefined), null, "native enum must be observed");
  assert.equal(helper.classify(new NativePersona(), "console"), null);
  persona = new NativePersona();
  assert.deepEqual(JSON.parse(JSON.stringify(helper.inspect())), {schema: 1, persona_present: true,
    platform_type: "string", platform_value: "PC", is_pc_type: "boolean", is_pc: true,
    native_pc_constant: "PC", accepted: true, read_error: false});
  const first = await search();
  assert(first.result.success); assert.equal(first.result.platform, "pc");
  assert.equal(first.result.auctions[0].item.definition_id, 233731);
  assert.equal(first.result.network[0].status, 200); assert(first.result.network[0].session_header_present);
  await search(); assert(submissions[1] - submissions[0] >= 30000, "actual native submissions must be paced");
  const before = submissions.length;
  persona = {platform: "PSN", isPC: true};
  assert.equal((await search()).result.error, "schema_unrecognized"); assert.equal(submissions.length, before);
  persona = {platform: "unreviewed:" + privateValue, isPC: true};
  assert(!JSON.stringify(helper.inspect()).includes(privateValue));
  persona = new NativePersona();
  for (const operation of ["buy", "bid", "move", "list", "relist", "eval", "coins"]) {
    assert.equal((await search({...command, operation})).result.error, "invalid_command");
  }
  assert.equal(submissions.length, before);
  mode = "401";
  const denied = await search(); assert.equal(denied.result.status, 401);
  assert.equal(denied.result.network[0].status, 401); assert.equal(denied.result.error, "service_failed");
  mode = "unsafe"; assert.equal((await search()).result.error, "unsafe_integer"); mode = "ok";
  let clicked, polls = 0;
  const posts = [], badges = [];
  const chrome = {storage: {session: {get: async () => ({followupTab: 7}), set: async () => {}}},
    scripting: {executeScript: async spec => {
      assert.equal(spec.world, "MAIN"); assert.equal(spec.target.tabId, 7);
      if (spec.files) { assert.deepEqual(Array.from(spec.files), ["persona.js", "page.js"]); return []; }
      if (spec.args) return [{result: await search()}];
      const text = String(spec.func);
      return [{result: text.includes("inspect") ? helper.inspect() : true}];
    }}, action: {onClicked: {addListener(fn) { clicked = fn; }},
      setBadgeText: async x => badges.push(x.text), setTitle: async x => assert(!x.title.includes(privateValue))}};
  const worker = vm.createContext({chrome, performance, URL, AbortSignal, fetch: async (url, options) => {
    assert(url.startsWith("http://127.0.0.1:8771/")); assert.equal(options.method, "POST");
    assert.equal(options.credentials, "omit"); assert.equal(options.redirect, "error");
    const body = JSON.parse(options.body); posts.push({url, body});
    if (url.endsWith("/next")) {
      if (++polls > 1) throw new Error("fixture stop:" + privateValue);
      return {ok: true, json: async () => command};
    }
    return {ok: true, json: async () => ({accepted: true})};
  }});
  vm.runInContext(workerSource, worker);
  await clicked({id: 7, url: location.href});
  assert(posts.some(x => x.url.endsWith("/persona") && x.body.accepted));
  assert(posts.some(x => x.url.endsWith("/result") && x.body.result.success));
  assert(posts.some(x => x.url.endsWith("/telemetry") && x.body.result_post_round_trip_ms >= 0));
  assert(badges.includes("READ"));
  const count = posts.length; await clicked({id: 7, url: "https://attacker.invalid/ultimate-team/web-app/"});
  assert.equal(posts.length, count);
  console.log("PASS: follow-up persona, strict rejection, identity/privacy, 30-second pacing and long-poll worker; synthetic only.");
})().catch(error => { console.error(error); process.exitCode = 1; });

"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const {webcrypto} = require("node:crypto");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "browser/read-bridge/page.js"), "utf8");
const workerSource = fs.readFileSync(path.join(root, "browser/read-bridge/worker.js"), "utf8");
const privateValue = "synthetic-private-canary";
const calls = [];
let mode = "normal", pc = true;
class XHR {
  constructor() {this.listeners = {}; this.status = 200;}
  open(method, url) {this.method = method; this.url = url;}
  setRequestHeader(name, value) {this.headerValue = value;}
  addEventListener(event, fn) {this.listeners[event] = fn;}
  send() {this.listeners.loadend?.();}
}
const original = {open: XHR.prototype.open, send: XHR.prototype.send, header: XHR.prototype.setRequestHeader};
const item = {id: "12345678901234567890", resourceId: 90001, definitionId: 90001, assetId: 123,
  rating: 83, rareflag: 1, nationId: 4, leagueId: 13, teamId: 23, preferredPosition: "ST",
  untradeable: false, marketAverage: 800, lastSalePrice: 650, name: privateValue, persona: privateValue};
const auction = {tradeId: "22222222222222222222", startingBid: 500, currentBid: 550, buyNowPrice: 700, expires: 100, tradeState: "active", bidState: "none"};
function observable(op, params) {
  calls.push({op, params});
  return {observe(owner, cb) {
    const routes = {coins: "user/currencies", club: "club", unassigned: "unassigned", transfer_list: "tradepile", search: "transfermarket"};
    const x = new XHR(); x.open("GET", "https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/" + routes[op] + "?discard=" + privateValue);
    x.setRequestHeader("X-UT-SID", privateValue); x.send();
    assert.equal(x.headerValue, privateValue, "request preserved");
    const response = mode === "failure" ? {success: false, status: 461, error: {code: 461, message: privateValue}} :
      {success: true, status: 200, data: mode === "bad-schema" ? {name: privateValue} : op === "coins" ? {credits: 0, account: privateValue} :
        {items: mode === "empty" ? [] : [{...item, getAuctionData: () => auction}], hasMore: true, account: privateValue}};
    if (mode === "unsafe") response.data.items[0].id = 2**53;
    if (mode === "throw") throw new Error(privateValue);
    if (mode !== "never") setTimeout(() => cb({unobserve() {}}, response), 0);
  }, unobserve() {}};
}
const services = {User: {requestCurrencies: () => observable("coins"), getUser: () => ({coins: {amount: 0}, email: privateValue, getSelectedPersona: () => ({isPC: pc, name: privateValue})})},
  Club: {search: c => observable("club", c)},
  Item: {clearTransferMarketCache() {calls.push({op: "invalidate"});},
    searchTransferMarket(c, page) {return observable("search", {criteria: c, page});},
    requestUnassignedItems: () => observable("unassigned"), requestTransferItems: () => observable("transfer_list")}};
const context = vm.createContext({window: {}, location: {protocol: "https:", hostname: "www.ea.com", pathname: "/ea-sports-fc/ultimate-team/web-app/", href: "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"},
  services, XMLHttpRequest: XHR, UTSearchCriteriaDTO: function() {}, crypto: webcrypto, TextEncoder, URL,
  setTimeout: (fn, delay) => setTimeout(fn, delay === 15000 ? 15 : delay), clearTimeout});
vm.runInContext(source, context);
const read = async (operation, params = {}) => {
  const out = await context.window.__fcReadBridgeV1.read({id: "a".repeat(32), evidence_key: "b".repeat(32), operation, params});
  const serialized = JSON.stringify(out);
  assert(!serialized.includes(privateValue), "private values never cross page boundary");
  assert(!serialized.includes(item.id), "physical ID pseudonymized before transport");
  assert(!serialized.includes(auction.tradeId), "trade ID pseudonymized before transport");
  assert.equal(XHR.prototype.open, original.open); assert.equal(XHR.prototype.send, original.send); assert.equal(XHR.prototype.setRequestHeader, original.header);
  return JSON.parse(serialized);
};
(async () => {
  const coins = await read("coins");
  assert.equal(coins.credits, 0); assert.equal(coins.platform, "pc"); assert.equal(coins.success, true);
  assert.deepEqual(coins.network, [{host: "utas.mob.v1.prd.futc-ext.gcp.ea.com", path: "/ut/game/fc27/user/currencies", session_header_present: true, status: 200}]);
  pc = false; assert.equal((await read("coins")).platform, null, "false isPC never implies ps5"); pc = true;
  const search = await read("search", {page: 2, count: 21, definition_id: 90001, max_buy: 700, min_buy: 500, nation: 4, league: 13, club: 23, rarity: 1, position: "ST", fresh: true});
  assert.equal(search.auctions[0].item.resource_id, 90001);
  assert.equal(search.auctions[0].item.definition_id, 90001);
  assert.equal(search.auctions[0].item.asset_id, 123);
  assert.match(search.auctions[0].trade_id, /^trade:[a-f0-9]{24}$/);
  assert.match(search.auctions[0].item.item_id, /^item:[a-f0-9]{24}$/);
  assert.equal(search.auctions[0].item.item_id, "item:" + require("node:crypto").createHash("sha256").update("b".repeat(32) + "|item|" + item.id).digest("hex").slice(0, 24));
  assert.equal(search.cache_invalidated, true);
  const probe = calls.findLast(c => c.op === "search");
  assert.equal(probe.params.page, 2); assert.equal(probe.params.criteria.maxBuy, 700);
  assert.deepEqual(Array.from(probe.params.criteria.defId), [90001]);
  assert.equal(probe.params.criteria.nationality, 4); assert.equal(probe.params.criteria.position, "ST");
  for (const op of ["club", "unassigned", "transfer_list"]) assert.equal((await read(op)).success, true);
  assert.equal((await read("purchased")).error, "service_unavailable");
  const before = calls.length;
  for (const op of ["bid", "buy", "move", "list", "eval"]) assert.equal((await read(op)).error, "invalid_command");
  for (const params of [{page: 3}, {count: 22}, {platform: "pc"}, {max_buy: true}, {min_buy: 9, max_buy: 1}]) assert.equal((await read("search", params)).error, "invalid_command");
  assert.equal(calls.length, before, "rejected commands call no native services");
  mode = "empty"; assert.deepEqual((await read("unassigned")).items, []);
  mode = "bad-schema"; assert.equal((await read("club")).error, "schema_unrecognized");
  mode = "failure"; const fail = await read("coins"); assert.equal(fail.error, "service_failed"); assert.equal(fail.status, 461); assert.equal(fail.ea_error_code, 461);
  mode = "unsafe"; assert.equal((await read("search")).error, "unsafe_integer");
  mode = "throw"; assert.equal((await read("coins")).error, "internal_error");
  mode = "never"; assert.equal((await read("coins")).error, "service_timeout");
  mode = "normal";
  context.location.hostname = "attacker.invalid"; assert.equal((await read("coins")).error, "wrong_page"); context.location.hostname = "www.ea.com";
  // Exercise the actual MV3 worker attachment and command/result exchange.
  let click, alarm, stored, fetched = [], badges = [], titles = [], pollStatus = 200, networkFailure = false,
    command = {id: "a".repeat(32), evidence_key: "b".repeat(32), operation: "coins", params: {}};
  const worker = vm.createContext({URL, AbortSignal, fetch: async (url, options) => {
    fetched.push({url, options}); assert.equal(options.credentials, "omit"); assert.equal(options.redirect, "error");
    if (url.endsWith("/next")) {
      assert.equal(options.method, "POST", "polling must use POST so Edge supplies Origin");
      assert.equal(options.headers["Content-Type"], "application/json");
      assert.equal(options.body, "{}");
      if (networkFailure) throw new Error(privateValue);
      const c = command; command = null; return {ok: pollStatus === 200, status: pollStatus, json: async () => c};
    }
    assert(url.endsWith("/result")); assert(!options.body.includes(privateValue)); assert.equal(JSON.parse(options.body).result.credits, 0); return {ok: true};
  }, chrome: {storage: {session: {get: async () => stored || {}, set: async v => {stored = v;}}},
    scripting: {executeScript: async spec => {
      assert.equal(spec.world, "MAIN"); assert.equal(spec.target.tabId, 7);
      if (spec.files) return [];
      if (spec.args) return [{result: await read("coins")}];
      return [{result: true}];
    }}, action: {onClicked: {addListener: f => {click = f;}}, setBadgeText: async v => {badges.push(v.text);},
      setTitle: async v => {titles.push(v.title);}},
    alarms: {create: async () => {}, onAlarm: {addListener: f => {alarm = f;}}}}});
  vm.runInContext(workerSource, worker);
  await click({id: 7, url: "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"});
  assert.equal(stored.readTab, 7); assert.equal(fetched.length, 2); assert.equal(badges.at(-1), "READ");
  assert.match(titles.at(-1), /attached on port 8767/);
  pollStatus = 403;
  await click({id: 7, url: "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"});
  assert.equal(badges.at(-1), "WAIT"); assert.match(titles.at(-1), /HTTP 403/);
  networkFailure = true;
  await click({id: 7, url: "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"});
  assert.match(titles.at(-1), /Cannot reach the local read server/);
  assert(!JSON.stringify(titles).includes(privateValue), "diagnostics must not export exception text");
  await click({id: 7, url: "https://attacker.invalid/ultimate-team/web-app/"}); assert.equal(badges.at(-1), "WAIT");
  assert.match(titles.at(-1), /Select the official HTTPS EA/);
  assert.equal(typeof alarm, "function");
  console.log("PASS: native read-only command dispatch, projection/privacy, identity, filters, errors, network preservation, and MV3 exchange");
})().catch(e => {console.error(e); process.exitCode = 1;});

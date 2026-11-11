"use strict";
// Execute actual page scripts with a synthetic EA observable implementation.
const fs = require("node:fs"), vm = require("node:vm"), path = require("node:path");
const assert = require("node:assert/strict"), {webcrypto} = require("node:crypto");
const dir = path.resolve(__dirname, "../browser/transaction-bridge");
const key = "b".repeat(32), privateValue = "synthetic-private-canary";
function setup(fault = null, apply = true) {
  const calls = []; let bought = false, moved = false, listed = false;
  const a = {tradeId: "222", startingBid: 150, currentBid: 0, buyNowPrice: 200, expires: 600, tradeState: "active"};
  const item = {id: "123", definitionId: 90001, tradable: true, isPlayer: () => true,
    getAuctionData: () => a, name: privateValue};
  class XHR {
    open() {} setRequestHeader() {} send() {} addEventListener() {}
  }
  const observable = (op, fn, payload = () => ({items: [item]})) => {
    calls.push(op);
    if (op !== fault || apply) fn?.();
    return {observe(owner, cb) {
      if (op === fault) return;
      setTimeout(() => cb({unobserve() {}}, {success: true, status: 200, data: payload()}), 0);
    }, unobserve() {}};
  };
  const services = {User: {getUser: () => ({getSelectedPersona: () => ({isPC: true})})}, Item: {
    clearTransferMarketCache() {}, searchTransferMarket: () => observable("search"),
    requestUnassignedItems: () => observable("inventory", null, () => ({items: bought && !moved ? [item] : []})),
    requestTransferItems: () => observable("transfer_list", null, () => ({items: moved ? [item] : []})),
    bid: (i, price) => {assert.equal(i, item); assert.equal(price, 200); return observable("buy", () => {bought = true;});},
    move: (items, pile, flag) => {assert.equal(items[0], item); assert.equal(pile, 2); assert.equal(flag, false); return observable("move", () => {moved = true; a.tradeState = "inactive";});},
    list: (i, bid, bin, duration) => {assert.equal(i, item); assert.equal(bid, 200); assert.equal(bin, 250); assert.equal(duration, 3600); return observable("list", () => {listed = true; Object.assign(a, {tradeId: "333", startingBid: bid, buyNowPrice: bin, expires: duration, tradeState: "active"});});}
  }};
  const c = vm.createContext({window: {}, services, ItemPile: {TRANSFER: 2, PURCHASED: 1}, repositories: {Item: {setDirty: pile => {assert([1, 2].includes(pile)); calls.push("dirty:" + pile);}}}, XMLHttpRequest: XHR,
    UTSearchCriteriaDTO: function() {}, crypto: webcrypto, TextEncoder, URL,
    location: {protocol: "https:", hostname: "www.ea.com", pathname: "/ea-sports-fc/ultimate-team/web-app/", href: "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"},
    setTimeout: (fn, delay) => setTimeout(fn, delay === 15000 ? 15 : delay), clearTimeout});
  for (const file of ["read-page.js", "page.js"]) vm.runInContext(fs.readFileSync(path.join(dir, file), "utf8"), c);
  const run = async (operation, params = {}) => {
    const result = await c.window.__fcTransactionBridgeV3.run({id: "a".repeat(32), evidence_key: key, operation, params});
    assert(!JSON.stringify(result).includes(privateValue), "no arbitrary service/account strings retained");
    return JSON.parse(JSON.stringify(result));
  };
  return {c, run, calls, item, a};
}
(async () => {
  let s = setup();
  const native = await s.run("search", {max_buy: 500, fresh: true});
  assert.equal(native.auctions[0].item.untradeable, false, "native tradable boolean projected");
  s.item.tradable = false;
  assert.equal((await s.run("search", {max_buy: 500})).auctions[0].item.untradeable, true);
  delete s.item.tradable;
  assert.equal((await s.run("search", {max_buy: 500})).auctions[0].item.untradeable, null, "absent native field stays unknown");
  s.item.tradable = true;
  const selected = (await s.run("search", {max_buy: 500, fresh: true})).auctions[0];
  const target = {item_id: selected.item.item_id, definition_id: 90001};
  const buy = {...target, trade_id: selected.trade_id, buy_now_price: 200};
  assert.equal((await s.run("buy", {...buy, buy_now_price: 501})).error, "invalid_command");
  assert.equal((await s.run("buy", {...buy, trade_id: "trade:" + "0".repeat(24)})).error, "invalid_command");
  assert(!s.calls.includes("buy"), "exact auction mismatch never dispatches a purchase");
  assert.equal((await s.run("buy", buy)).success, true);
  assert.equal((await s.run("buy", buy)).error, "invalid_command");
  assert.equal(s.calls.filter(v => v === "buy").length, 1);
  const inventory = await s.run("unassigned");
  assert.equal(inventory.items[0].item_id, target.item_id);
  assert.equal(inventory.cache_invalidated, true, "owned-item read must expire the native purchased cache");
  assert.equal(s.calls[s.calls.lastIndexOf("inventory") - 1], "dirty:1");
  assert.equal((await s.run("move", target)).success, true);
  assert.equal((await s.run("transfer_list")).auctions[0].item.item_id, target.item_id);
  const listing = {...target, starting_bid: 200, buy_now_price: 250, duration: 3600};
  assert.equal((await s.run("list", {...listing, duration: 7200})).error, "invalid_command");
  assert.equal((await s.run("list", listing)).success, true);
  assert.equal((await s.run("list", listing)).error, "invalid_command");
  const status = await s.run("status");
  assert.equal(status.cache_invalidated, true, "status must expire the native transfer cache");
  assert.equal(s.calls[s.calls.lastIndexOf("transfer_list") - 1], "dirty:2");
  assert.equal(status.auctions[0].trade_state, "active");
  assert.equal(status.auctions[0].expires, 3600);
  assert.equal(status.auctions[0].buy_now_price, 250);
  assert.equal((await s.run("relist", listing)).error, "invalid_command", "active item cannot be relisted");
  Object.assign(s.a, {tradeState: "expired", expires: -1, currentBid: 0});
  assert.equal((await s.run("relist", listing)).success, true, "single expired item can be relisted");
  for (const op of ["buy", "move", "list"]) {
    s = setup(op, true);
    const a = (await s.run("search", {max_buy: 500, fresh: true})).auctions[0];
    const t = {item_id: a.item.item_id, definition_id: 90001};
    const b = {...t, trade_id: a.trade_id, buy_now_price: 200};
    const l = {...t, starting_bid: 200, buy_now_price: 250, duration: 3600};
    assert.equal((await s.run("buy", b)).error, op === "buy" ? "service_timeout" : null);
    if (op !== "buy") await s.run("move", t);
    if (op === "list") await s.run("list", l);
    const args = op === "buy" ? b : op === "move" ? t : l;
    assert.equal((await s.run(op, args)).error, "invalid_command");
    assert.equal(s.calls.filter(v => v === op).length, 1, "timeout cannot redispatch native write");
  }
  s = setup(); s.c.location.hostname = "attacker.invalid";
  assert.equal((await s.run("buy", buy)).error, "wrong_page");
  assert.equal(s.calls.length, 0);
  console.log("PASS: actual native write dispatch, identity checks, prices/duration, single writes, status, eligible relist, timeout duplicate prevention, privacy and page guards (synthetic only)");
})().catch(e => {console.error(e); process.exitCode = 1;});

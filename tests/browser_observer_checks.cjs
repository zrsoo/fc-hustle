"use strict";
// Synthetic runtime checks; no browser, account, network or live evidence file.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../browser/observer/page.js"), "utf8");
const API = "https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/";

async function main() {
  let sends = 0, opens = 0, headerCalls = 0;
  class XHR {
    open(method, url, ...args) { opens++; this.method = method; this.url = url; this.args = args; this.listeners = []; return "original-open"; }
    setRequestHeader(name, value) { headerCalls++; return "original-header"; }
    addEventListener(name, callback) { this.listeners.push(callback); }
    send(body) { sends++; this.body = body; return "original-send"; }
    async complete(status, body) { this.status = status; this.responseType = ""; this.responseText = JSON.stringify(body); this.responseURL = this.url; await Promise.all(this.listeners.map(f => f())); }
  }
  let response = new Response(JSON.stringify({auctionInfo: []}), {status: 200});
  let originalPromise;
  const originalFetch = (...args) => { originalPromise = Promise.resolve(response); return originalPromise; };
  const previousObserver = Object.freeze({peek: () => []});
  const window = {fetch: originalFetch, __fcConfigurationObserver: previousObserver};
  const context = vm.createContext({window, XMLHttpRequest: XHR, URL, Headers, Request, Date,
    EAConfigurationRepository: {KEY_EADP_CLIENT_ID: "public-client-key"},
    getAppMain: () => ({getConfigRepository: () => ({getConfigString: key => {
      assert.equal(key, "public-client-key", "must read only the reviewed public configuration key");
      return "FC27_JS_WEB_APP";
    }})}),
    TextDecoder, Blob, performance: {getEntriesByType: () => [{name: "https://accounts.ea.com/connect/auth?client_id=FC27_JS_WEB_APP&private=synthetic-private-canary"}]},
    location: {href: "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"}});
  vm.runInContext(source, context);
  const hooks = {open: XHR.prototype.open, fetch: window.fetch};
  vm.runInContext(source, context);
  assert.equal(XHR.prototype.open, hooks.open, "repeated attachment must be idempotent");
  assert.equal(window.fetch, hooks.fetch);
  const state = window.__fcConfigurationObserverV2;
  assert.equal(window.__fcConfigurationObserver, previousObserver, "upgrading must preserve existing hooks");
  assert.equal(state.peek().length, 0, "installation alone is not authentication");
  const xhr = new XHR();
  assert.equal(xhr.open("GET", API + "user/credits?private_fixture=canary", true), "original-open");
  assert.equal(xhr.setRequestHeader("X-UT-SID", "synthetic-private-canary"), "original-header");
  xhr.setRequestHeader("X-UT-SKU", "FUT27WEB");
  xhr.setRequestHeader("X-UT-Client", "FC27_JS_WEB_APP");
  assert.equal(xhr.send(), "original-send");
  await xhr.complete(200, {credits: 1234, account: "synthetic-private-canary"});
  let observations = state.peek();
  assert.equal(observations[0].event, "authenticated_read");
  assert.equal(observations[0].response_shape, "credits");
  assert.equal(observations[0].client_id, "FC27_JS_WEB_APP");
  assert.equal(observations[0].sku, "FUT27WEB");
  for (const forbidden of ["synthetic-private-canary", "1234", "private_fixture", "account", "user/credits?"])
    assert.ok(!JSON.stringify(observations).includes(forbidden), "private information leaked");
  assert.equal(observations[0].request_prefix, "/ut/game/fc27/");
  assert.equal(observations[0].observer_version, 2);
  for (const type of ["arraybuffer", "blob", "json"]) {
    const binary = new XHR(); binary.open("GET", API + "club"); binary.setRequestHeader("x-ut-sid", "synthetic"); binary.send();
    binary.status = 200; binary.responseURL = binary.url; binary.responseType = type;
    const text = JSON.stringify({data: {itemData: [], account: "synthetic-private-canary"}});
    binary.response = type === "arraybuffer" ? new TextEncoder().encode(text).buffer : type === "blob" ? new Blob([text]) : JSON.parse(text);
    await Promise.all(binary.listeners.map(f => f()));
    assert.equal(state.peek().at(-1).event, "authenticated_read");
    assert.equal(state.peek().at(-1).response_type, type);
    assert.equal(state.peek().at(-1).route, "club");
  }
  const noSession = new XHR(); noSession.open("GET", API + "club"); noSession.send(); await noSession.complete(200, {itemData: []});
  assert.equal(state.peek().at(-1).event, "configured_request", "HTTP 200 alone cannot prove authentication");
  const noShape = new XHR(); noShape.open("GET", API + "club"); noShape.setRequestHeader("x-ut-sid", "synthetic");
  noShape.send(); await noShape.complete(200, {message: "login required"});
  assert.equal(state.peek().at(-1).event, "configured_request");
  const redirected = new XHR(); redirected.open("GET", API + "club"); redirected.setRequestHeader("x-ut-sid", "synthetic");
  redirected.send(); redirected.status = 200; redirected.responseType = "json";
  redirected.response = {itemData: []}; redirected.responseURL = "https://www.ea.com/login";
  await Promise.all(redirected.listeners.map(f => f()));
  assert.equal(state.peek().at(-1).event, "configured_request", "redirects must not prove authenticated access");
  const denied = new XHR(); denied.open("GET", API + "club"); denied.send(); await denied.complete(401, {});
  assert.equal(state.peek().at(-1).event, "auth_rejected");
  let count = state.peek().length;
  for (const url of [API.replace(".ea.com", ".ea.com.attacker.invalid"), API.replace("https:", "http:"), "https://example.com/ut/game/fc27/club"]) {
    const bad = new XHR(); bad.open("GET", url); bad.send(); await bad.complete(200, {itemData: []});
  }
  assert.equal(state.peek().length, count, "non-EA traffic must be ignored");
  const older = new XHR(); older.open("GET", API.replace("fc27", "fc26") + "club"); older.send(); await older.complete(200, {itemData: []});
  assert.equal(state.peek().at(-1).game_version, "fc26");
  assert.equal(state.peek().at(-1).client_id, null, "historical version must not inherit FC27 identifiers");
  const auth = new XHR(); auth.open("POST", "https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/auth");
  auth.send(JSON.stringify({sku: "FUT27WEB", client: "FC27_JS_WEB_APP", other: "synthetic-private-canary"}));
  const result = window.fetch(API + "transfermarket?private_fixture=canary", {headers: {"x-ut-sid": "synthetic-private-canary"}});
  assert.equal(result, originalPromise, "fetch return identity must be preserved");
  await result; await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(state.peek().at(-1).event, "authenticated_read");
  assert.equal(state.peek().at(-1).response_shape, "auctionInfo");
  assert.ok(!JSON.stringify(state.peek()).includes("synthetic-private-canary"));
  count = state.peek().length;
  state.ack(count);
  assert.equal(state.peek().length, 0);
  assert.ok(opens >= 8 && sends >= 8 && headerCalls >= 4, "original browser operations must still run");
  await checkWorker();
  checkNativeProbe();
  console.log("PASS: observer behavior, privacy, auth semantics, preservation and version isolation");
}

function checkNativeProbe() {
  const probe = fs.readFileSync(path.join(__dirname, "../browser/observer/native-read-probe.js"), "utf8");
  for (const [protocol, hostname, pathname, expected] of [
    ["https:", "www.ea.com", "/ea-sports-fc/ultimate-team/web-app/", 1],
    ["https:", "ea.com", "/ea-sports-fc/ultimate-team/web-app/", 1],
    ["http:", "www.ea.com", "/ea-sports-fc/ultimate-team/web-app/", 0],
    ["https:", "www.ea.com.attacker.invalid", "/ea-sports-fc/ultimate-team/web-app/", 0],
    ["https:", "www.ea.com", "/login", 0]
  ]) {
    let calls = 0;
    const result = vm.runInNewContext(probe, {location: {protocol, hostname, pathname},
      services: {User: {requestCurrencies() { calls++; return {private: "synthetic-private-canary"}; }}}});
    assert.equal(calls, expected);
    assert.equal(result, undefined, "native read must not return account data to the console");
  }
  const location = {protocol: "https:", hostname: "www.ea.com", pathname: "/ea-sports-fc/ultimate-team/web-app/"};
  assert.equal(vm.runInNewContext(probe, {location}), undefined, "missing app service must be harmless");
  assert.equal(vm.runInNewContext(probe, {location,
    services: {User: {requestCurrencies() {throw {private: "synthetic-private-canary"};}}}}), undefined);
}

async function checkWorker() {
  const events = {}, posts = [], badges = [], stored = {};
  let injected = 0, failDelivery = true, acknowledgements = 0;
  const queued = [{event: "configured_request", game_version: "fc27"}];
  const chrome = {
    storage: {session: {get: async () => ({...stored}), set: async value => Object.assign(stored, value)}},
    action: {onClicked: {addListener: callback => {events.click = callback;}},
      setBadgeText: async value => {badges.push(value.text);}},
    alarms: {create: async (name, settings) => {assert.equal(settings.periodInMinutes, 0.5);},
      onAlarm: {addListener: callback => {events.alarm = callback;}}},
    scripting: {executeScript: async options => {
      assert.equal(options.world, "MAIN");
      assert.equal(options.target.tabId, 7);
      if (options.files) {assert.deepEqual(Array.from(options.files), ["page.js"]); injected++; return [];}
      return [{result: options.func(...(options.args || []))}];
    }}
  };
  const context = vm.createContext({chrome, URL, AbortSignal,
    window: {__fcConfigurationObserverV2: {peek: () => queued.slice(), ack: count => {acknowledgements++; queued.splice(0, count);}}},
    fetch: async (url, options) => {
      assert.ok(url === "http://127.0.0.1:8766/attached" || url === "http://127.0.0.1:8766/observation");
      assert.equal(options.credentials, "omit"); assert.equal(options.redirect, "error");
      posts.push({url, value: JSON.parse(options.body)});
      return {ok: !(url.endsWith("/observation") && failDelivery)};
    }});
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../browser/observer/worker.js"), "utf8"), context);
  await events.click({id: 7, url: "https://attacker.invalid/ultimate-team/web-app/"});
  assert.equal(injected, 0); assert.equal(badges.at(-1), "WAIT");
  await events.click({id: 7, url: "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"});
  assert.equal(injected, 1); assert.equal(stored.observedTab, 7);
  assert.equal(acknowledgements, 0, "failed delivery must retain the batch");
  assert.equal(queued.length, 1); assert.equal(badges.at(-1), "WAIT");
  failDelivery = false;
  events.alarm({name: "fc-observer-poll"});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(queued.length, 0); assert.equal(acknowledgements, 1); assert.equal(badges.at(-1), "ON");
  assert.deepEqual(posts.find(p => p.url.endsWith("/attached")).value, {observer_installed: true, observer_version: 2});
}
main().catch(() => { console.error("FAIL: observer behavioral check"); process.exitCode = 1; });

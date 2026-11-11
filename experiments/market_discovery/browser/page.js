/* Independently authored search-only adapter based on reviewed local read bridge.
 * No credentials, raw identifiers, raw error messages or native objects leave here.
 */
(() => {
  "use strict";
  if (window.__fcDiscoverySearchV1) return;
  const number = v => Number.isSafeInteger(v) && v >= 0 ? v : null;
  const empty = error => ({status: null, success: false, error, ea_error_code: null, platform: null,
    credits: null, items: null, auctions: null, has_more: null, cache_invalidated: null, network: []});
  function valid(c) {
    if (!c || Object.keys(c).sort().join() !== "evidence_key,id,operation,params" || c.operation !== "search" ||
        typeof c.id !== "string" || !/^[a-f0-9]{32}$/.test(c.id) || typeof c.evidence_key !== "string" || !/^[a-f0-9]{32}$/.test(c.evidence_key)) return false;
    const p = c.params;
    if (!p || typeof p !== "object" || Array.isArray(p) || p.count !== 21 || ![1,2].includes(p.page) || typeof p.fresh !== "boolean") return false;
    for (const [k,v] of Object.entries(p)) {
      if (!["page","count","fresh","definition_id","min_buy","max_buy","club","league"].includes(k)) return false;
      if (k !== "fresh" && (!Number.isSafeInteger(v) || v < (["page","count","definition_id"].includes(k) ? 1 : 0))) return false;
    }
    return (p.min_buy ?? 0) <= (p.max_buy ?? Number.MAX_SAFE_INTEGER);
  }
  async function id(value, namespace, key) {
    if (!(typeof value === "string" && /^[0-9]{1,24}$/.test(value)) && !(Number.isSafeInteger(value) && value >= 0)) throw new Error("unsafe_integer");
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${key}|${namespace}|${value}`));
    return namespace + ":" + [...new Uint8Array(hash)].map(v => v.toString(16).padStart(2,"0")).join("").slice(0,24);
  }
  async function auction(raw, key) {
    const a = raw.getAuctionData?.() || raw.auctionData || raw._auction || raw;
    const i = raw.itemData || raw;
    if (!Number.isSafeInteger(i.definitionId) || i.definitionId < 1) throw new Error("schema_unrecognized");
    return {trade_id: await id(a.tradeId,"trade",key), starting_bid: number(a.startingBid), current_bid: number(a.currentBid),
      buy_now_price: number(a.buyNowPrice), expires: a.expires === -1 ? -1 : number(a.expires),
      trade_state: ["active","closed","expired","inactive"].includes(a.tradeState) ? a.tradeState : null,
      bid_state: ["none","highest","outbid","buyNow","sold"].includes(a.bidState) ? a.bidState : null,
      item: {item_id: await id(i.id,"item",key), definition_id: i.definitionId, resource_id: number(i.resourceId), asset_id: number(i.assetId),
        rating: number(i.rating), rarity: number(i.rareflag), nation: number(i.nationId), league: number(i.leagueId), club: number(i.teamId),
        position: null, untradeable: typeof i.untradeable === "boolean" ? i.untradeable : null,
        market_average: number(i.marketAverage), last_sale_price: number(i.lastSalePrice)}};
  }
  function observe(value) {
    if (typeof value?.observe !== "function") throw new Error("service_unavailable");
    return new Promise((resolve,reject) => {
      let done = false;
      const owner = {};
      const timer = setTimeout(() => {if (!done) {done = true; value.unobserve?.(owner); reject(new Error("service_timeout"));}},15000);
      try {
        value.observe(owner,(sender,response) => {
          if (done) return;
          done = true; clearTimeout(timer); sender?.unobserve?.(owner); resolve(response);
        });
      } catch { done = true; clearTimeout(timer); value.unobserve?.(owner); reject(new Error("internal_error")); }
    });
  }
  function capture(rows) {
    const proto = XMLHttpRequest.prototype;
    const original = {open: proto.open, send: proto.send, header: proto.setRequestHeader};
    const pending = new WeakMap();
    const open = function(method,url,...rest) {
      let metadata = null;
      try {
        const u = new URL(url,location.href);
        if (method === "GET" && u.protocol === "https:" && /^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname) && /^\/ut\/game\/fc27\/(?:user\/credits|user\/currencies|transfermarket|club|purchased\/items|unassigned|tradepile|usermassinfo)$/.test(u.pathname))
          metadata = {host: u.hostname,path:u.pathname,session_header_present:false};
      } catch {}
      pending.set(this,metadata);
      return original.open.call(this,method,url,...rest);
    };
    const header = function(name,value) {
      const m = pending.get(this);
      // Presence only; the header value is passed through without being retained.
      if (m && String(name).toLowerCase() === "x-ut-sid") m.session_header_present = true;
      return original.header.call(this,name,value);
    };
    const send = function(...args) {
      const m = pending.get(this);
      if (m) this.addEventListener("loadend",() => {if (rows.length < 30 && this.status >= 100 && this.status <= 599) rows.push({...m,status:this.status});},{once:true});
      return original.send.apply(this,args);
    };
    proto.open = open; proto.setRequestHeader = header; proto.send = send;
    return () => {
      if (proto.open === open) proto.open = original.open;
      if (proto.setRequestHeader === header) proto.setRequestHeader = original.header;
      if (proto.send === send) proto.send = original.send;
    };
  }
  let busy = false;
  async function search(c, workerMark = null) {
    const began = performance.now();
    let nativeBegan = null;
    const timing = {worker_poll_to_native_ms:null,native_service_ms:null,page_total_ms:null};
    let result = empty("invalid_command");
    const finish = () => {timing.page_total_ms = performance.now()-(nativeBegan ?? began); return {result,timing};};
    if (!valid(c)) return finish();
    if (location.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(location.hostname) || !/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname)) {
      result = empty("wrong_page"); return finish();
    }
    if (busy) {result = empty("bridge_busy"); return finish();}
    busy = true;
    let restore = () => {};
    try {
      if (typeof services === "undefined" || typeof UTSearchCriteriaDTO !== "function" || typeof services.Item?.searchTransferMarket !== "function") throw new Error("service_unavailable");
      const persona = services.User?.getUser?.()?.getSelectedPersona?.();
      if (persona?.platform !== "pc" && !(persona?.platform == null && persona?.isPC === true)) throw new Error("schema_unrecognized");
      result = empty("internal_error"); result.platform = "pc";
      const p = c.params, criteria = new UTSearchCriteriaDTO();
      criteria.type = "player"; criteria.count = 21;
      if (p.definition_id != null) criteria.defId = [p.definition_id];
      for (const [k,v] of Object.entries({min_buy:"minBuy",max_buy:"maxBuy",club:"club",league:"league"})) if (p[k] != null) criteria[v] = p[k];
      if (p.fresh) {
        result.cache_invalidated = typeof services.Item.clearTransferMarketCache === "function";
        if (result.cache_invalidated) services.Item.clearTransferMarketCache();
      }
      restore = capture(result.network);
      const nativeStart = performance.now();
      nativeBegan = nativeStart;
      // Performance timeOrigin normalizes worker/page time origins on this browser.
      const delay = performance.timeOrigin + nativeStart-workerMark;
      if (typeof workerMark === "number" && Number.isFinite(delay) && delay >= 0 && delay <= 120000) timing.worker_poll_to_native_ms = delay;
      let response;
      try { response = await observe(services.Item.searchTransferMarket(criteria,p.page)); }
      finally { timing.native_service_ms = performance.now()-nativeStart; }
      await new Promise(resolve => setTimeout(resolve,0)); // XHR loadend may follow observable completion
      result.status = Number.isInteger(response?.status) && response.status >= 100 && response.status <= 599 ? response.status : null;
      result.ea_error_code = number(response?.error?.code);
      if (response?.success !== true) {result.error = "service_failed"; return finish();}
      const payload = response.data ?? response.response;
      const rows = payload?.items ?? payload?.auctionInfo;
      if (!Array.isArray(rows) || rows.length > 21) throw new Error("schema_unrecognized");
      result.auctions = await Promise.all(rows.map(row => auction(row,c.evidence_key)));
      result.has_more = typeof payload.hasMore === "boolean" ? payload.hasMore : null;
      result.error = null; result.success = true;
      return finish();
    } catch (e) {
      result.error = ["service_unavailable","service_timeout","schema_unrecognized","unsafe_integer"].includes(e?.message) ? e.message : "internal_error";
      return finish();
    } finally {restore(); busy = false;}
  }
  Object.defineProperty(window,"__fcDiscoverySearchV1",{value:Object.freeze({search})});
})();

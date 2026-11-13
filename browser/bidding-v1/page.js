/* Protocol 1 one-shot native adapter. Load persona.js first in the official tab.
 * The reviewed host supplies durable ownership; this page adds in-memory fencing.
 * No actor loop, endpoint emulation, credential access, or raw ID export.
 */
(() => {
  "use strict";
  if (window.__fcBiddingV1) return;
  const number = v => Number.isSafeInteger(v) && v >= 0 ? v : null;
  const hex = v => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
  const empty = error => ({status:null, success:false, error, ea_error_code:null, platform:null,
    credits:null, items:null, auctions:null, has_more:null, cache_invalidated:null, network:[]});
  const known = new Map(), sent = new Set();
  let busy = false, session = null;
  function attach(scope, owner, epoch) {
    if (!hex(scope) || !hex(owner) || !Number.isSafeInteger(epoch) || epoch < 1 || busy ||
        session && (scope !== session.scope || epoch <= session.epoch)) return false;
    session = {scope, owner, epoch}; known.clear(); return true;
  }
  function valid(c) {
    if (!c || Object.keys(c).sort().join() !== "epoch,evidence_key,id,operation,owner,params,schema,scope" ||
        c.schema !== 1 || !hex(c.id) || !hex(c.evidence_key) || !session ||
        c.scope !== session.scope || c.owner !== session.owner || c.epoch !== session.epoch) return false;
    const p = c.params;
    if (!p || typeof p !== "object" || Array.isArray(p)) return false;
    if (["watched", "balance"].includes(c.operation)) return Object.keys(p).length === 0;
    if (c.operation === "search") {
      if (p.count !== 21 || ![1,2].includes(p.page) || typeof p.fresh !== "boolean") return false;
      for (const [k,v] of Object.entries(p)) {
        if (!["page","count","fresh","definition_id","max_bid","min_buy","max_buy","club","league"].includes(k)) return false;
        if (k !== "fresh" && (!Number.isSafeInteger(v) || v < (["page","count","definition_id"].includes(k) ? 1 : 0))) return false;
      }
      return (p.min_buy ?? 0) <= (p.max_buy ?? Number.MAX_SAFE_INTEGER);
    }
    if (c.operation !== "bid" || Object.keys(p).sort().join() !== "amount,cap,deadline,definition_id,item_id,minimum,trade_id") return false;
    return typeof p.item_id === "string" && typeof p.trade_id === "string" && /^item:[a-f0-9]{24}$/.test(p.item_id) && /^trade:[a-f0-9]{24}$/.test(p.trade_id) &&
      [p.amount,p.cap,p.minimum,p.definition_id].every(v => Number.isSafeInteger(v) && v > 0) &&
      p.amount === p.minimum && p.amount <= p.cap && typeof p.deadline === "string" && Date.parse(p.deadline) > Date.now();
  }
  async function id(value, namespace, key) {
    if (!(typeof value === "string" && /^[0-9]{1,24}$/.test(value)) && !(Number.isSafeInteger(value) && value >= 0)) throw new Error("unsafe_integer");
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${key}|${namespace}|${value}`));
    return namespace + ":" + [...new Uint8Array(hash)].map(v => v.toString(16).padStart(2,"0")).join("").slice(0,24);
  }
  async function auction(raw, key, networkAt) {
    const a = raw.getAuctionData?.() || raw.auctionData || raw._auction || raw;
    const i = raw.itemData || raw;
    if (!Number.isSafeInteger(i.definitionId) || i.definitionId < 1) throw new Error("schema_unrecognized");
    const trade = await id(a.tradeId,"trade",key), item = await id(i.id,"item",key);
    if (known.size >= 1000) known.clear();
    known.set(key+"|"+trade, {raw, item, definition:i.definitionId, networkAt, a});
    return {trade_id:trade, starting_bid:number(a.startingBid), current_bid:number(a.currentBid),
      buy_now_price:number(a.buyNowPrice), expires:a.expires === -1 ? -1 : number(a.expires),
      trade_state:["active","closed","expired","inactive"].includes(a.tradeState) ? a.tradeState : null,
      bid_state:["none","highest","outbid","buyNow","sold"].includes(a.bidState) ? a.bidState : null,
      item:{item_id:item, definition_id:i.definitionId, resource_id:number(i.resourceId), asset_id:number(i.assetId),
        rating:number(i.rating), rarity:number(i.rareflag), nation:number(i.nationId), league:number(i.leagueId), club:number(i.teamId),
        position:null, untradeable:typeof i.untradeable === "boolean" ? i.untradeable : null,
        market_average:number(i.marketAverage), last_sale_price:number(i.lastSalePrice)}};
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
      } catch {done = true; clearTimeout(timer); value.unobserve?.(owner); reject(new Error("internal_error"));}
    });
  }
  function capture(rows, operation) {
    const proto = XMLHttpRequest.prototype;
    const original = {open:proto.open, send:proto.send, header:proto.setRequestHeader};
    const pending = new WeakMap();
    const routes = {search:["GET","transfermarket"], watched:["GET","watchlist"],
      balance:["GET","user/currencies"], bid:["PUT","trade/[0-9]{1,24}/bid"]};
    const [verb, route] = routes[operation];
    const open = function(method,url,...rest) {
      let metadata = null;
      try {
        const u = new URL(url,location.href);
        if (method === verb && u.protocol === "https:" && /^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname) &&
            new RegExp("^/ut/game/fc27/"+route+"$").test(u.pathname))
          metadata = {host:u.hostname,path:operation === "bid" ? "/ut/game/fc27/trade/:trade/bid" : u.pathname,session_header_present:false};
      } catch {}
      pending.set(this,metadata); return original.open.call(this,method,url,...rest);
    };
    const header = function(name,value) {
      const m = pending.get(this);
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
  async function execute(c) {
    const start = performance.now();
    const out = {schema:1, command_id:hex(c?.id) ? c.id : "0".repeat(32), operation:["search","watched","balance","bid"].includes(c?.operation) ? c.operation : null,
      result:empty("invalid_command"), freshness:{observed_at:new Date().toISOString(), network_at:null,
        request_count:0, read_id:hex(c?.id) ? c.id : "0".repeat(32), source:"native"},
      coverage:{complete:false, has_more:null, account_capacity:null, evidence_id:null}, timing:{native_service_ms:0}};
    if (!valid(c)) return out;
    if (location.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(location.hostname) || !/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname)) {
      out.result = empty("wrong_page"); return out;
    }
    if (busy) {out.result = empty("bridge_busy"); return out;}
    busy = true;
    let restore = () => {};
    try {
      if (window.__fcDiscoveryPersonaFollowupV1?.selectedPlatform() !== "pc") throw new Error("schema_unrecognized");
      const p = c.params, r = out.result = empty("internal_error"); r.platform = "pc";
      let invoke;
      if (c.operation === "search") {
        const criteria = new UTSearchCriteriaDTO(); criteria.type = "player"; criteria.count = 21;
        if (p.definition_id != null) criteria.defId = [p.definition_id];
        for (const [k,v] of Object.entries({max_bid:"maxBid",min_buy:"minBuy",max_buy:"maxBuy",club:"club",league:"league"})) if (p[k] != null) criteria[v] = p[k];
        if (p.fresh) {r.cache_invalidated = typeof services.Item.clearTransferMarketCache === "function"; if (r.cache_invalidated) services.Item.clearTransferMarketCache();}
        invoke = () => services.Item.searchTransferMarket(criteria,p.page);
      } else if (c.operation === "watched") invoke = () => services.Item.requestWatchedItems();
      else if (c.operation === "balance") invoke = () => services.User.requestCurrencies();
      else {
        const entry = known.get(c.evidence_key+"|"+p.trade_id);
        if (!entry || entry.item !== p.item_id || entry.definition !== p.definition_id || entry.raw.untradeable !== false ||
            !entry.networkAt || Date.now()-Date.parse(entry.networkAt) > 30000 ||
            Date.now() >= Date.parse(entry.networkAt)+entry.a.expires*1000 ||
            entry.a.tradeState !== "active" || entry.a.bidState === "highest" || entry.a.expires <= 0 ||
            p.amount < entry.a.startingBid || p.amount <= entry.a.currentBid || p.amount >= entry.a.buyNowPrice ||
            sent.has(c.id) || sent.has(c.evidence_key+"|"+p.trade_id)) throw new Error("invalid_command");
        sent.add(c.id); sent.add(c.evidence_key+"|"+p.trade_id);
        known.delete(c.evidence_key+"|"+p.trade_id);
        invoke = () => services.Item.bid(entry.raw,p.amount);
      }
      restore = capture(r.network,c.operation);
      const networkLowerBound = new Date().toISOString();
      const response = await observe(invoke());
      await new Promise(resolve => setTimeout(resolve,0));
      r.status = Number.isInteger(response?.status) && response.status >= 100 && response.status <= 599 ? response.status : null;
      r.ea_error_code = number(response?.error?.code);
      out.freshness.request_count = r.network.length;
      const fresh = r.network.some(n => n.session_header_present && n.status >= 200 && n.status < 300);
      out.freshness.network_at = fresh ? networkLowerBound : null;
      if (response?.success !== true) {r.error = "service_failed"; return out;}
      const data = response.data ?? response.response;
      if (["search","watched"].includes(c.operation)) {
        const rows = data?.items ?? data?.auctionInfo;
        if (!Array.isArray(rows) || rows.length > (c.operation === "search" ? 21 : 100)) throw new Error("schema_unrecognized");
        r.auctions = await Promise.all(rows.map(row => auction(row,c.evidence_key,out.freshness.network_at)));
        r.has_more = typeof data.hasMore === "boolean" ? data.hasMore : null;
        out.coverage.has_more = r.has_more;
        // Native success/empty arrays cannot prove watchlist completeness or capacity.
      } else if (c.operation === "balance") {
        const coins = data?.currencies?.find?.(x => x.name === "COINS");
        r.credits = number(data?.credits ?? coins?.funds);
        if (r.credits === null) throw new Error("schema_unrecognized");
      }
      r.success = true; r.error = null;
    } catch (e) {
      out.result.success = false;
      out.result.error = ["service_unavailable","service_timeout","schema_unrecognized","unsafe_integer","invalid_command"].includes(e?.message) ? e.message : "internal_error";
    } finally {
      restore(); busy = false;
      out.freshness.observed_at = new Date().toISOString();
      out.freshness.request_count = out.result.network.length;
      out.timing.native_service_ms = performance.now()-start;
    }
    return out;
  }
  // Reconciliation unlocks another MINIMUM bid, never repeats a command ID.
  function reconciled(scope, owner, epoch, evidenceKey, trade) {
    if (busy || !session || session.scope !== scope || session.owner !== owner || session.epoch !== epoch ||
        !hex(evidenceKey) || !/^trade:[a-f0-9]{24}$/.test(trade)) return false;
    sent.delete(evidenceKey+"|"+trade); return true;
  }
  Object.defineProperty(window,"__fcBiddingV1",{value:Object.freeze({attach,execute,reconciled})});
})();

/* Locally authored, bounded native reads. Never reads authentication values.
 * Unknown properties and exception text never cross the page boundary.
 */
(() => {
  "use strict";
  if (window.__fcReadBridgeV1) return;
  const positions = new Set(["GK", "CB", "LB", "RB", "LWB", "RWB", "CDM", "CM", "CAM", "LM", "RM", "LW", "RW", "CF", "ST"]);
  const num = v => Number.isSafeInteger(v) && v >= 0 ? v : null;
  const empty = error => ({status: null, success: false, error, ea_error_code: null, platform: null,
    credits: null, items: null, auctions: null, has_more: null, cache_invalidated: null, network: []});
  const platform = () => {
    const persona = services.User?.getUser?.()?.getSelectedPersona?.();
    const p = persona?.platform;
    return ["pc", "ps3", "ps4", "ps5", "xbox", "xbox360", "xboxone", "xbsx", "switch"].includes(p) ? p : persona?.isPC === true ? "pc" : null;
  };
  async function id(value, namespace, key) {
    if (value == null) return null;
    if (!(typeof value === "string" && /^[0-9]{1,24}$/.test(value)) && !(Number.isSafeInteger(value) && value >= 0)) throw new Error("unsafe_integer");
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${key}|${namespace}|${value}`));
    return namespace + ":" + [...new Uint8Array(bytes)].map(v => v.toString(16).padStart(2, "0")).join("").slice(0, 24);
  }
  async function item(raw, key) {
    if (!raw || typeof raw !== "object") throw new Error("schema_unrecognized");
    return {item_id: await id(raw.id, "item", key), resource_id: num(raw.resourceId), definition_id: num(raw.definitionId),
      asset_id: num(raw.assetId), rating: num(raw.rating), rarity: num(raw.rareflag), nation: num(raw.nationId), league: num(raw.leagueId),
      club: num(raw.teamId), position: positions.has(raw.preferredPosition) ? raw.preferredPosition : null,
      untradeable: typeof raw.untradeable === "boolean" ? raw.untradeable : null,
      market_average: num(raw.marketAverage), last_sale_price: num(raw.lastSalePrice)};
  }
  async function auction(raw, key) {
    const a = raw.getAuctionData?.() || raw.auctionData || raw._auction || raw;
    return {trade_id: await id(a.tradeId, "trade", key), starting_bid: num(a.startingBid), current_bid: num(a.currentBid),
      buy_now_price: num(a.buyNowPrice), expires: a.expires === -1 ? -1 : num(a.expires),
      trade_state: ["active", "closed", "expired", "inactive"].includes(a.tradeState) ? a.tradeState : null,
      bid_state: ["none", "highest", "outbid", "buyNow", "sold"].includes(a.bidState) ? a.bidState : null,
      item: await item(raw.itemData || raw, key)};
  }
  function observe(value) {
    if (typeof value?.observe !== "function") return Promise.reject(new Error("service_unavailable"));
    return new Promise((resolve, reject) => {
      const owner = {};
      let done = false;
      const timer = setTimeout(() => {
        if (done) return;
        done = true;
        value.unobserve?.(owner);
        reject(new Error("service_timeout"));
      }, 15000);
      try {
        value.observe(owner, (sender, response) => {
          if (done) return;
          done = true;
          clearTimeout(timer);
          sender?.unobserve?.(owner);
          resolve(response);
        });
      } catch {
        done = true;
        clearTimeout(timer);
        value.unobserve?.(owner);
        reject(new Error("internal_error"));
      }
    });
  }
  // Capture only exact generic GET paths, numeric statuses, and header presence.
  // Original wrappers (including the task_02 observer) are restored after each read.
  function networkCapture(rows) {
    const proto = XMLHttpRequest.prototype;
    const original = {open: proto.open, setRequestHeader: proto.setRequestHeader, send: proto.send};
    const pending = new WeakMap();
    const allowed = /^(\/ut\/game\/fc27\/(?:user\/credits|user\/currencies|transfermarket|club|purchased\/items|unassigned|tradepile|usermassinfo))$/;
    function metadata(url, method) {
      try {
        const u = new URL(url, location.href);
        if (method.toUpperCase() !== "GET" || u.protocol !== "https:" || !/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname) || !allowed.test(u.pathname)) return null;
        return {host: u.hostname, path: u.pathname, session_header_present: false};
      } catch { return null; }
    }
    const open = function(method, url, ...rest) {pending.set(this, metadata(String(url), String(method))); return original.open.call(this, method, url, ...rest);};
    const header = function(name, value) {const m = pending.get(this); if (m && String(name).toLowerCase() === "x-ut-sid") m.session_header_present = true; return original.setRequestHeader.call(this, name, value);};
    const send = function(...args) {const m = pending.get(this); if (m) this.addEventListener("loadend", () => {if (rows.length < 30 && this.status >= 100 && this.status <= 599) rows.push({...m, status: this.status});}, {once: true}); return original.send.apply(this, args);};
    proto.open = open; proto.setRequestHeader = header; proto.send = send;
    return () => {if (proto.open === open) proto.open = original.open; if (proto.setRequestHeader === header) proto.setRequestHeader = original.setRequestHeader; if (proto.send === send) proto.send = original.send;};
  }
  function valid(c) {
    if (!c || Object.keys(c).sort().join() !== "evidence_key,id,operation,params" || !/^[a-f0-9]{32}$/.test(c.id) || !/^[a-f0-9]{32}$/.test(c.evidence_key)) return false;
    if (!["coins", "club", "unassigned", "purchased", "transfer_list", "search"].includes(c.operation) || !c.params || typeof c.params !== "object" || Array.isArray(c.params)) return false;
    const allowed = c.operation === "search" ? ["page", "count", "definition_id", "max_buy", "min_buy", "nation", "league", "club", "rarity", "position", "fresh"] : c.operation === "club" ? ["start", "count"] : [];
    for (const [k, v] of Object.entries(c.params)) {
      if (!allowed.includes(k)) return false;
      if (k === "fresh" ? typeof v !== "boolean" : k === "position" ? !positions.has(v) : !Number.isSafeInteger(v) || v < (["page", "count", "definition_id"].includes(k) ? 1 : 0)) return false;
    }
    return (c.params.page ?? 1) <= 2 && (c.params.count ?? 1) <= (c.operation === "search" ? 21 : 100) && (c.params.start ?? 0) <= 10000 && (c.params.min_buy ?? 0) <= (c.params.max_buy ?? Number.MAX_SAFE_INTEGER);
  }
  let busy = false;
  async function read(c) {
    if (!valid(c)) return empty("invalid_command");
    if (location.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(location.hostname) || !/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname)) return empty("wrong_page");
    if (busy) return empty("bridge_busy");
    busy = true;
    const out = empty("internal_error");
    let restore = () => {};
    try {
      if (typeof services === "undefined") return empty("service_unavailable");
      restore = networkCapture(out.network);
      const p = c.params, op = c.operation;
      let response;
      if (op === "search" || op === "club") {
        if (typeof UTSearchCriteriaDTO !== "function") return empty("service_unavailable");
        const criteria = new UTSearchCriteriaDTO();
        criteria.type = "player";
        criteria.count = p.count ?? (op === "search" ? 21 : 20);
        if (op === "club") {
          criteria.offset = p.start ?? 0;
          if (typeof services.Club?.search !== "function") return empty("service_unavailable");
          response = await observe(services.Club.search(criteria));
        } else {
          if (p.definition_id != null) criteria.defId = [p.definition_id];
          for (const [k, v] of Object.entries({max_buy: "maxBuy", min_buy: "minBuy", nation: "nationality", league: "league", club: "club", rarity: "rarity", position: "position"})) if (p[k] != null) criteria[v] = p[k];
          if (p.fresh) {
            out.cache_invalidated = typeof services.Item?.clearTransferMarketCache === "function";
            if (out.cache_invalidated) services.Item.clearTransferMarketCache();
          }
          if (typeof services.Item?.searchTransferMarket !== "function") return empty("service_unavailable");
          response = await observe(services.Item.searchTransferMarket(criteria, p.page ?? 1));
        }
      } else {
        const service = op === "coins" ? services.User : services.Item;
        const method = {coins: "requestCurrencies", unassigned: "requestUnassignedItems", purchased: "requestPurchasedItems", transfer_list: "requestTransferItems"}[op];
        if (typeof service?.[method] !== "function") return empty("service_unavailable");
        response = await observe(service[method]());
      }
      // Native observables can resolve at readyState 4, before XHR loadend fires.
      await new Promise(resolve => setTimeout(resolve, 0));
      out.status = Number.isInteger(response?.status) && response.status >= 100 && response.status <= 599 ? response.status : null;
      out.ea_error_code = num(response?.error?.code);
      out.platform = platform();
      if (response?.success !== true) {out.error = "service_failed"; return out;}
      const payload = response.data ?? response.response;
      if (c.operation === "coins") {
        // Read back the wallet after the currency service completes; never export the user.
        const user = services.User.getUser?.();
        out.credits = num(payload?.credits) ?? num(user?.coins?.amount) ?? num(user?.credits?.amount) ?? num(user?.credits);
        if (out.credits === null) throw new Error("schema_unrecognized");
      } else {
        const rows = payload?.items ?? payload?.auctionInfo ?? payload?.itemData;
        if (!Array.isArray(rows) || rows.length > 100) throw new Error("schema_unrecognized");
        if (["search", "transfer_list"].includes(c.operation)) out.auctions = await Promise.all(rows.map(r => auction(r, c.evidence_key)));
        else out.items = await Promise.all(rows.map(r => item(r, c.evidence_key)));
        out.has_more = typeof payload?.hasMore === "boolean" ? payload.hasMore : null;
      }
      out.success = true; out.error = null;
      return out;
    } catch (e) {
      out.error = ["service_unavailable", "service_timeout", "schema_unrecognized", "unsafe_integer"].includes(e?.message) ? e.message : "internal_error";
      return out;
    } finally {restore(); busy = false;}
  }
  Object.defineProperty(window, "__fcReadBridgeV1", {value: Object.freeze({read})});
})();

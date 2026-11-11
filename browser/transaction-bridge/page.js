/* Locally authored bounded writes. Authentication stays in EA native services.
 * Native acknowledgments are never transaction proof: Python re-reads state.
 */
(() => {
  "use strict";
  if (window.__fcTransactionBridgeV3) return;
  const api = window.__fcTransactionReadV3;
  if (!api) return;
  let busy = false;
  const intended = new Set();
  const writes = new Set(["buy", "move", "list", "relist"]);
  const fields = {
    buy: ["item_id", "trade_id", "definition_id", "buy_now_price"],
    move: ["item_id", "definition_id"],
    list: ["item_id", "definition_id", "starting_bid", "buy_now_price", "duration"],
    relist: ["item_id", "definition_id", "starting_bid", "buy_now_price", "duration"], status: []
  };
  function valid(c) {
    if (!c || Object.keys(c).sort().join() !== "evidence_key,id,operation,params" ||
        !/^[a-f0-9]{32}$/.test(c.id) || !/^[a-f0-9]{32}$/.test(c.evidence_key) ||
        !c.params || typeof c.params !== "object" || Array.isArray(c.params)) return false;
    const expected = fields[c.operation];
    if (!expected || Object.keys(c.params).sort().join() !== [...expected].sort().join()) return false;
    const p = c.params;
    for (const [k, v] of Object.entries(p)) {
      if (k === "item_id" || k === "trade_id") {
        if (typeof v !== "string" || !(new RegExp(`^${k === "item_id" ? "item" : "trade"}:[a-f0-9]{24}$`)).test(v)) return false;
      } else if (!Number.isSafeInteger(v) || v <= 0) return false;
    }
    if (c.operation === "buy" && !(p.buy_now_price >= 200 && p.buy_now_price <= 500)) return false;
    if (["list", "relist"].includes(c.operation) && !(p.duration === 3600 && p.starting_bid >= 150 &&
        p.starting_bid < p.buy_now_price && p.buy_now_price <= 1000 && p.starting_bid % 50 === 0 && p.buy_now_price % 50 === 0)) return false;
    return true;
  }
  async function run(c) {
    if (!writes.has(c?.operation) && c?.operation !== "status") return api.read(c);
    if (!valid(c)) return api.empty("invalid_command");
    if (location.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(location.hostname) ||
        !/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname)) return api.empty("wrong_page");
    if (busy) return api.empty("bridge_busy");
    busy = true;
    const out = api.empty("internal_error");
    try {
      if (c.operation === "status") return await api.read({...c, operation: "transfer_list"});
      const p = c.params, token = c.operation;
      // Even changing the request ID cannot cause a second purchase/list dispatch.
      if (intended.has(token)) return api.empty("invalid_command");
      if (c.operation === "buy") {
        const r = await api.read({...c, operation: "search", params: {
          definition_id: p.definition_id, max_buy: p.buy_now_price, page: 1, count: 21, fresh: true}});
        if (!r.success || !r.auctions?.some(a => a.trade_id === p.trade_id && a.item.item_id === p.item_id &&
            a.item.definition_id === p.definition_id && a.item.untradeable === false &&
            a.buy_now_price === p.buy_now_price && a.trade_state === "active" && a.expires > 0)) return api.empty("invalid_command");
      } else {
        const r = await api.read({...c, operation: c.operation === "move" ? "unassigned" : "transfer_list", params: {}});
        if (!r.success) return r;
      }
      const item = api.known.get(c.evidence_key + "|" + p.item_id);
      if (!item || item.definitionId !== p.definition_id || api.untradeable(item) !== false || item.isPlayer?.() !== true) return api.empty("invalid_command");
      const auction = item.getAuctionData?.() || item.auctionData || item._auction || {};
      if (c.operation === "buy" && (await api.id(auction.tradeId, "trade", c.evidence_key) !== p.trade_id ||
          auction.buyNowPrice !== p.buy_now_price || auction.tradeState !== "active")) return api.empty("invalid_command");
      if (c.operation === "list" && auction.tradeState === "active") return api.empty("invalid_command");
      if (c.operation === "relist" && !(auction.tradeState === "expired" && auction.expires === -1 && auction.currentBid === 0)) return api.empty("invalid_command");
      intended.add(token);  // Never cleared after errors or timeouts.
      let response;
      if (c.operation === "buy") response = await api.observe(services.Item.bid(item, p.buy_now_price));
      if (c.operation === "move") response = await api.observe(services.Item.move([item], ItemPile.TRANSFER, false));
      if (["list", "relist"].includes(c.operation)) response = await api.observe(services.Item.list(item, p.starting_bid, p.buy_now_price, p.duration));
      out.status = Number.isInteger(response?.status) && response.status >= 100 && response.status <= 599 ? response.status : null;
      out.ea_error_code = Number.isSafeInteger(response?.error?.code) && response.error.code >= 0 ? response.error.code : null;
      out.platform = api.platform();
      out.success = response?.success === true;
      out.error = out.success ? null : "service_failed";
    } catch (e) {
      out.error = ["service_timeout", "service_unavailable", "unsafe_integer", "schema_unrecognized"].includes(e?.message) ? e.message : "internal_error";
    } finally { busy = false; }
    return out;
  }
  Object.defineProperty(window, "__fcTransactionBridgeV3", {value: Object.freeze({run})});
})();

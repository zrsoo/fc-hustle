/* First-party observer. Observes ordinary requests; never initiates an EA request.
 * Credentials remain in the page. No raw URL, body, response, or header value is exported.
 */
(() => {
  "use strict";
  if (window.__fcConfigurationObserverV2) return;
  const queue = [];
  const pending = new WeakMap();
  let clientId = null, sku = null;
  function configurationIdentifier() {
    // Source-reviewed public getter used by EA's own login view. Read this one
    // public key only; never enumerate the repository or read its secret keys.
    try {
      if (typeof getAppMain === "function" && typeof EAConfigurationRepository !== "undefined") {
        const key = EAConfigurationRepository.KEY_EADP_CLIENT_ID;
        if (typeof key === "string") identifier(getAppMain()?.getConfigRepository()?.getConfigString(key));
      }
    } catch { /* An unavailable configuration is not a default value. */ }
  }
  // Login redirects can use document/script resources instead of Fetch/XHR.
  // Inspect only literal public identifiers; never export resource URLs.
  function resourceIdentifiers(raw) {
    const url = allowedUrl(raw);
    if (!url) return;
    for (const key of ["sku", "client", "client_id"]) identifier(url.searchParams.get(key));
  }
  function allowedUrl(raw) {
    try {
      const u = new URL(raw, location.href);
      return u.protocol === "https:" && /(^|\.)ea\.com$/.test(u.hostname) ? u : null;
    } catch { return null; }
  }
  function identifier(value) {
    if (typeof value !== "string") return;
    if (/^FC[0-9]{2}_JS_WEB_APP$/.test(value)) clientId = value;
    if (/^FUT[0-9]{2}WEB$/.test(value)) sku = value;
  }
  function bodyIdentifiers(body, url) {
    // Inspect only explicit public configuration keys on EA UT JSON requests.
    if (!url || !/^\/ut\//.test(url.pathname) || typeof body !== "string" || body.length > 65536) return;
    try {
      const parsed = JSON.parse(body);
      for (const key of ["sku", "client", "clientId", "client_id", "clientVersion"]) identifier(parsed?.[key]);
    } catch { /* Not a JSON request. */ }
  }
  function metadata(raw, method) {
    const url = allowedUrl(raw);
    if (!url) return null;
    for (const key of ["sku", "client", "client_id"]) identifier(url.searchParams.get(key));
    const match = /^\/ut\/game\/(fc[0-9]{2})\//.exec(url.pathname);
    if (!match || !/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(url.hostname)) return null;
    return {game_version: match[1], host: url.host, request_prefix: match[0],
            method: String(method).toUpperCase(), session_header_present: false,
            // Keep only a small route enum inside the page; discard resource IDs and query strings.
            route: /^\/ut\/game\/fc[0-9]{2}\/(user\/credits|user\/currencies|usermassinfo|transfermarket|club)(?:\/|$)/.exec(url.pathname)?.[1] || "other"};
  }
  function header(meta, name, value) {
    const key = String(name).toLowerCase();
    // Deliberately do not read, copy, hash, or retain the session header's value.
    if (meta && key === "x-ut-sid") meta.session_header_present = true;
    if (["x-ut-sku", "x-ut-client", "x-ut-client-id", "x-ea-client-id"].includes(key)) identifier(value);
  }
  function responseShape(meta, body, depth = 0) {
    if (!body || typeof body !== "object") return "none";
    if (["user/credits", "user/currencies", "usermassinfo"].includes(meta.route) && Number.isFinite(body.credits) && body.credits >= 0) return "credits";
    if (meta.route === "transfermarket" && Array.isArray(body.auctionInfo)) return "auctionInfo";
    if (meta.route === "club" && Array.isArray(body.itemData)) return "itemData";
    // Some adapters wrap the REST result. Only fixed wrapper keys are inspected.
    if (depth < 2) for (const key of ["data", "response", "userInfo"]) {
      const shape = responseShape(meta, body[key], depth + 1);
      if (shape !== "none") return shape;
    }
    return "none";
  }
  async function xhrShape(xhr, meta) {
    if (xhr.responseType === "json") return responseShape(meta, xhr.response);
    let text;
    if (xhr.responseType === "arraybuffer" && xhr.response?.byteLength <= 2000000)
      text = new TextDecoder().decode(xhr.response);
    else if (xhr.responseType === "blob" && xhr.response?.size <= 2000000)
      text = await xhr.response.text();
    else if ((!xhr.responseType || xhr.responseType === "text") && xhr.responseText.length <= 2000000)
      text = xhr.responseText;
    return text === undefined ? "none" : responseShape(meta, JSON.parse(text));
  }
  function record(meta, status, shape = "none", responseType = "unknown") {
    if (!meta || !Number.isInteger(status) || status < 100 || status > 599) return;
    configurationIdentifier();
    const year = meta.game_version.slice(2);
    const auth = meta.method === "GET" && status >= 200 && status < 300 && meta.session_header_present && shape !== "none";
    queue.push({event: auth ? "authenticated_read" : [401,403,440,460,461].includes(status) ? "auth_rejected" : "configured_request",
      observed_at: new Date().toISOString(), game_version: meta.game_version, host: meta.host,
      request_prefix: meta.request_prefix, client_id: clientId === `FC${year}_JS_WEB_APP` ? clientId : null,
      sku: sku === `FUT${year}WEB` ? sku : null, method: meta.method, status,
      session_header_present: meta.session_header_present, response_shape: shape,
      observer_version: 2, route: meta.route,
      response_type: ["json", "text", "arraybuffer", "blob", "document"].includes(responseType) ? responseType : "unknown"});
    if (queue.length > 200) queue.shift();
  }
  const open = XMLHttpRequest.prototype.open;
  const setHeader = XMLHttpRequest.prototype.setRequestHeader;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, raw, ...rest) {
    const result = open.call(this, method, raw, ...rest);
    try { pending.set(this, {meta: metadata(raw, method), url: allowedUrl(raw)}); } catch { /* Preserve page behavior. */ }
    return result;
  };
  XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
    const result = setHeader.call(this, name, value);
    try { header(pending.get(this)?.meta, name, value); } catch { /* Preserve page behavior. */ }
    return result;
  };
  XMLHttpRequest.prototype.send = function(body) {
    try {
      const request = pending.get(this);
      if (request) bodyIdentifiers(body, request.url);
      if (request?.meta) this.addEventListener("loadend", async () => {
        try {
          let shape = "none";
          const final = metadata(this.responseURL, request.meta.method);
          const sameRoute = final && final.host === request.meta.host && final.request_prefix === request.meta.request_prefix && final.route === request.meta.route;
          if (sameRoute && request.meta.method === "GET" && this.status >= 200 && this.status < 300) {
            shape = await xhrShape(this, request.meta);
          }
          record(request.meta, this.status, shape, this.responseType || "text");
        } catch { record(request.meta, this.status, "none", this.responseType || "text"); }
      }, {once: true});
    } catch { /* Preserve page behavior. */ }
    return send.call(this, body);
  };
  const fetch = window.fetch;
  window.fetch = function(input, init) {
    let meta = null;
    try {
      const raw = typeof input === "string" || input instanceof URL ? String(input) : input.url;
      meta = metadata(raw, init?.method || input?.method || "GET");
      bodyIdentifiers(init?.body, allowedUrl(raw));
      const headers = new Headers(input instanceof Request ? input.headers : undefined);
      new Headers(init?.headers).forEach((value, name) => headers.set(name, value));
      // Headers.has avoids retrieving a session value.
      if (meta) meta.session_header_present = headers.has("x-ut-sid");
      for (const key of ["x-ut-sku", "x-ut-client", "x-ut-client-id", "x-ea-client-id"]) identifier(headers.get(key));
    } catch { /* Preserve page behavior. */ }
    const result = fetch.call(this, input, init);
    if (meta) result.then(async response => {
      try {
        // A redirected response cannot prove the original authenticated route.
        if (response.redirected) return record(meta, response.status);
        let shape = "none";
        if (meta.method === "GET" && response.ok && meta.route !== "other")
          shape = responseShape(meta, await response.clone().json());
        record(meta, response.status, shape, "json");
      } catch { record(meta, response.status); }
    }, () => {});
    return result;
  };
  try {
    configurationIdentifier();
    for (const entry of performance.getEntriesByType("resource")) resourceIdentifiers(entry.name);
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) resourceIdentifiers(entry.name);
    }).observe({type: "resource", buffered: true});
  } catch { /* Resource history is optional; unknown identifiers remain null. */ }
  Object.defineProperty(window, "__fcConfigurationObserverV2", {value: Object.freeze({
    peek: () => queue.slice(), ack: count => queue.splice(0, count)
  }), configurable: false});
})();

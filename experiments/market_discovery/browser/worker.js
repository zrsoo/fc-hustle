"use strict";
// Change only this constant to "alarm_30s" for the instrumented baseline arm.
// Existing browser/transaction-bridge and browser/read-bridge stay unchanged.
const TRANSPORT = "long_poll";
const ENDPOINT = "http://127.0.0.1:8770";
let running = false;
async function post(path, body, timeout) {
  const response = await fetch(ENDPOINT + path, {method: "POST", credentials: "omit", redirect: "error", cache: "no-store",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), signal: AbortSignal.timeout(timeout)});
  if (!response.ok) throw new Error("local_rejected");
  return response.json();
}
async function poll() {
  if (running) return;
  running = true;
  try {
    do {
      const {discoveryTab} = await chrome.storage.session.get("discoveryTab");
      if (!Number.isInteger(discoveryTab)) return;
      const installed = await chrome.scripting.executeScript({target: {tabId: discoveryTab}, world: "MAIN", func: () => !!window.__fcDiscoverySearchV1});
      if (installed[0]?.result !== true) throw new Error("attach_required");
      const command = await post("/next", {protocol: 1}, 25000);
      const received = performance.timeOrigin + performance.now();
      if (command) {
        // Validate independently before page injection. Page validates again.
        if (!validCommand(command)) throw new Error("invalid_command");
        const values = await chrome.scripting.executeScript({target: {tabId: discoveryTab}, world: "MAIN",
          func: (c, mark) => window.__fcDiscoverySearchV1.search(c, mark), args: [command, received]});
        const value = values[0]?.result;
        if (!value || !value.timing) throw new Error("invalid_reply");
        await post("/result", {id: command.id, result: value.result, timing: value.timing}, 3000);
      }
      await chrome.action.setBadgeText({text: "READ"});
    } while (TRANSPORT === "long_poll");
  } catch {
    await chrome.action.setBadgeText({text: "WAIT"});
    await chrome.action.setTitle({title: "Research search stopped. Check localhost server and reattach on the official EA Web App."});
    // No automatic retry after an ambiguous command or native error.
  } finally { running = false; }
}
function validCommand(c) {
  if (!c || Object.keys(c).sort().join() !== "evidence_key,id,operation,params" || c.operation !== "search" ||
      typeof c.id !== "string" || !/^[a-f0-9]{32}$/.test(c.id) || typeof c.evidence_key !== "string" || !/^[a-f0-9]{32}$/.test(c.evidence_key)) return false;
  const p = c.params;
  if (!p || Array.isArray(p) || typeof p !== "object" || p.count !== 21 || ![1,2].includes(p.page) || typeof p.fresh !== "boolean") return false;
  for (const [k,v] of Object.entries(p)) {
    if (!["page","count","fresh","definition_id","min_buy","max_buy","club","league"].includes(k)) return false;
    if (k !== "fresh" && (!Number.isSafeInteger(v) || v < (["page","count","definition_id"].includes(k) ? 1 : 0))) return false;
  }
  return (p.min_buy ?? 0) <= (p.max_buy ?? Number.MAX_SAFE_INTEGER);
}
chrome.action.onClicked.addListener(async tab => {
  try {
    const u = new URL(tab.url);
    if (u.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(u.hostname) || !/\/ultimate-team\/web-app(?:\/|$)/.test(u.pathname)) throw new Error("wrong_page");
    await chrome.scripting.executeScript({target: {tabId: tab.id}, world: "MAIN", files: ["page.js"]});
    await chrome.storage.session.set({discoveryTab: tab.id});
    await chrome.alarms.clear("fc-discovery-baseline");
    if (TRANSPORT === "alarm_30s") await chrome.alarms.create("fc-discovery-baseline", {periodInMinutes: 0.5});
    await poll();
  } catch { await chrome.action.setBadgeText({text: "WAIT"}); }
});
chrome.alarms.onAlarm.addListener(a => {if (TRANSPORT === "alarm_30s" && a.name === "fc-discovery-baseline") void poll();});

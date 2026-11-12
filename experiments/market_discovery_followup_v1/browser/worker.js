"use strict";
const ENDPOINT = "http://127.0.0.1:8771";
let running = false;
const now = () => performance.timeOrigin + performance.now();
async function post(path, body, timeout) {
  const response = await fetch(ENDPOINT + path, {method: "POST", credentials: "omit",
    redirect: "error", cache: "no-store", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body), signal: AbortSignal.timeout(timeout)});
  if (!response.ok) throw new Error("local_http_" + response.status);
  return response.json();
}
async function badge(text, title) {
  await chrome.action.setBadgeText({text});
  await chrome.action.setTitle({title});
}
function validCommand(c) {
  if (!c || Object.keys(c).sort().join() !== "evidence_key,id,operation,params" || c.operation !== "search" ||
      typeof c.id !== "string" || !/^[a-f0-9]{32}$/.test(c.id) || typeof c.evidence_key !== "string" || !/^[a-f0-9]{32}$/.test(c.evidence_key)) return false;
  const p = c.params;
  if (!p || Array.isArray(p) || typeof p !== "object" || p.count !== 21 || ![1,2].includes(p.page) || typeof p.fresh !== "boolean") return false;
  for (const [key, value] of Object.entries(p)) {
    if (!["page","count","fresh","definition_id","min_buy","max_buy","club","league"].includes(key)) return false;
    if (key !== "fresh" && (!Number.isSafeInteger(value) || value < (["page","count","definition_id"].includes(key) ? 1 : 0))) return false;
  }
  return (p.min_buy ?? 0) <= (p.max_buy ?? Number.MAX_SAFE_INTEGER);
}
async function poll() {
  if (running) return;
  running = true;
  let failure = "Cannot access the attached EA tab. Reattach this follow-up extension.";
  try {
    while (true) {
      const {followupTab} = await chrome.storage.session.get("followupTab");
      if (!Number.isInteger(followupTab)) return;
      const installed = await chrome.scripting.executeScript({target: {tabId: followupTab}, world: "MAIN",
        func: () => !!window.__fcDiscoverySearchFollowupV1});
      if (installed[0]?.result !== true) throw new Error("attach_required");
      failure = "Cannot poll the follow-up server on port 8771. Check its extension ID and server process.";
      const command = await post("/next", {protocol: 1}, 25000);
      const received = now();
      if (command) {
        if (!validCommand(command)) throw new Error("invalid_command");
        failure = "The bounded page search failed to return. No automatic retry was made.";
        const values = await chrome.scripting.executeScript({target: {tabId: followupTab}, world: "MAIN",
          func: (c, mark) => window.__fcDiscoverySearchFollowupV1.search(c, mark), args: [command, received]});
        const pageReturned = now(), value = values[0]?.result;
        if (!value?.timing) throw new Error("invalid_reply");
        const postBegan = performance.now();
        failure = "The local server rejected the result. No search retry was made.";
        await post("/result", {id: command.id, result: value.result, timing: value.timing}, 3000);
        await post("/telemetry", {id: command.id,
          worker_dispatch_to_page_return_ms: pageReturned - received,
          result_post_round_trip_ms: performance.now() - postBegan}, 3000);
      }
      await badge("READ", "Read-only discovery follow-up attached; local long polling; explicit searches only.");
    }
  } catch (error) {
    const code = /^local_http_[0-9]{3}$/.test(error?.message) ? " (" + error.message + ")" : "";
    await badge("WAIT", failure + code);
  } finally { running = false; }
}
chrome.action.onClicked.addListener(async tab => {
  let failure = "Select the official HTTPS EA Ultimate Team Web App before attaching.";
  try {
    const url = new URL(tab.url);
    if (url.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(url.hostname) ||
        !/\/ultimate-team\/web-app(?:\/|$)/.test(url.pathname)) throw new Error("wrong_page");
    failure = "Cannot inject the reviewed follow-up. Check this extension's EA site access.";
    await chrome.scripting.executeScript({target: {tabId: tab.id}, world: "MAIN", files: ["persona.js", "page.js"]});
    const inspected = await chrome.scripting.executeScript({target: {tabId: tab.id}, world: "MAIN",
      func: () => window.__fcDiscoveryPersonaFollowupV1.inspect()});
    failure = "Cannot deliver the safe persona projection to port 8771. Check the pinned extension ID.";
    await post("/persona", inspected[0]?.result, 3000);
    await chrome.storage.session.set({followupTab: tab.id});
    await badge("READ", "Read-only discovery follow-up attached; waiting for explicit search commands.");
    await poll();
  } catch (error) {
    const code = /^local_http_[0-9]{3}$/.test(error?.message) ? " (" + error.message + ")" : "";
    await badge("WAIT", failure + code);
  }
});

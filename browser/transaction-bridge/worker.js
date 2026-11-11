"use strict";
const ENDPOINT = "http://127.0.0.1:8768";
let running = false;
async function badge(text, title) {
  await chrome.action.setBadgeText({text});
  await chrome.action.setTitle({title});
}
async function poll() {
  if (running) return;
  running = true;
  let failure = "Cannot read the selected bridge tab. Click the bridge on the EA Web App tab.";
  try {
    const {transactionTab} = await chrome.storage.session.get("transactionTab");
    if (!Number.isInteger(transactionTab)) return;
    failure = "Cannot access the page bridge. Click the bridge on the EA Web App tab again.";
    const installed = await chrome.scripting.executeScript({target: {tabId: transactionTab}, world: "MAIN",
      func: () => !!window.__fcTransactionBridgeV3});
    if (installed[0]?.result !== true) throw new Error("attach_required");
    failure = "Cannot reach the local transaction server on port 8768. Start python -m fc_access.transaction_server.";
    // Edge can omit Origin on extension GET requests. POST supplies it without
    // weakening the server's extension-origin requirement.
    const response = await fetch(ENDPOINT + "/next", {method: "POST", credentials: "omit", redirect: "error", cache: "no-store",
      headers: {"Content-Type": "application/json"}, body: '{"bridge_version":3}', signal: AbortSignal.timeout(3000)});
    failure = `Local transaction server rejected polling (HTTP ${response.status}). Restart it after updating the bridge.`;
    if (!response.ok) throw new Error("sink_unavailable");
    failure = "The local transaction server returned an invalid command response.";
    const command = await response.json();
    if (command) {
      failure = "The page command could not finish. Keep the EA Web App tab open.";
      const results = await chrome.scripting.executeScript({target: {tabId: transactionTab}, world: "MAIN",
        func: async c => window.__fcTransactionBridgeV3.run(c), args: [command]});
      failure = "Cannot deliver the transaction result to the local server on port 8768.";
      const accepted = await fetch(ENDPOINT + "/result", {method: "POST", credentials: "omit", redirect: "error", cache: "no-store",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({id: command.id, result: results[0]?.result}), signal: AbortSignal.timeout(3000)});
      failure = `Local transaction server rejected the result (HTTP ${accepted.status}). No automatic retry was made.`;
      if (!accepted.ok) throw new Error("result_rejected");
    }
    await badge("TXN", "FC transaction bridge attached on port 8768; waiting for explicit one-shot transaction commands.");
  } catch { await badge("WAIT", failure); }
  finally { running = false; }
}
chrome.action.onClicked.addListener(async tab => {
  let failure = "Select the official HTTPS EA Ultimate Team Web App tab before clicking the bridge.";
  try {
    const url = new URL(tab.url);
    if (url.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(url.hostname) || !/\/ultimate-team\/web-app(?:\/|$)/.test(url.pathname)) throw new Error("wrong_page");
    failure = "Cannot install the page bridge. Check the extension's site access for the EA Web App.";
    await chrome.scripting.executeScript({target: {tabId: tab.id}, world: "MAIN", files: ["read-page.js", "page.js"]});
    failure = "Cannot save the bridge tab or start its polling alarm. Reload the transaction bridge extension.";
    await chrome.storage.session.set({transactionTab: tab.id});
    await chrome.alarms.create("fc-transaction-poll", {periodInMinutes: 0.5});
    await poll();
  } catch { await badge("WAIT", failure); }
});
chrome.alarms.onAlarm.addListener(a => {if (a.name === "fc-transaction-poll") void poll();});

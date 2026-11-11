"use strict";
const ENDPOINT = "http://127.0.0.1:8766";
const ALARM = "fc-observer-poll";
let running = false;

async function post(path, value) {
  const response = await fetch(ENDPOINT + path, {
    method: "POST", credentials: "omit", redirect: "error", cache: "no-store",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(value),
    signal: AbortSignal.timeout(3000)
  });
  if (!response.ok) throw new Error("sink_unavailable");
}

async function poll() {
  if (running) return;
  running = true;
  try {
    const {observedTab} = await chrome.storage.session.get("observedTab");
    if (!Number.isInteger(observedTab)) return;
    const results = await chrome.scripting.executeScript({target: {tabId: observedTab}, world: "MAIN",
      func: () => {
        const state = window.__fcConfigurationObserverV2;
        return state ? {installed: true, observations: state.peek()} : {installed: false, observations: []};
      }});
    const result = results[0]?.result;
    if (!result?.installed) throw new Error("attach_required");
    await post("/attached", {observer_installed: true, observer_version: 2});
    for (const observation of result.observations) await post("/observation", observation);
    // Acknowledge only after all observations were accepted, so sink downtime loses no batch.
    if (result.observations.length) await chrome.scripting.executeScript({
      target: {tabId: observedTab}, world: "MAIN", func: count => window.__fcConfigurationObserverV2?.ack(count),
      args: [result.observations.length]
    });
    await chrome.action.setBadgeText({text: "ON"});
  } catch {
    await chrome.action.setBadgeText({text: "WAIT"});
  } finally { running = false; }
}

chrome.action.onClicked.addListener(async tab => {
  try {
    const url = new URL(tab.url);
    if (url.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(url.hostname) ||
        !/\/ultimate-team\/web-app(?:\/|$)/.test(url.pathname)) throw new Error("wrong_page");
    await chrome.scripting.executeScript({target: {tabId: tab.id}, world: "MAIN", files: ["page.js"]});
    // Session storage holds only a browser tab number, never authentication state; no disk storage.
    await chrome.storage.session.set({observedTab: tab.id});
    await chrome.alarms.create(ALARM, {periodInMinutes: 0.5});
    await poll();
  } catch { await chrome.action.setBadgeText({text: "WAIT"}); }
});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void poll(); });

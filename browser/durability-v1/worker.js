"use strict";
// Only the local command transport polls. There is no market/bidding actor.
const BASE = 'http://127.0.0.1:8779';
const WORKER = [...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');
let running = false;
async function post(path, value, timeout=24000) {
  const r = await fetch(BASE+path, {method:'POST',credentials:'omit',redirect:'error',cache:'no-store',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(value),signal:AbortSignal.timeout(timeout)});
  if (!r.ok) throw Error('local_rejected');
  return r.json();
}
const official = text => {
  const u = new URL(text);
  return u.protocol === 'https:' && /^(www\.)?ea\.com$/.test(u.hostname) &&
    /\/ultimate-team\/web-app(?:\/|$)/.test(u.pathname);
};
async function badge(text) {await chrome.action.setBadgeText({text});}
async function poll() {
  if (running) return;
  running = true;
  try {
    while (true) {
      const {durableTab} = await chrome.storage.session.get('durableTab');
      if (!Number.isInteger(durableTab)) return;
      const tab = await chrome.tabs.get(durableTab);
      if (!official(tab.url)) throw Error('wrong_tab');
      const h = await post('/hello',{protocol:1});
      if (!h.owner || h.window.expired || h.window.stopped) {await badge('IDLE'); return;}
      // Reinject after same-origin page navigation, never request native data here.
      await chrome.scripting.executeScript({target:{tabId:durableTab},world:'MAIN',files:['persona.js','page.js']});
      const values = await chrome.scripting.executeScript({target:{tabId:durableTab},world:'MAIN',
        func:async owner => {
          const p = window.__fcDurablePageV1;
          if (!p.attach(owner.scope,owner.owner,owner.epoch)) return null;
          const c={schema:1,id:'0'.repeat(32),operation:'balance',params:{},evidence_key:'1'.repeat(32),...owner};
          const reject=async c => {const r=await p.execute(c);return r.result.error==='invalid_command' && r.freshness.request_count===0;};
          const different = x => (x[0]==='a'?'b':'a')+x.slice(1);
          const fences={wrong_scope:await reject({...c,scope:different(owner.scope)}),
            wrong_owner:await reject({...c,owner:different(owner.owner)}),
            stale_epoch:await reject({...c,epoch:owner.epoch-1}),
            bid_disabled:await reject({...c,operation:'bid'})};
          return {document:p.document,persona:window.__fcDiscoveryPersonaFollowupV1.inspect(),fences};
        },args:[h.owner]});
      const safe=values[0]?.result;
      if (!safe || !Object.values(safe.fences).every(x=>x===true)) throw Error('page_fence_failed');
      const peer={boot:h.boot,...h.owner,...safe,worker:WORKER};
      await post('/hello',{protocol:1,peer});
      const c=await post('/next',peer);
      if (c) {
        if(c.scope!==peer.scope || c.owner!==peer.owner || c.epoch!==peer.epoch) throw Error('stale_command');
        const r=await chrome.scripting.executeScript({target:{tabId:durableTab},world:'MAIN',
          func:c=>window.__fcDurablePageV1.execute(c),args:[c]});
        // No retry of execution or result delivery. Lost ACK is UNKNOWN at host.
        await post('/result',{peer,id:c.id,result:r[0]?.result});
      }
      await badge(safe.persona.accepted?'READ':'USER');
    }
  } catch {await badge('WAIT');}
  finally {running=false;}
}
async function watchdog() {await chrome.alarms.create('durability-local',{periodInMinutes:0.5});void poll();}
chrome.action.onClicked.addListener(async tab=>{
  try {
    if(!official(tab.url)) throw Error('wrong_tab');
    await chrome.storage.session.set({durableTab:tab.id});
    await watchdog();
  } catch {await badge('WAIT');}
});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='durability-local')void poll();});
chrome.runtime.onStartup.addListener(()=>void watchdog());
chrome.runtime.onInstalled.addListener(()=>void watchdog());

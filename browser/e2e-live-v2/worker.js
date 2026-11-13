"use strict";
const BASE='http://127.0.0.1:8782',worker=crypto.randomUUID();
let running=false;
const official=s=>{const u=new URL(s);return u.protocol==='https:'&&/^(www\.)?ea\.com$/.test(u.hostname)&&/\/ultimate-team\/web-app(?:\/|$)/.test(u.pathname);};
async function post(path,v){const r=await fetch(BASE+path,{method:'POST',credentials:'omit',redirect:'error',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(v),signal:AbortSignal.timeout(25000)});if(!r.ok)throw Error('local_rejected');return r.json();}
async function poll(){if(running)return;running=true;try{while(true){
 const {liveV2Tab}=await chrome.storage.session.get('liveV2Tab');if(!Number.isInteger(liveV2Tab))return;
 const tab=await chrome.tabs.get(liveV2Tab);if(!official(tab.url))throw Error('wrong_tab');
 const h=await post('/hello',{protocol:1});if(h.stopped||h.expired){await chrome.action.setBadgeText({text:'STOP'});return;}
 await chrome.scripting.executeScript({target:{tabId:liveV2Tab},world:'MAIN',files:['persona.js','page.js']});
 const a=await chrome.scripting.executeScript({target:{tabId:liveV2Tab},world:'MAIN',func:h=>window.__fcE2ELiveV2.attach(h),args:[h]});
 const safe=a[0]?.result;if(!safe)throw Error('page_fence');
 const peer={boot:h.boot,owner:h.owner,worker,...safe};await post('/hello',{protocol:1,peer});
 const c=await post('/next',peer);if(c){const r=await chrome.scripting.executeScript({target:{tabId:liveV2Tab},world:'MAIN',func:c=>window.__fcE2ELiveV2.execute(c),args:[c]});await post('/result',{peer,id:c.id,result:r[0]?.result});}
 await chrome.action.setBadgeText({text:safe.persona.accepted?'E2E':'USER'});
 }}catch{await chrome.action.setBadgeText({text:'WAIT'});}finally{running=false;}}
async function watchdog(){await chrome.alarms.create('live-v2-local',{periodInMinutes:0.5});void poll();}
chrome.action.onClicked.addListener(async tab=>{if(official(tab.url)){await chrome.storage.session.set({liveV2Tab:tab.id});await watchdog();}});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='live-v2-local')void poll();});
chrome.runtime.onStartup.addListener(()=>void watchdog());chrome.runtime.onInstalled.addListener(()=>void watchdog());

"use strict";
const BASE='http://127.0.0.1:8781',worker=crypto.randomUUID();
let running=false;
const official=s=>{const u=new URL(s);return u.protocol==='https:'&&/^(www\.)?ea\.com$/.test(u.hostname)&&/\/ultimate-team\/web-app(?:\/|$)/.test(u.pathname);};
async function post(path,v){const r=await fetch(BASE+path,{method:'POST',credentials:'omit',redirect:'error',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(v),signal:AbortSignal.timeout(25000)});if(!r.ok)throw Error('local_rejected');return r.json();}
async function poll(){if(running)return;running=true;try{while(true){
 const {reconTab}=await chrome.storage.session.get('reconTab');if(!Number.isInteger(reconTab))return;
 const tab=await chrome.tabs.get(reconTab);if(!official(tab.url))throw Error('wrong_tab');
 const h=await post('/hello',{protocol:1});if(h.stopped||h.expired){await chrome.action.setBadgeText({text:'STOP'});return;}
 await chrome.scripting.executeScript({target:{tabId:reconTab},world:'MAIN',files:['persona.js','page.js']});
 const a=await chrome.scripting.executeScript({target:{tabId:reconTab},world:'MAIN',func:h=>window.__fcReconV1.attach(h),args:[h]});
 const safe=a[0]?.result;if(!safe)throw Error('page_fence');
 const peer={boot:h.boot,owner:h.owner,worker,...safe};await post('/hello',{protocol:1,peer});
 const c=await post('/next',peer);if(c){const r=await chrome.scripting.executeScript({target:{tabId:reconTab},world:'MAIN',func:c=>window.__fcReconV1.execute(c),args:[c]});await post('/result',{peer,id:c.id,result:r[0]?.result});}
 await chrome.action.setBadgeText({text:safe.persona.accepted?'E2E':'USER'});
 }}catch{await chrome.action.setBadgeText({text:'WAIT'});}finally{running=false;}}
async function watchdog(){await chrome.alarms.create('recon-local',{periodInMinutes:0.5});void poll();}
chrome.action.onClicked.addListener(async tab=>{if(official(tab.url)){await chrome.storage.session.set({reconTab:tab.id});await watchdog();}});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='recon-local')void poll();});
chrome.runtime.onStartup.addListener(()=>void watchdog());chrome.runtime.onInstalled.addListener(()=>void watchdog());

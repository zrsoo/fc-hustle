'use strict';
const BASE='http://127.0.0.1:8778';let running=false;
async function post(path,value){const r=await fetch(BASE+path,{method:'POST',credentials:'omit',redirect:'error',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(value),signal:AbortSignal.timeout(25000)});if(!r.ok)throw Error('local_rejected');return r.json();}
async function poll(){if(running)return;running=true;try{
  const {searchTab}=await chrome.storage.session.get('searchTab');if(!Number.isInteger(searchTab))return;
  const c=await post('/next',{});if(c){const r=await chrome.scripting.executeScript({target:{tabId:searchTab},world:'MAIN',func:c=>window.__fcSearchValidationV3.read(c),args:[c]});await post('/result',{id:c.id,result:r[0].result});}
  await chrome.action.setBadgeText({text:'READ'});
}catch{await chrome.action.setBadgeText({text:'WAIT'});}finally{running=false;}}
chrome.action.onClicked.addListener(async tab=>{try{
  const u=new URL(tab.url);if(u.protocol!=='https:'||!/^(www\.)?ea\.com$/.test(u.hostname)||!/\/ultimate-team\/web-app(?:\/|$)/.test(u.pathname))throw Error('wrong_page');
  await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',files:['persona.js','page.js']});await chrome.storage.session.set({searchTab:tab.id});await chrome.alarms.create('search-read',{periodInMinutes:0.5});await poll();
}catch{await chrome.action.setBadgeText({text:'WAIT'});}});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='search-read')void poll();});

'use strict';
// Local delivery only. A click selects the official tab; alarms never search EA.
const BASE='http://127.0.0.1:8784';
const WORKER=[...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');
let running=false;
const official=text=>{const u=new URL(text);return u.protocol==='https:' && /^(www\.)?ea\.com$/.test(u.hostname) && /\/ultimate-team\/web-app(?:\/|$)/.test(u.pathname);};
async function post(path,value){
  const r=await fetch(BASE+path,{method:'POST',credentials:'omit',redirect:'error',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(value),signal:AbortSignal.timeout(24000)});
  if(!r.ok)throw Error('local_rejected');return r.json();
}
async function poll(){
  if(running)return;running=true;
  try{
    while(true){
      const {productionTab,productionDocument}=await chrome.storage.session.get(['productionTab','productionDocument']);
      if(!Number.isInteger(productionTab))return;
      const tab=await chrome.tabs.get(productionTab);if(!official(tab.url))throw Error('wrong_tab');
      const h=await post('/hello',{schema:2});if(!h.owner){await chrome.action.setBadgeText({text:'IDLE'});return;}
      await chrome.scripting.executeScript({target:{tabId:productionTab},world:'MAIN',files:['persona.js','page.js']});
      const values=await chrome.scripting.executeScript({target:{tabId:productionTab},world:'MAIN',func:(h,worker,expectedDocument)=>{
        const p=window.__fcProductionV1;
        // Reload/account-context changes require operator selection and a higher
        // host owner epoch. Do not silently bind account labels to a new page.
        if(expectedDocument && expectedDocument!==p.document)return null;
        const fences={owner:h.owner.owner,epoch:h.owner.epoch,host_epoch:h.host_epoch,worker_epoch:worker,document:p.document};
        return p.attach(h.owner.context,fences)?{context:h.owner.context,fences}:null;
      },args:[h,WORKER,productionDocument]});
      const peer=values[0]?.result;if(!peer)throw Error('persona_or_document_unverified');
      await chrome.storage.session.set({productionDocument:peer.fences.document});
      await post('/hello',{schema:2,peer});
      const c=await post('/next',peer);
      if(c){
        if(Object.keys(peer.context).some(k=>c.context[k]!==peer.context[k]) || Object.keys(peer.fences).some(k=>c.fences[k]!==peer.fences[k]))throw Error('stale_command');
        const results=await chrome.scripting.executeScript({target:{tabId:productionTab},world:'MAIN',func:c=>window.__fcProductionV1.execute(c),args:[c]});
        // No retry of execution or result delivery, even after an ACK is lost.
        await post('/result',{peer,id:c.id,result:results[0]?.result});
      }
      await chrome.action.setBadgeText({text:'READ'});
    }
  }catch{await chrome.action.setBadgeText({text:'WAIT'});}finally{running=false;}
}
chrome.action.onClicked.addListener(async tab=>{
  try{if(!official(tab.url))throw Error('wrong_tab');await chrome.storage.session.set({productionTab:tab.id,productionDocument:null});
    await chrome.alarms.create('production-local',{periodInMinutes:0.5});void poll();
  }catch{await chrome.action.setBadgeText({text:'WAIT'});}
});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='production-local')void poll();});

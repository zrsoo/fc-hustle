'use strict';
// Local delivery only. A click selects the official tab; alarms never search EA.
// After an operator has bound a persona once, a reloaded official document may
// rebind automatically, but only to a strictly newer controller owner epoch and
// only when the page proves the same persona fingerprint. Anything else waits
// for an explicit operator click, exactly as before.
const BASE='http://127.0.0.1:8784';
const PATTERNS=['https://www.ea.com/ea-sports-fc/ultimate-team/web-app/*','https://www.ea.com/*/ea-sports-fc/ultimate-team/web-app/*',
  'https://ea.com/ea-sports-fc/ultimate-team/web-app/*','https://ea.com/*/ea-sports-fc/ultimate-team/web-app/*'];
const WORKER=[...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');
let running=false,recent=null;
const official=text=>{const u=new URL(text);return u.protocol==='https:' && /^(www\.)?ea\.com$/.test(u.hostname) && /\/ultimate-team\/web-app(?:\/|$)/.test(u.pathname);};
async function post(path,value,timeout=24000){
  const r=await fetch(BASE+path,{method:'POST',credentials:'omit',redirect:'error',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(value),signal:AbortSignal.timeout(timeout)});
  if(!r.ok)throw Error('local_rejected');return r.json();
}
async function fingerprints(){return (await chrome.storage.local.get(['personaFingerprints'])).personaFingerprints||{};}
async function productionTab(){
  const {productionTab}=await chrome.storage.session.get(['productionTab']);
  if(Number.isInteger(productionTab)){
    let tab=null;try{tab=await chrome.tabs.get(productionTab);}catch{}
    if(tab){if(!official(tab.url))throw Error('wrong_tab');return productionTab;}
  }
  // No live operator-selected tab (closed, browser or extension restart). Only an
  // account an operator bound before may continue, in its single official tab.
  if(!Object.keys(await fingerprints()).length)return null;
  const tabs=(await chrome.tabs.query({url:PATTERNS})).filter(t=>official(t.url));
  if(tabs.length!==1)throw Error('wrong_tab');
  await chrome.storage.session.set({productionTab:tabs[0].id,productionDocument:null,productionEpoch:null,productionMode:'continuity'});
  return tabs[0].id;
}
async function poll(){
  if(running)return;running=true;
  let active=null,stage='execute',pollPhase='tab';
  const emit=async(records,scope=active)=>{if(scope)try{await post('/diagnostic',{peer:scope.peer,id:scope.id,records},2000);}catch{}};
  const event=(stage,detail={})=>({stage,at:new Date().toISOString(),detail});
  try{
    while(true){
      pollPhase='tab';
      const tabId=await productionTab();if(tabId===null)return;
      const {productionDocument,productionEpoch,productionMode}=await chrome.storage.session.get(['productionDocument','productionEpoch','productionMode']);
      pollPhase='hello';const h=await post('/hello',{schema:2});if(!h.owner){await chrome.action.setBadgeText({text:'IDLE'});return;}
      pollPhase='inject';
      await chrome.scripting.executeScript({target:{tabId},world:'MAIN',files:['persona.js','diagnostics.js','controller.js','page.js']});
      const expectedFingerprint=(await fingerprints())[h.owner.context?.account]??null;
      pollPhase='persona';const values=await chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:async(h,worker,expectedDocument,boundEpoch,expectedFingerprint,mode)=>{
        const p=window.__fcProductionV1;
        // A reload/new document never silently inherits the previous binding.
        // Once rebound by continuity, the document stays under that stricter rule.
        let continuity=mode==='continuity';
        if(expectedDocument && expectedDocument!==p.document){
          if(!Number.isSafeInteger(boundEpoch) || !(h.owner.epoch>boundEpoch))return null;
          continuity=true;
        }
        const fingerprint=await p.personaFingerprint?.(h.owner.context);
        if(!fingerprint || continuity && fingerprint!==expectedFingerprint)return null;
        const fences={owner:h.owner.owner,epoch:h.owner.epoch,host_epoch:h.host_epoch,worker_epoch:worker,document:p.document};
        return p.attach(h.owner.context,fences)?{context:h.owner.context,fences,fingerprint,continuity}:null;
      },args:[h,WORKER,productionDocument??null,productionEpoch??null,expectedFingerprint,productionMode??'operator']});
      const bound=values[0]?.result;if(!bound)throw Error('persona_or_document_unverified');
      const peer={context:bound.context,fences:bound.fences};
      await chrome.storage.session.set({productionDocument:peer.fences.document,productionEpoch:peer.fences.epoch,productionMode:bound.continuity?'continuity':'operator'});
      // Only an explicit operator selection records which persona is authorized.
      if(!bound.continuity)await chrome.storage.local.set({personaFingerprints:{...(await fingerprints()),[peer.context.account]:bound.fingerprint}});
      pollPhase='bind';await post('/hello',{schema:2,peer});
      pollPhase='claim';const c=await post('/next',peer);
      if(c){
        if(Object.keys(peer.context).some(k=>c.context[k]!==peer.context[k]) || Object.keys(peer.fences).some(k=>c.fences[k]!==peer.fences[k]))throw Error('stale_command');
        active={peer,id:c.id};stage='execute';await emit([event('WORKER_EXECUTE')]);
        if(c.operation?.startsWith('bulk_'))await chrome.scripting.executeScript({target:{tabId},world:'MAIN',files:['bulk-transfer.js']});
        const results=await chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:(c,service)=>c.schema===4?window.__fcProductionV1.executeController(c):service==='fc-controller-v1'?window.__fcProductionV1.executeReadController(c):c.operation?.startsWith('bulk_')?window.__fcBulkTransferV1.execute(c):window.__fcProductionV1.execute(c),args:[c,h.service]});
        stage='result';await emit([event('WORKER_RESULT')]);
        try{const trace=await chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:id=>window.__fcProductionDiagnosticsV1?.get(id)??[],args:[c.id]});await emit(trace[0]?.result??[]);}catch{}
        // No retry of execution or result delivery, even after an ACK is lost.
        stage='post_result';await emit([event('WORKER_POST_RESULT')]);
        await post('/result',{peer,id:c.id,result:results[0]?.result});
        await emit([event('WORKER_ACK')]);recent=active;active=null;
      }
      await chrome.action.setBadgeText({text:'READ'});
    }
  }catch(error){
    const reason=['local_rejected','persona_or_document_unverified','wrong_tab','stale_command'].includes(error?.message)?error.message:'worker_exception';
    if(active)await emit([event('WORKER_FAILURE',{worker_stage:stage,reason})]);
    else await emit([event('WORKER_POLL_FAILURE',{poll_phase:pollPhase,reason})],recent);
    await chrome.action.setBadgeText({text:'WAIT'});
  }finally{running=false;}
}
const schedule=()=>chrome.alarms.create('production-local',{periodInMinutes:0.5});
chrome.action.onClicked.addListener(async tab=>{
  try{if(!official(tab.url))throw Error('wrong_tab');await chrome.storage.session.set({productionTab:tab.id,productionDocument:null,productionEpoch:null,productionMode:'operator'});
    await schedule();void poll();
  }catch{await chrome.action.setBadgeText({text:'WAIT'});}
});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='production-local')void poll();});
// Alarms may not survive a browser restart or extension reload; polling is
// local-only and does nothing until a controller owner exists.
chrome.runtime?.onStartup?.addListener(()=>void schedule());
chrome.runtime?.onInstalled?.addListener(()=>void schedule());

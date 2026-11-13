'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const hex=n=>n.toString(16).padStart(32,'0');
const context={account:hex(1),persona:hex(2),game:'fc27',platform:'pc',identity_namespace:hex(3)};
let owner={context,owner:hex(4),epoch:1},host=hex(5),document=hex(7),next=null,mode='ok';
let stored={},executions=0,posts=[],badge='',files=[],personaOK=true,official=true;
const listeners={},page={document,attach(c,f){return personaOK;},execute(c){executions++;return {command_id:c.id,safe:true};}};
const chrome={
  storage:{session:{async get(){return stored;},async set(v){Object.assign(stored,v);}}},
  tabs:{async get(id){assert.equal(id,7);return {url:official?'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/':'https://evil.example/'};}},
  action:{async setBadgeText(v){badge=v.text;},onClicked:{addListener(f){listeners.click=f;}}},
  alarms:{async create(){},onAlarm:{addListener(f){listeners.alarm=f;}}},
  scripting:{async executeScript(c){
    if(c.files){files.push(...c.files);return [];}
    // Execute the actual injected callback against the page-double, rather
    // than returning a fabricated worker handshake without checking its code.
    sandbox.window={__fcProductionV1:page};
    sandbox.injectArgs=c.args;
    const value=await vm.runInContext('('+c.func.toString()+')(...injectArgs)',sandbox);
    return [{result:JSON.parse(JSON.stringify(value))}];
  }}
};
const fetch=async(url,options)=>{
  assert.equal(new URL(url).origin,'http://127.0.0.1:8784');assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');assert.equal(options.cache,'no-store');
  const path=new URL(url).pathname,v=JSON.parse(options.body);posts.push({path,v});
  if(mode==='offline')throw Error('SECRET_NATIVE_ERROR');
  if(path==='/hello')return {ok:true,json:async()=>({schema:2,host_epoch:host,owner})};
  if(path==='/next'){
    assert.equal(v.fences.host_epoch,host);assert.equal(v.fences.epoch,owner.epoch);assert.equal(v.fences.document,page.document);
    if(next){const c={...next,context:{...context},fences:{...v.fences,...next.fences}};next=null;return {ok:true,json:async()=>c};}
    throw Error('idle_close');
  }
  if(path==='/result'){
    if(mode==='dropResult')throw Error('lost_ACK');
    return {ok:true,json:async()=>({accepted:true})};
  }
  throw Error('wrong_local_route');
};
const sandbox=vm.createContext({chrome,fetch,URL,AbortSignal,crypto:require('node:crypto').webcrypto});
vm.runInContext(fs.readFileSync('browser/production-v1/worker.js','utf8'),sandbox);
const settle=()=>new Promise(resolve=>setTimeout(resolve,20));
const alarm=async()=>{listeners.alarm({name:'production-local'});await settle();};
const cmd=n=>({schema:2,id:hex(n),operation:'balance',params:{},fences:{}});
(async()=>{
  await alarm();assert.equal(posts.length,0,'no selected tab: no work');
  mode='offline';await listeners.click({id:7,url:'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/'});await settle();assert.equal(badge,'WAIT');assert.equal(executions,0);
  mode='ok';await alarm();assert.equal(executions,0,'idle only attaches');assert.deepEqual(files.slice(0,2),['persona.js','page.js']);
  next=cmd(20);await alarm();assert.equal(executions,1);assert.equal(posts.filter(p=>p.path==='/result').length,1);
  await alarm();assert.equal(executions,1,'idle poll cannot replay a command');
  next={...cmd(21),fences:{host_epoch:hex(999)}};await alarm();assert.equal(executions,1);
  next={...cmd(22),fences:{worker_epoch:hex(999)}};await alarm();assert.equal(executions,1);
  next={...cmd(23),fences:{document:hex(999)}};await alarm();assert.equal(executions,1);
  mode='dropResult';next=cmd(24);await alarm();assert.equal(executions,2);const results=posts.filter(p=>p.path==='/result').length;
  mode='ok';await alarm();assert.equal(executions,2);assert.equal(posts.filter(p=>p.path==='/result').length,results,'result delivery is not retried');
  page.document=hex(8);next=cmd(25);await alarm();assert.equal(executions,2,'reload cannot silently rebind account context');assert.equal(badge,'WAIT');next=null;
  host=hex(55);owner={...owner,epoch:2};
  await listeners.click({id:7,url:'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/'});await settle();
  next=cmd(26);await alarm();assert.equal(executions,3,'explicit new document/host/epoch selection works');
  personaOK=false;next=cmd(27);await alarm();assert.equal(executions,3);next=null;personaOK=true;
  official=false;await alarm();assert.equal(executions,3);assert.equal(badge,'WAIT');
  assert(!JSON.stringify(posts).includes('SECRET_NATIVE_ERROR'));
  console.log('PASS production worker: explicit tab, local-only idle, fences, dropped ACK, no replay, reload requires rebind, persona and no secret retention');
})().catch(e=>{console.error(e);process.exitCode=1;});

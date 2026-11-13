'use strict';
// Deterministic service-worker restart/alarm/network faults. No native services.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let fail=true,posts=[],injections=0,executions=0,stored={durableTab:7},badge='',reloads=0;
const listeners={},scope='a'.repeat(32),owner='b'.repeat(32);
let epoch=1,boot='c'.repeat(32),document='d'.repeat(32),next=null;
const chrome={
  storage:{session:{async get(){return stored;},async set(v){stored=v;}}},
  action:{async setBadgeText(v){badge=v.text;},onClicked:{addListener(f){listeners.click=f;}}},
  alarms:{async create(){},onAlarm:{addListener(f){listeners.alarm=f;}}},
  runtime:{onStartup:{addListener(f){listeners.start=f;}},onInstalled:{addListener(f){listeners.install=f;}}},
  tabs:{async get(id){assert.equal(id,7);return {url:'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/'};}},
  scripting:{async executeScript(c){
    if(c.files){injections++;return [];}
    if(c.args[0]?.schema){executions++;return [{result:{safe:true}}];}
    return [{result:{document,persona:{accepted:true},fences:{wrong_scope:true,wrong_owner:true,stale_epoch:true,bid_disabled:true}}}];
  }}
};
let runningResolve;
const fetch=async(url,options)=>{
  assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');
  const path=new URL(url).pathname,v=JSON.parse(options.body);posts.push(path);
  if(fail)throw Error('server absent');
  if(path==='/hello')return {ok:true,async json(){return {boot,owner:{scope,owner,epoch},window:{expired:false}};}};
  if(path==='/next'){
    assert.equal(v.epoch,epoch);assert.equal(v.boot,boot);assert.equal(v.document,document);
    if(next){const c=next;next=null;return {ok:true,async json(){return c;}};}
    // Terminate this test's local delivery loop at an empty poll, just as a
    // bounded HTTP error does. Alarm must restart it; no command is replayed.
    throw Error('idle connection closed');
  }
  if(path==='/result')return {ok:true,async json(){return {accepted:true};}};
  throw Error('unexpected route');
};
const context=vm.createContext({chrome,fetch,URL,AbortSignal,JSON,Number,Object,Error,crypto:require('node:crypto').webcrypto,Uint8Array});
vm.runInContext(fs.readFileSync('browser/durability-v1/worker.js','utf8'),context);
const settle=()=>new Promise(r=>setTimeout(r,25));
(async()=>{
  listeners.alarm({name:'durability-local'});await settle();assert.equal(badge,'WAIT');
  fail=false;
  listeners.alarm({name:'durability-local'});await settle();assert(injections>0);
  assert.equal(executions,0,'idle recovery cannot call native services');
  next={schema:1,id:'e'.repeat(32),scope,owner,epoch,operation:'watched',params:{}};
  listeners.alarm({name:'durability-local'});await settle();assert.equal(executions,1);
  listeners.alarm({name:'durability-local'});await settle();assert.equal(executions,1);
  boot='f'.repeat(32);epoch=2;document='1'.repeat(32);
  next={schema:1,id:'2'.repeat(32),scope,owner,epoch,operation:'balance',params:{}};
  listeners.start();await settle();assert.equal(executions,2);
  next={schema:1,id:'3'.repeat(32),scope,owner,epoch:1,operation:'bid',params:{}};
  listeners.alarm({name:'durability-local'});await settle();assert.equal(executions,2);
  assert.equal(posts.filter(p=>p==='/result').length,2);
  console.log('PASS: idle watchdog, failed fetch, process restart, page reinjection, ownership and no replay');
})().catch(e=>{console.error(e);process.exitCode=1;});

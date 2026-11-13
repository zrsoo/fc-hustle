'use strict';
// Persistent mocked native page: Python exercises the shipped JS via protocol 2.
const {setup,ctx,hex}=require('./production_page_checks.cjs');
const readline=require('node:readline');
const h=setup();
let calls=0;
const rl=readline.createInterface({input:process.stdin});
let chain=Promise.resolve();
rl.on('line',line=>{chain=chain.then(async()=>{
  const q=JSON.parse(line);let out;
  if(q.action==='attach')out=h.fences;
  else if(q.action==='stats')out={calls:h.calls,helper_calls:calls};
  else if(q.action==='configure'){
    const c=h.sandbox.UTCurrencyInputControl;
    if(q.missing==='helpers')delete h.sandbox.UTCurrencyInputControl;
    if(q.missing==='below')delete c.getIncrementBelowVal;
    if(q.missing==='caps')delete h.sandbox.services.Item.transfersDao;
    if(q.disagree)c.getIncrementAboveVal=()=>50;
    if(q.cap){
      const old=h.sandbox.services.Item.transfersDao.getItemMarketDataByDefId;
      h.sandbox.services.Item.transfersDao.getItemMarketDataByDefId=function(ids){
        const observable=old.call(this,ids),observe=observable.observe;
        observable.observe=function(owner,cb){return observe.call(this,owner,(s,r)=>{r.response.marketData=[{defId:q.cap.definition_id,priceLimits:{minimum:q.cap.minimum,maximum:q.cap.maximum}}];cb(s,r);});};return observable;
      };
    }
    if(c && !c.counted){
      for(const name of ['getIncrementAboveVal','getIncrementBelowVal'])if(c[name]){const f=c[name];c[name]=function(v){calls++;return f.call(this,v);};}
      c.counted=true;
    }
    out=true;
  }else out=await h.execute(q);
  process.stdout.write(JSON.stringify(out)+'\n');
});});

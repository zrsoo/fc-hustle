'use strict';
const assert=require('node:assert/strict');
const {setup}=require('./production_page_checks.cjs');
(async()=>{
  for(const entry of ['legacy','controller'])for(const mode of ['ok','missing','version','oversize','persona']){
    const h=setup(),raw=h.raw();h.sandbox.ItemPile.CLUB=4;raw.pile=4;
    const before=await h.execute(h.command('watched'));
    const row=before.result.auctions[0],target={trade_id:row.trade_id,item_id:row.item.item_id,definition_id:row.item.definition_id};
    h.fences.epoch++;assert(h.api.attach(before.context,h.fences));
    const pool=mode==='missing'?[]:mode==='version'?[{...raw,definitionId:999}]:mode==='oversize'?Array(2049).fill(raw):[raw];
    h.sandbox.repositories.Item.getClub=()=>({items:{values:()=>pool}});
    let gets=0;
    h.sandbox.services.Item.requestItemsById=ids=>{
      gets++;assert.deepEqual(Array.from(ids),[raw.id]);
      return h.response('owned_item',{items:[raw]},{idList:raw.id});
    };
    const queue=entry==='controller'?h.enableControllerQueue():null;
    const execute=c=>entry==='controller'?h.api.executeReadController(c):h.execute(c);
    if(mode==='persona')h.switchPersona({platform:'PC',isPC:true});
    const c=h.command('owned_item',target),v=await execute(c);
    assert.equal(v.result.success,mode==='ok',JSON.stringify(v));
    assert.equal(gets,mode==='ok'?1:0,mode);
    if(queue)assert(queue.requests.every(r=>r.count===1 && r.send===r.originalSend));
    if(mode==='ok'){
      assert.equal(v.freshness.request_count,1);assert.equal(v.result.items[0].item_id,target.item_id);
      const ds=h.sandbox.window.__fcProductionDiagnosticsV1.get(c.id);
      assert(ds.some(r=>r.detail.item_pile==='club'));
      assert(!JSON.stringify(ds).includes('CANARY'));assert(!JSON.stringify(ds).includes(raw.id));
      // A selector and fresh GET grant no terminal win or move authority.
      const moved=await h.execute(h.command('move',{...target,paid:7700,win_read_id:before.command_id,
        owned_read_id:c.id,caps_read_id:c.id,starting_bid:11750,buy_now_price:12000,duration:3600}));
      assert.equal(moved.result.success,false);assert.equal(gets,1);
    }
  }
  console.log('PASS read-only selector recovery: exact pseudonym/version, fresh owned GET, bounded native cache, persona/fences, no write authority or secret export');
})().catch(e=>{console.error(e);process.exitCode=1;});

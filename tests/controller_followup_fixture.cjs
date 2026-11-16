'use strict';
// Real captured service follow-ups; only transport, repositories and DTOs are synthetic.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const methods=JSON.parse(fs.readFileSync('docs/research/004/request-ownership-fix/native-followup-contract.json','utf8')).methods;
function base(h){
  const q=h.enableControllerQueue(),b=h.sandbox;
  b.EAObservable=function(){return q.observable();};b.UTServiceResponseDTO=class{};
  b._0x16df02=b.a0_0x351b=()=>{throw Error('unresolved_static_projection');};
  b.DebugUtils={Assert:v=>assert(v)};
  b.JSUtils={isObject:v=>v!==null&&typeof v==='object',isValid:v=>v!=null,find:(rows,fn)=>rows.find(fn)};
  b.AppNotification={ITEM_CLEARSOLD:'clear',ITEM_LIST:'list',OBJECTIVE_UPDATE:'objectives'};
  b.getDefaultDispatcher=()=>({notify(){}});
  return q;
}
function bulk(f,op,{cacheBefore=false}={}){
  const q=base(f.h),b=f.h.sandbox,item=b.services.Item;
  for(const r of f.rows())r.compareTo=other=>other.id===r.id;
  if(op==='clear_sold'){
    item.transfersDao.removeSold=()=>q.request('clear_sold',notify=>{
      f.calls.push('clearSoldItems');f.emit('DELETE','trade/sold');f.effect();
      notify({success:true,status:200,response:{}});
    });
    if(cacheBefore){
      const original=item.itemDao.getTransferPile;let first=true;
      item.itemDao.getTransferPile=function(){if(!first)return original.apply(this,arguments);first=false;
        const value=q.observable();value.notify({success:true,status:304,response:{items:f.rows()}});return value;};
    }
    item.clearSoldItems=vm.runInContext('('+methods.clearSoldItems+')',b);
  }else{
    item.transfersDao.relistExpiredAuctions=()=>q.request('relist_all',notify=>{
      f.calls.push('relistExpiredAuctions');f.emit('PUT','auctionhouse/relist');f.effect();
      notify({success:true,status:200,response:{auctionIds:['NEW']}});
    });
    item.relistExpiredAuctions=function(){return this.transfersDao.relistExpiredAuctions();};
  }
  return q;
}
function resale(f){
  const q=base(f.h),b=f.h.sandbox,item=b.services.Item,leaf=item.itemDao.listItem;
  item.itemDao.listItem=function(...args){
    const value=leaf.apply(this,args),result=q.observable();
    value.observe(this,(sender,v)=>{sender.unobserve(this);
      const raw=b.repositories.Item.getTransferItems()[0];
      result.notify({...v,response:{auctionIds:[raw.getAuctionData().tradeId]}});});
    return result;
  };
  item.transfersDao.getAuctionData=rows=>q.request('list_status',notify=>{
    assert.equal(rows.length,1);const raw=rows[0];
    const x=new b.XMLHttpRequest();x.open('GET','https://utas.test.ea.com/ut/game/fc27/trade/status/lite?tradeIds='+raw.getAuctionData().tradeId);
    x.setRequestHeader('X-UT-SID','CREDENTIAL-CANARY-DO-NOT-RETAIN');x.send();
    notify({success:true,status:200,response:{items:rows}});
  });
  item.refreshAuctions=raw=>item.transfersDao.getAuctionData([raw]);
  item.list=vm.runInContext('('+methods.list+')',b);
  return q;
}
module.exports={base,bulk,resale};

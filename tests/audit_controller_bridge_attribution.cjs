'use strict';
// Finite offline diagnostic, not a green-test surrogate. A failed contract exits 1.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {setup}=require('./controller_native_checks.cjs');
async function probe(){
  const findings=[];
  for(const operation of ['search','watched','caps','transfer_list','unassigned','owned_item']){
    const h=setup(1),b=h.sandbox;
    let params={},route;
    if(operation==='search'){
      params={purpose:'discovery',page:1,count:21,fresh:true,max_bid:1000,min_buy:11000};
      route='transfermarket?start=0&num=21&macr=1000&minb=11000';
    }else if(operation==='watched')route='watchlist';
    else if(operation==='caps'){
      // The test scene's captured service skeleton has no caps method; give it
      // a local DTO-producing observable with no native queue send at all.
      params={definition_id:700000};route='marketdata/pricelimits?defId=700000';
      b.services.Item.transfersDao.getItemMarketDataByDefId=()=>({observe(owner,cb){
        emit(route);cb({unobserve(){}},{success:true,status:200,response:{marketData:[{defId:700000,priceLimits:{minimum:150,maximum:20000}}]}});
      },unobserve(){}});
    }else if(operation==='owned_item'){
      Object.assign(h.raw[0].getAuctionData(),{tradeState:'closed',bidState:'highest',expires:0,currentBid:500,isWon:()=>true});
      const seeded=await h.execute(h.command('watched')),r=seeded.auctions[0];
      params={trade_id:r.trade_id,item_id:r.item.item_id,definition_id:r.item.definition_id};
      route='item?idList='+h.raw[0].id;
    }else{
      route=operation==='transfer_list'?'tradepile':'purchased/items';
      b.ItemPile.TRANSFER=3;b.ItemPile.PURCHASED=2;
      b.repositories.Item.transfer={endOfList:true};b.repositories.Item.getTransferItems=()=>[];
      const method=operation==='transfer_list'?'requestTransferItems':'requestUnassignedItems';
      const leaf=operation==='transfer_list'?'getTransferPile':'getUnassignedPile';
      b.services.Item.itemDao[leaf]=()=>({observe(owner,cb){emit(route);cb({unobserve(){}},{success:true,status:200,response:{items:[]}});},unobserve(){}});
      b.services.Item[method]=()=>b.services.Item.itemDao[leaf]();
    }
    function emit(path){const x=new b.XMLHttpRequest();x.responseText=JSON.stringify({auctionInfo:[]});x.open('GET','https://utas.test.ea.com/ut/game/fc27/'+path);
      x.setRequestHeader('X-UT-SID','CANARY');x.send();}
    h.setOptions({zeroOwned:true,onObserve:()=>emit(route)});
    const c={...h.command(operation,params),schema:2};
    const r=await h.api.executeReadController(c);
    if(!r.result.success)assert.equal(r.result.error,'ambiguous_network','a missing API is not an ownership test');
    findings.push({operation,dialect:2,scenario:'NO_NATIVE_QUEUE_SEND_WITH_MATCHING_UNOWNED_GET',
      success:r.result.success,error:r.result.error,recorded_requests:r.freshness.request_count,
      expected:'REJECT',verdict:r.result.success?'FAIL':'PASS'});
  }
  for(const zeroOwned of [false,true]){
    const h=setup(1),b=h.sandbox;
    h.setOptions({zeroOwned,interleave:!zeroOwned,onObserve:zeroOwned?()=>{
      const x=new b.XMLHttpRequest();x.open('GET','https://utas.test.ea.com/ut/game/fc27/watchlist');
      x.setRequestHeader('X-UT-SID','CANARY');x.send();
    }:undefined});
    const r=await h.execute(h.command('watched'));
    findings.push({operation:'watched',dialect:4,scenario:zeroOwned?'NO_NATIVE_QUEUE_SEND_WITH_MATCHING_UNOWNED_GET':'OWNED_PLUS_UNRELATED_BACKGROUND_GET',
      success:r.success,error:r.error,recorded_requests:r.network.length,background_count:r.background.length,
      expected:zeroOwned?'REJECT':'ACCEPT',verdict:r.success===!zeroOwned?'PASS':'FAIL'});
  }
  const h=setup(1);h.setOptions({interleave:true});
  const r=await h.api.executeReadController({...h.command('search',{purpose:'discovery',page:1,count:21,fresh:true,max_bid:1000,min_buy:11000}),schema:2});
  findings.push({operation:'search',dialect:2,scenario:'OWNED_PLUS_UNRELATED_BACKGROUND_GET',success:r.result.success,error:r.result.error,
    recorded_requests:r.freshness.request_count,expected:'ACCEPT',verdict:r.result.success?'PASS':'FAIL'});
  const result={classification:'OFFLINE_SYNTHETIC_INTERLEAVING_AUDIT',live_ea_requests:0,account_mutations:0,findings};
  if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result));return findings.every(f=>f.verdict==='PASS')?0:1;
}
if(require.main===module)probe().then(code=>{process.exitCode=code;}).catch(e=>{console.error(e);process.exitCode=2;});
module.exports={probe};

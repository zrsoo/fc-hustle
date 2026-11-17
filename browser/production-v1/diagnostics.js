/* Bounded, positive-allowlist diagnostics. No raw bodies or authentication data. */
(() => {
  'use strict';
  if(window.__fcProductionDiagnosticsV1)return;
  const stages=new Set(['UNCLASSIFIED_EA_REQUEST','BACKGROUND_REQUEST','BACKGROUND_RESPONSE','BULK_REQUEST_BLOCKED','PAGE_ENTER','NATIVE_INVOKE','NATIVE_CALLBACK','NATIVE_TIMEOUT','EA_RESPONSE','EA_BODY','WIRE_AUCTION','NATIVE_DATA','ITEM_SCHEMA_FAILURE','PAGE_FAILURE','PAGE_FINISHED']);
  const types=new Set(['undefined','null','boolean','number','string','object','array','function']);
  const errors=new Set(['invalid_command','wrong_page','bridge_busy','persona_unverified','service_unavailable','service_timeout','service_failed','schema_unrecognized','unsafe_identity','stale_source','unauthenticated','ambiguous_network','invalid_preconditions','internal_error','helpers_unavailable','helper_disagreement','known_identity_unavailable']);
  const records=new Map();
  function record(id,stage,detail={}){
    if(!/^[a-f0-9]{32}$/.test(id)||!stages.has(stage))return;
    if(!records.has(id)){if(records.size>=4)records.delete(records.keys().next().value);records.set(id,[]);}
    const rows=records.get(id);if(rows.length>=64)return;
    const safe={};
    for(const key of ['row_count','request_count','definition_count'])if(Number.isSafeInteger(detail[key])&&detail[key]>=0&&detail[key]<=100)safe[key]=detail[key];
    if(Number.isInteger(detail.status)&&detail.status>=100&&detail.status<=599)safe.status=detail.status;
    for(const key of ['success','xhr_zero_status'])if(typeof detail[key]==='boolean')safe[key]=detail[key];
    for(const key of ['wire_ready','wire_target_found','wire_identity_matches','wire_callback_matches','message_present','reason_present'])if(typeof detail[key]==='boolean')safe[key]=detail[key];
    if(Number.isInteger(detail.target_index)&&detail.target_index>=0&&detail.target_index<10)safe.target_index=detail.target_index;
    for(const key of ['wire_current_bid','wire_starting_bid','wire_buy_now_price','wire_error_code'])if(Number.isSafeInteger(detail[key])&&detail[key]>=0)safe[key]=detail[key];
    if(Number.isSafeInteger(detail.wire_expires)&&detail.wire_expires>=-1)safe.wire_expires=detail.wire_expires;
    if(['none','highest','outbid','buyNow','sold'].includes(detail.wire_bid_state))safe.wire_bid_state=detail.wire_bid_state;
    if(['active','closed','expired','inactive'].includes(detail.wire_trade_state))safe.wire_trade_state=detail.wire_trade_state;
    if(['club','transfer','purchased','inbox','storage','other'].includes(detail.item_pile))safe.item_pile=detail.item_pile;
    for(const key of ['definition_type','resource_type','data_type'])if(types.has(detail[key]))safe[key]=detail[key];
    if(errors.has(detail.error))safe.error=detail.error;
    if(detail.error==='bulk_contract_changed')safe.error=detail.error;
    if(['ea_read','ea_write','outside_ut'].includes(detail.traffic_scope))safe.traffic_scope=detail.traffic_scope;
    if(['GET','POST','PUT','DELETE','OTHER'].includes(detail.method))safe.method=detail.method;
    if(['SETTINGS','USER_MASSINFO','USER','CLUB','SQUAD','STORE','FAVORITES','AUCTIONHOUSE','ITEM','OTHER'].includes(detail.route_group))safe.route_group=detail.route_group;
    if(['body','query','route','duplicate'].includes(detail.violation))safe.violation=detail.violation;
    if(['Error','TypeError','RangeError','SyntaxError'].includes(detail.error_class))safe.error_class=detail.error_class;
    rows.push({stage,at:new Date().toISOString(),detail:safe});
  }
  Object.defineProperty(window,'__fcProductionDiagnosticsV1',{value:Object.freeze({record,get:id=>JSON.parse(JSON.stringify(records.get(id)??[]))})});
})();

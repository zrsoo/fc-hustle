/* Bounded, positive-allowlist diagnostics. No raw bodies or authentication data. */
(() => {
  'use strict';
  if(window.__fcProductionDiagnosticsV1)return;
  const stages=new Set(['PAGE_ENTER','NATIVE_INVOKE','NATIVE_CALLBACK','NATIVE_TIMEOUT','EA_RESPONSE','NATIVE_DATA','ITEM_SCHEMA_FAILURE','PAGE_FAILURE','PAGE_FINISHED']);
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
    for(const key of ['success'])if(typeof detail[key]==='boolean')safe[key]=detail[key];
    for(const key of ['definition_type','resource_type','data_type'])if(types.has(detail[key]))safe[key]=detail[key];
    if(errors.has(detail.error))safe.error=detail.error;
    if(['Error','TypeError','RangeError','SyntaxError'].includes(detail.error_class))safe.error_class=detail.error_class;
    rows.push({stage,at:new Date().toISOString(),detail:safe});
  }
  Object.defineProperty(window,'__fcProductionDiagnosticsV1',{value:Object.freeze({record,get:id=>JSON.parse(JSON.stringify(records.get(id)??[]))})});
})();

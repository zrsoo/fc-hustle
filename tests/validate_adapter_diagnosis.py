"""Independent offline assessment of the one authorized diagnostic search."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.production_v1.diagnose_search import OUT
from fc_access.production_v1.contracts import Search,parse_response,stamp
from fc_access.release_audit_v1 import private_fields


def need(value,reason):
 if not value:raise ValueError(reason)


def validate():
 s=json.loads((OUT/'checkpoint.json').read_text());records=json.loads((OUT/'transport.json').read_text())
 private_fields(s);private_fields(records)
 need(s['mode']=='READ_ONLY_ADAPTER_DIAGNOSIS_NOT_PERFORMANCE_GATE' and s['status']=='SEARCH_ACKNOWLEDGED','diagnostic_not_acknowledged')
 need(s['account_mutations']==0 and 'valuation_start_ns' not in s,'gate_or_mutation_executed')
 need(s['budget']==dict(authentication_GETs=1,broad_discovery_GETs=1,pricing_GETs=0,helpers=0,valuations=0,retries=0),'wrong_budget')
 for path,digest in s['preserved_checkpoints'].items():
  need(hashlib.sha256((Path(__file__).resolve().parents[1]/path).read_bytes()).hexdigest()==digest,'previous_failed_checkpoint_changed')
 need(len(s['operations'])==len(records)==2,'wrong_operation_count')
 events=[];requests=[]
 for index,(e,t) in enumerate(zip(s['operations'],records)):
  c=e['command'];r=e['response']
  need((c['operation'],c['params'])==([('balance',{}),('search',Search.discovery().params())][index]),'wrong_read_only_sequence')
  need(t['state']=='ACKNOWLEDGED' and t['command']==c and t['result']==r and e['state']=='RESPONSE_RECORDED','checkpoint_vs_transport_mismatch')
  need(c['context']==s['context'] and c['fences']==s['fences'],'scope_changed')
  need(e['start_ns']<=e['finish_ns']<=s['finished_ns']<s['deadline_ns'],'diagnostic_deadline_or_time')
  parse_response(r,c,source='native',now=stamp(r['freshness']['observed_at']))
  need(r['result']['success'] is True,'native_failure')
  trace=[]
  for item in t['events']:
   value=item['event']
   if type(value) is dict:
    need(value['kind']!='RESULT_REJECTED','live_result_rejected')
    trace+=value.get('records',[])
  stages=[v['stage'] for v in trace]
  for stage in ('WORKER_EXECUTE','WORKER_RESULT','WORKER_POST_RESULT','WORKER_ACK','PAGE_ENTER','NATIVE_INVOKE','EA_RESPONSE','NATIVE_CALLBACK','NATIVE_DATA','PAGE_FINISHED'):
   need(stage in stages,'missing_stage:'+stage)
  need(not set(stages)&{'WORKER_FAILURE','PAGE_FAILURE','NATIVE_TIMEOUT','ITEM_SCHEMA_FAILURE'},'failure_in_live_trace')
  if index==1:
   need(any(v['stage']=='NATIVE_DATA' and v['detail'].get('definition_type')=='array' and v['detail'].get('definition_count')==0 for v in trace),'native_broad_defaults_not_observed')
  n=r['result']['network'];need(len(n)==1 and n[0]['method']=='GET' and n[0]['status']==200 and n[0]['session_header_present'],'not_one_authenticated_GET')
  requests+=n;events+=trace
 need(requests[0]['query']=={} and requests[1]['query']==dict(start=0,num=21,macr=1000,minb=11000),'wire_filters_changed')
 need(s['operations'][0]['finish_ns']<=s['operations'][1]['start_ns'],'not_serialized')
 return dict(diagnostic_status='PASS',EA_GETs=2,broad_searches=1,search_rows=len(s['operations'][1]['response']['result']['auctions']),
  mutations=0,pricing_GETs=0,performance_gates=0,prior_checkpoints_unchanged=True,
  prior_failure_reproduced=False,underlying_search_root_cause='NOT_CONFIRMED',behavior_fix_executed=False,
  interpretation='The instrumented production search succeeded; the earlier rejection/transport hypothesis was not reproduced.')


if __name__=='__main__':print(json.dumps(validate(),indent=2))

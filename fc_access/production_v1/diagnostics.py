"""Typed metadata only, including for rejected/untrusted result envelopes."""
from datetime import datetime,timezone
import math
from .contracts import fields,integer,stamp,ERRORS,ROUTES,METADATA_PATH

STAGES={'PAGE_ENTER','NATIVE_INVOKE','NATIVE_CALLBACK','NATIVE_TIMEOUT','EA_RESPONSE','NATIVE_DATA',
        'ITEM_SCHEMA_FAILURE','PAGE_FAILURE','PAGE_FINISHED','WORKER_EXECUTE','WORKER_RESULT',
        'WORKER_POST_RESULT','WORKER_ACK','WORKER_FAILURE'}
TYPES={'undefined','null','boolean','number','string','object','array','function'}
REASONS={'invalid_fields','invalid_result','invalid_status','invalid_cache_evidence','invalid_integer','invalid_item',
 'invalid_rows','invalid_auction','duplicate_identity','wrong_exact_definition','invalid_network','wrong_native_route',
 'invalid_network_status','invalid_query','invalid_request_source','unsupported_freshness','unsupported_coverage',
 'invalid_timing','stale_or_unauthenticated_source','native_status_mismatch','operation_payload_mismatch','cache_only_source',
 'missing_exact_wire_definition','wire_criteria_mismatch','response_correlation_mismatch','invalid_time','timezone_required',
 'unknown_or_duplicate_result','wrong_result_peer','stale_peer','reattach_required','wire_metadata_identity_mismatch'}

def typename(value):
    if value is None:return 'null'
    return {bool:'boolean',int:'number',float:'number',str:'string',dict:'object',list:'array'}.get(type(value),'other')

def safe_reason(error):
    return str(error) if type(error) is ValueError and str(error) in REASONS else type(error).__name__ if type(error).__name__ in {'ValueError','TypeError','KeyError','OverflowError','OSError'} else 'validation_failed'

def validate_records(records):
    if type(records) is not list or len(records)>64:raise ValueError('invalid_diagnostic')
    for row in records:
        fields(row,{'stage','at','detail'});stamp(row['at'])
        if row['stage'] not in STAGES or type(row['detail']) is not dict:raise ValueError('invalid_diagnostic')
        for key,value in row['detail'].items():
            if key in {'row_count','request_count','definition_count'}:integer(value,0);valid=value<=100
            elif key in {'status','local_status'}:valid=type(value) is int and 100<=value<=599
            elif key=='success':valid=type(value) is bool
            elif key in {'definition_type','resource_type','data_type'}:valid=value in TYPES
            elif key=='error':valid=value in ERRORS
            elif key=='error_class':valid=value in {'Error','TypeError','RangeError','SyntaxError'}
            elif key=='worker_stage':valid=value in {'execute','result','post_result'}
            elif key=='reason':valid=value in {'local_rejected','worker_exception'}
            else:valid=False
            if not valid:raise ValueError('invalid_diagnostic')
    return records

def result_summary(value,command):
    # Never copy unknown keys, arbitrary strings, IDs, bodies or exception text.
    v=value if type(value) is dict else {};r=v.get('result') if type(v.get('result')) is dict else {}
    result=dict(envelope_type=typename(value),top_field_count=len(v),
        success=r.get('success') if type(r.get('success')) is bool else None,
        error=r.get('error') if type(r.get('error')) is str and r['error'] in ERRORS else None,
        status=r.get('status') if type(r.get('status')) is int and 100<=r['status']<=599 else None,
        correlation_matches=all(v.get(k)==command[k] for k in ('schema','operation','context','fences')) and v.get('command_id')==command['id'])
    result['top_shape']={k:typename(v[k]) if k in v else 'undefined' for k in
        ('schema','command_id','operation','context','fences','result','freshness','coverage','timing')}
    result['result_shape']={k:typename(r[k]) if k in r else 'undefined' for k in
        ('success','error','status','credits','items','auctions','caps','cache_invalidated','network')}
    rows=r.get('auctions');result['row_count']=len(rows) if type(rows) is list else None
    result['row_shapes']=[]
    for row in rows[:21] if type(rows) is list else []:
        a=row if type(row) is dict else {};i=a.get('item') if type(a.get('item')) is dict else {}
        result['row_shapes'].append(dict(row_type=typename(row),fields={k:typename(a[k]) if k in a else 'undefined' for k in
            ('trade_id','starting_bid','current_bid','buy_now_price','expires','trade_state','bid_state','native_is_won')},
            item_fields={k:typename(i[k]) if k in i else 'undefined' for k in ('item_id','definition_id','untradeable','last_sale_price')}))
    result['network']=[]
    for n in r.get('network',[])[:30] if type(r.get('network')) is list else []:
        if type(n) is not dict:continue
        query=n.get('query') if type(n.get('query')) is dict else {}
        result['network'].append(dict(method=n.get('method') if type(n.get('method')) is str and n['method'] in {'GET','PUT','OTHER'} else 'other',
            path=n.get('path') if type(n.get('path')) is str and n['path'] in {p for _,p in ROUTES.values()} | {METADATA_PATH} else '/unexpected',
            status=n.get('status') if type(n.get('status')) is int and 100<=n['status']<=599 else None,
            session_header_present=n.get('session_header_present') is True,
            query={k:query[k] for k in ('start','num','definitionId','defId','macr','minb','maxb') if type(query.get(k)) is int and 0<=query[k]<=2**53-1}))
        ids=query.get('defIds')
        if type(ids) is list and 1<=len(ids)<=21 and all(type(d) is int and 0<d<=2**53-1 for d in ids):
            result['network'][-1]['query']['defIds']=list(ids)
    t=v.get('timing') if type(v.get('timing')) is dict else {}
    result['timing']={k:t[k] if type(t.get(k)) in {int,float} and math.isfinite(t[k]) and 0<=t[k]<=120000 else typename(t.get(k)) for k in ('native_service_ms','ea_rtt_ms','native_helper_ms')}
    return result

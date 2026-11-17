"""Independent finite-probe audit; explicitly does not certify the objective."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.protocol import delivery_command,delivery_response
OUT=ROOT/'docs/research/005/stage02'


def need(value,reason):
    if not value:raise ValueError(reason)


def validate(rows,result,analysis):
    need(rows[0]['kind']=='PREPARED' and rows[0]['max_initial_mutations']==1 and rows[0]['max_other_mutations']==0,'finite_prepared_scope')
    need(rows[-1]['kind']=='CLOSED' and rows[-1]['result']==result,'closed_consumed_window')
    reserved=[r for r in rows if r['kind']=='RESERVED_BEFORE_DELIVERY'];results=[r for r in rows if r['kind']=='NATIVE_RESULT']
    need(len(reserved)==len(results)==129 and len({r['command']['id'] for r in reserved})==129,'single_delivery_ids')
    need([r['ordinal'] for r in reserved]==list(range(1,130)),'durable_reservation_sequence')
    actual=[];by_operation={};responses={}
    for r,v in zip(reserved,results):
        c,response=v['command'],v['response'];delivery_command(c)
        need(c==r['command'] and rows.index(r)<rows.index(v),'intent_before_delivery')
        need(c['context']==rows[0]['context'],'consistent_account_context')
        at=response['observed_at'] if c['schema']==4 else response['freshness']['observed_at']
        parsed=delivery_response(response,c,now=datetime.fromisoformat(at))
        payload=parsed if c['schema']==4 else parsed['result']
        actual.extend(payload['network']);by_operation.setdefault(c['operation'],[]).append(v);responses[c['id']]=v
        if c['operation']!='bid':need(payload['success'] is True,'native_read_failure_not_hidden')
    need(len(actual)==26 and Counter(n['method'] for n in actual)=={'GET':25,'PUT':1},'actual_native_request_inventory')
    need(sum(r['reserved_ea'] for r in reserved)==result['reserved_ea']==32,'request_reservation_accounting')
    need(len(by_operation['bid'])==1 and result['account_mutations']==1,'one_irreversible_intent')
    write=by_operation['bid'][0];c,v=write['command'],write['response'];p=c['params'];target=p['target'];receipt=v['receipt']
    need(v['success'] is False and v['error']=='ambiguous_network' and v['status']==403 and v['network'][0]['status']==461,'retained_layer_statuses')
    need(receipt['verdict']=='UNCONFIRMED' and receipt['native_success'] is False and receipt['native_error_code']==461 and receipt['matching_item_count']==0,'no_invented_bid_acceptance')
    need(receipt['wire_trade_id']==target['trade_id'] and receipt['wire_amount']==p['amount']==850 and p['cap']==4300,'exact_durable_target_amount_cap')
    discovery=responses[p['status_read_id']]['response'];before=next(row for row in discovery['result']['auctions'] if row['trade_id']==target['trade_id'])
    need(before['item']['item_id']==target['item_id'] and before['item']['definition_id']==target['definition_id'] and before['current_bid']==800,'full_discovery_link')
    status=by_operation['status_batch'][0]['response'];after=status['auctions'][0]
    need(status['success'] and not status['missing'] and len(status['links'])==1 and status['links'][0]['full_read_id']==discovery['command_id'],'independent_exact_status_link')
    need(after['trade_id']==target['trade_id'] and after['item']['item_id']==target['item_id'] and after['current_bid']==900 and after['bid_state']=='none','real_account_state_no_participation')
    age=(datetime.fromisoformat(v['network_at'])-datetime.fromisoformat(discovery['freshness']['network_at'])).total_seconds()
    need(age==analysis['discovery_age_at_bid_seconds'] and before['expires']-age>60,'honest_age_and_eligibility')
    selected=analysis['candidate_selection']
    need(selected['selection_remaining']>60 and selected['minimum']==850 and selected['cap']==4300 and selected['resale_price']==5100,'unchanged_strategy_values')
    need(result['confirmed_members']==0 and result['attempts'][0]['state']=='UNKNOWN' and result['status']=='NO_CONFIRMED_PARTICIPATION','unknown_preserved_not_resolved')
    readback=next(r for r in rows if r['kind']=='INDEPENDENT_ACCOUNT_READBACK')['response']
    need(readback['success'] is True and not readback['auctions'] and datetime.fromisoformat(readback['network_at'])>datetime.fromisoformat(v['observed_at']),'fresh_personal_watch_readback')
    diagnostics=[r for group in analysis['diagnostics'] for r in group]
    need(any(r['stage']=='EA_RESPONSE' and r['detail'].get('status')==461 for r in diagnostics),'wire_diagnostic_retained')
    need(any(r['stage']=='NATIVE_CALLBACK' and r['detail']==dict(status=403,success=False) for r in diagnostics),'service_diagnostic_retained')
    need(result['pending']==0 and result['service_stopped'] is True,'finite_probe_quiesced')
    need(len([r for r in rows if r['kind']=='SEMANTIC_RESULT'])==127,'callback_gap_honestly_disclosed')
    return dict(commands=129,ea_requests=26,bid_intents=1,confirmed_members=0,unknown_preserved=1,
                wire_status=461,service_status=403,discovery_age_seconds=age,callback_messages_missing=2)


def main():
    seal=json.loads((OUT/'sealed-evidence.json').read_text())
    allowed={f'docs/research/005/stage02/bid-0{i}/{name}' for i in (1,2,3)
             for name in ('checkpoint.jsonl','result.json')}
    allowed.add('docs/research/005/stage02/bid-03/analysis.json')
    need({r['path'] for r in seal['files']}==allowed and len(seal['files'])==len(allowed),'captured_evidence_seal_scope')
    for r in seal['files']:need(hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_ea_evidence_changed')
    for window in ('bid-01','bid-02'):
        result=json.loads((OUT/window/'result.json').read_text())
        need(result['commands']==result['account_mutations']==result['pending']==0 and result['service_stopped'] is True,'failed_attachment_had_no_native_dispatch')
    rows=[json.loads(s) for s in (OUT/'bid-03/checkpoint.jsonl').read_text(encoding='utf-8').splitlines()]
    result=json.loads((OUT/'bid-03/result.json').read_text());analysis=json.loads((OUT/'bid-03/analysis.json').read_text())
    summary=validate(rows,result,analysis)
    safe=json.loads((OUT/'final-state.json').read_text())
    quiet=json.loads((OUT/'final-quiescence.json').read_text(encoding='utf-8-sig'))
    need(safe['active_members']==safe['pending_commands']==0 and safe['attempt_states']=={'UNKNOWN':20} and
         safe['controller'][0]['lifecycle']=='STOPPED','captured_safe_local_state')
    need(not quiet['production_listeners'] and not quiet['production_workers'] and not quiet['scheduled_mutation_jobs'],
         'independent_quiescent_process_capture')
    negatives=0
    for edit in (
        lambda r,v,a:v.update(confirmed_members=1),lambda r,v,a:v.update(account_mutations=0),
        lambda r,v,a:next(x for x in r if x['kind']=='NATIVE_RESULT' and x['command']['operation']=='bid')['response'].update(success=True),
        lambda r,v,a:a['candidate_selection'].update(selection_remaining=60),
        lambda r,v,a:a['diagnostics'].clear(),lambda r,v,a:r.pop(2)):
        r,v,a=deepcopy(rows),deepcopy(result),deepcopy(analysis);edit(r,v,a)
        # Keep an attacker's duplicated summary consistent: the actual native
        # evidence and contract checks must reject the claim independently.
        r[-1]['result']=deepcopy(v)
        try:validate(r,v,a)
        except (ValueError,KeyError,IndexError):negatives+=1
        else:raise ValueError('negative_case_accepted')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',live=summary,negative_checks=negatives,quiescent=True)))


if __name__=='__main__':main()

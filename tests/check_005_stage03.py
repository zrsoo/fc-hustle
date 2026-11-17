"""Audit the consumed live freshness experiment, never certify full completion."""
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
OUT=ROOT/'docs/research/005/stage03'


def need(value,reason):
    if not value:raise ValueError(reason)


def validate(rows,result):
    need(rows[0]['kind']=='PREPARED' and rows[0]['fresh_status_experiment'] is True and
         rows[0]['max_initial_mutations']==1 and rows[0]['max_other_mutations']==0,'finite_intent')
    need(rows[-1]['kind']=='CLOSED' and rows[-1]['result']==result,'consumed_closed_window')
    reserved=[r for r in rows if r['kind']=='RESERVED_BEFORE_DELIVERY']
    results=[r for r in rows if r['kind']=='NATIVE_RESULT']
    semantics=[r for r in rows if r['kind']=='SEMANTIC_RESULT']
    need(len(reserved)==len(results)==len(semantics)==99,'complete_delivery_and_monitoring')
    need(len({r['command']['id'] for r in reserved})==99,'unique_intents')
    need([r['ordinal'] for r in reserved]==list(range(1,100)),'durable_intent_sequence')
    by_id={};ops={};network=[]
    for reservation,outcome in zip(reserved,results):
        command,response=outcome['command'],outcome['response'];delivery_command(command)
        need(command==reservation['command'] and rows.index(reservation)<rows.index(outcome),'intent_before_dispatch')
        need(command['context']==rows[0]['context'],'same_account')
        at=response['observed_at'] if command['schema']==4 else response['freshness']['observed_at']
        parsed=delivery_response(response,command,now=datetime.fromisoformat(at))
        payload=parsed if command['schema']==4 else parsed['result']
        need(payload['success'] is True,'failed_native_operation')
        if command['schema']==2:need(response['freshness']['source']=='native','fixture_not_account_evidence')
        network.extend(payload['network']);by_id[command['id']]=outcome
        ops.setdefault(command['operation'],[]).append(outcome)
    need(len(network)==21 and Counter(n['method'] for n in network)=={'GET':20,'PUT':1},'actual_account_request_inventory')
    need(all(n['status']==200 and n['session_header_present'] is True for n in network),'authenticated_native_success')
    need(result['account_mutations']==len(ops['bid'])==1,'one_consumed_write')
    need(sum(r['reserved_ea'] for r in reserved)==result['reserved_ea']==26,'request_reservations')
    write=ops['bid'][0];command,response=write['command'],write['response'];p=command['params'];target=p['target']
    receipt=response['receipt']
    need(receipt['verdict']=='ACCEPTED' and receipt['native_success'] is True and receipt['matching_item_count']==1 and
         receipt['wire_identity_matches'] is True and receipt['wire_amount_matches'] is True and
         receipt['wire_trade_id']==target['trade_id'] and receipt['wire_amount']==p['amount']==700,'matching_wire_service_receipt')
    selection=next(r for r in rows if r['kind']=='FRESH_SELECTION')
    before=next(c for c in selection['before'] if c['target']==target)
    after=next(c for c in selection['after'] if c['target']==target)
    need(before['read_id']!=after['read_id']==selection['status_read_id']==p['status_read_id'],'fresh_status_authority')
    need(after['selection_remaining']>60 and after['selection_age']<1 and p['minimum']==after['minimum']==700,'eligibility_and_minimum')
    need(before['quote']==after['quote'] and before['cap']==after['cap']==p['cap']==4100 and
         before['resale_price']==after['resale_price']==4900 and after['quote']['status']=='COMPLETE','unchanged_profitable_quote')
    fresh=by_id[p['status_read_id']];need(rows.index(fresh)<rows.index(write),'read_before_write')
    links=fresh['response']['links'];link=next(v for v in links if v['target']==target)
    full=by_id[link['full_read_id']]['response']
    need(any(r['trade_id']==target['trade_id'] and r['item']['item_id']==target['item_id'] and
             r['item']['definition_id']==target['definition_id'] for r in full['result']['auctions']),'full_version_identity')
    post=ops['status_batch'][-1];pr=post['response']
    need(post['command']['id']!=fresh['command']['id'] and rows.index(post)>rows.index(write),'independent_post_bid_status')
    row=next(r for r in pr['auctions'] if r['trade_id']==target['trade_id'])
    need(row['item']['item_id']==target['item_id'] and row['bid_state']=='highest' and row['current_bid']==700 and
         any(l['target']==target and l['full_read_id']==link['full_read_id'] for l in pr['links']),'independent_membership_confirmation')
    watch=next(r for r in rows if r['kind']=='INDEPENDENT_ACCOUNT_READBACK')['response']
    need(watch['success'] is True and datetime.fromisoformat(watch['network_at'])>datetime.fromisoformat(response['observed_at']) and
         any(r['trade_id']==target['trade_id'] and r['item']['definition_id']==target['definition_id'] and
             r['item']['item_id']==target['item_id'] and r['bid_state']=='highest' and r['current_bid']==700 for r in watch['auctions']),
         'personal_account_membership')
    need(result['status']=='CONFIRMED_PARTICIPATION' and result['confirmed_members']==1 and
         result['attempts'][0]['state']=='ACKNOWLEDGED' and result['attempts'][0]['command_id']==command['id'],'honest_result')
    need(result['semantic']['reason'] is None and result['semantic']['native_successes']==21 and
         result['pending']==0 and result['service_stopped'] is True,'finite_probe_stopped')
    return dict(commands=99,monitor_callbacks=99,ea_requests=21,bid_amount=700,confirmed_members=1,
                terminal_settlement_observed=False,healthy_operational_seconds=0)


def main():
    seal=json.loads((OUT/'sealed-evidence.json').read_text())
    expected={f'docs/research/005/stage03/fresh-bid-01/{n}' for n in ('checkpoint.jsonl','result.json')}
    need({r['path'] for r in seal['files']}==expected and len(seal['files'])==2,'immutable_capture_scope')
    for row in seal['files']:need(hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256'],'captured_evidence_changed')
    rows=[json.loads(s) for s in (OUT/'fresh-bid-01/checkpoint.jsonl').read_text().splitlines()]
    result=json.loads((OUT/'fresh-bid-01/result.json').read_text());summary=validate(rows,result)
    negatives=0
    def bid(r):return next(v for v in r if v['kind']=='NATIVE_RESULT' and v['command']['operation']=='bid')
    for edit in (
        lambda r,v:bid(r)['response']['receipt'].update(verdict='UNCONFIRMED'),
        lambda r,v:bid(r)['response']['receipt'].update(wire_amount=750),
        lambda r,v:next(x for x in r if x['kind']=='FRESH_SELECTION')['after'][0].update(selection_remaining=60),
        lambda r,v:next(x for x in r if x['kind']=='INDEPENDENT_ACCOUNT_READBACK')['response'].update(auctions=[]),
        lambda r,v:r.remove(next(x for x in r if x['kind']=='SEMANTIC_RESULT')),
        lambda r,v:v.update(account_mutations=2)):
        r,v=deepcopy(rows),deepcopy(result);edit(r,v);r[-1]['result']=deepcopy(v)
        try:validate(r,v)
        except (ValueError,KeyError,IndexError):negatives+=1
        else:raise ValueError('negative_evidence_accepted')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',live=summary,negative_checks=negatives)))


if __name__=='__main__':main()

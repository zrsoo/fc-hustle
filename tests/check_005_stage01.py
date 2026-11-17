"""Independently audit retained incident and fresh read-only window; not completion."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.protocol import delivery_command, delivery_response

INCIDENT=ROOT/'docs/research/005/incident-20261117T010101301454Z/incident.json'
READ=ROOT/'docs/research/005/read-02'


def require(condition, reason):
    if not condition:raise ValueError(reason)


def validate_incident(value):
    require(value['classification']=='HISTORICAL_INCIDENT_PROJECTION_NOT_LIVE_PROOF','historical_classification')
    commands=value['commands'];ids=[c['command_id'] for c in commands]
    require(len(ids)==len(set(ids))==302,'incident_command_identity')
    require(Counter(b['state'] for b in value['batches'])=={'READ_FAILED':35,'OPERATION_FAILED':4,'SETTLED':2},'incident_batch_states')
    bids=[c for c in commands if c['operation']=='bid']
    require(len(bids)==19 and value['member_count']==0,'historical_participation_not_confirmed')
    require(len(value['attempts'])==19 and all(a['state']=='UNKNOWN' for a in value['attempts']),'unknown_preservation')
    require({a['command_id'] for a in value['attempts']}=={c['command_id'] for c in bids},'intent_correlation')
    counts=Counter()
    for c in bids:
        n=c['network'];r=c['receipt']
        require(len(n)==1 and n[0]['method']=='PUT' and n[0]['path']=='/ut/game/fc27/trade/:trade/bid' and n[0]['targets']==[c['target']], 'owned_bid_binding')
        require(n[0]['session_header_present'] is True,'request_auth_presence')
        require(c['success'] is False and r['verdict']=='UNCONFIRMED','no_invented_acceptance')
        require(r['wire_identity_matches'] is True and r['wire_trade_id']==c['target']['trade_id'] and r['wire_amount']==c['amount'] and r['wire_amount_matches'] is True,'receipt_amount_identity')
        counts[(n[0]['status'],c['service_status'],c['error'],r['native_error_code'])]+=1
    require(counts=={(461,403,'ambiguous_network',461):12,(401,401,'service_failed',401):7},'layer_status_classes')
    balances=Counter((c['success'],c['service_status']) for c in commands if c['operation']=='balance')
    require(balances=={(True,200):6,(False,401):30,(None,None):4},'balance_failures_and_unknowns')
    return dict(commands=len(commands),bids=len(bids),unknown=19,wire461_service403=12,wire401_service401=7,balance_401=30,confirmed_members=0)


def validate_reads(rows, result):
    require(rows[0]['kind']=='PREPARED' and rows[0]['max_mutations']==0,'read_only_preparation')
    require(rows[-1]['kind']=='CLOSED' and rows[-1]['result']==result,'closed_result')
    reservations=[r for r in rows if r['kind']=='RESERVED_BEFORE_DELIVERY']
    captures=[r for r in rows if r['kind']=='NATIVE_RESULT']
    require(len(reservations)==len(captures)==6,'finite_reserved_commands')
    require([r['ordinal'] for r in reservations]==list(range(1,7)),'durable_single_delivery')
    require(len({r['command']['id'] for r in reservations})==6,'distinct_commands')
    operations=[];networks=[];discovery=None
    for reserved,capture in zip(reservations,captures):
        c,v=capture['command'],capture['response']
        require(c==reserved['command'],'command_intent_binding')
        require(rows.index(reserved)<rows.index(capture),'intent_precedes_delivery')
        delivery_command(c)
        parsed=delivery_response(v,c,now=datetime.fromisoformat(v['observed_at'] if c['schema']==4 else v['freshness']['observed_at']))
        r=parsed if c['schema']==4 else parsed['result']
        require(c['context']==rows[0]['context'] and r['success'] is True,'scope_and_native_success')
        require(r['status']==200 and all(n['method']=='GET' and n['status']==200 and n['session_header_present'] is True for n in r['network']),'genuine_gets_only')
        operations.append(c['operation']);networks.extend(r['network'])
        if c['operation']=='search':discovery=v
        if c['operation']=='status_batch':
            expected=[dict(trade_id=r['trade_id'],item_id=r['item']['item_id'],definition_id=r['item']['definition_id']) for r in discovery['result']['auctions'][:10]]
            require(c['params']['targets']==expected,'fresh_discovery_targets')
            require(len(v['auctions'])==len(v['links'])==10 and not v['missing'],'ten_exact_status_rows')
            require(all(l['full_read_id']==discovery['command_id'] for l in v['links']),'independent_full_identity_links')
    require(operations==['balance','watched','transfer_list','unassigned','search','status_batch'],'operation_inventory')
    require(len(networks)<=rows[0]['max_ea_requests'] and len(networks)>=6,'finite_actual_gets')
    require(result['status']=='READS_VERIFIED' and result['mutations']==0 and result['pending']==0 and result['service_stopped'] is True,'closed_safe_state')
    return dict(commands=6,actual_gets=len(networks),mutations=0,status_targets=10)


def main():
    seal=json.loads((ROOT/'docs/research/005/sealed-stage01-evidence.json').read_text())
    require(seal['classification']=='IMMUTABLE_CAPTURED_EA_EVIDENCE_ONLY','capture_seal_scope')
    expected={INCIDENT.relative_to(ROOT).as_posix(),(READ/'checkpoint.jsonl').relative_to(ROOT).as_posix(),(READ/'result.json').relative_to(ROOT).as_posix()}
    require({entry['path'] for entry in seal['files']}==expected and len(seal['files'])==3,'captured_file_inventory')
    for entry in seal['files']:
        require(hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256'],'captured_ea_evidence_changed')
    incident=validate_incident(json.loads(INCIDENT.read_text(encoding='utf-8')))
    reads=validate_reads([json.loads(line) for line in (READ/'checkpoint.jsonl').read_text(encoding='utf-8').splitlines()],json.loads((READ/'result.json').read_text()))
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',incident=incident,reads=reads)))


if __name__=='__main__':main()

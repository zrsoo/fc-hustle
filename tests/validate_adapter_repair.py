"""Independent retained-live assessor. Never contacts Edge, EA or localhost."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.production_v1 import gate_00203 as gate
from fc_access.production_v1.contracts import METADATA_PATH,parse_response,Search
from fc_access.release_audit_v1 import private_fields

OUT=gate.OUT/'adapter-repair/20261114-01'


def validate():
    for base in (OUT,gate.SIXTH_CHECKPOINT.parent):
        manifest=json.loads((base/'evidence-manifest.json').read_text(encoding='utf8'))
        for relative,digest in manifest['files'].items():
            path=(base/relative).resolve()
            gate.need(path.is_relative_to(base.resolve()) and path.suffix in {'.json','.txt'},'invalid_evidence_manifest_path')
            gate.need(hashlib.sha256(path.read_bytes()).hexdigest()==digest,'captured_evidence_changed')
    total=0
    for name,query in [('smoke-01',Search.discovery().params()),('metadata-smoke-02',Search.pricing(50573369).params())]:
        s=json.loads((OUT/name/'checkpoint.json').read_text(encoding='utf8'))
        gate.need(s['status']=='SEARCH_ACKNOWLEDGED' and s['account_mutations']==0 and len(s['operations'])==2,'probe_not_acknowledged')
        gate.need(s['health_before']['mutations_enabled'] is False and s['context']['platform']=='pc','wrong_probe_scope')
        captures=json.loads((OUT/name/'transport.json').read_text(encoding='utf8'))
        private_fields(captures)
        gate.need(len(captures)==2,'missing_transport_evidence')
        for index,(entry,capture) in enumerate(zip(s['operations'],captures)):
            c,r=entry['command'],entry['response']
            gate.need(c['operation']==('balance' if index==0 else 'search') and c['params']==({} if index==0 else query),'probe_budget_or_query')
            parse_response(r,c,now=datetime.fromisoformat(r['freshness']['observed_at'].replace('Z','+00:00')))
            gate.need(capture['state']=='ACKNOWLEDGED' and capture['command']==c and capture['result']==r,'transport_result_disagrees')
            events=[row['event'] for row in capture['events'] if type(row['event']) is dict]
            stages=[row['stage'] for e in events if e['kind']=='DIAGNOSTIC' for row in e['records']]
            gate.need('WORKER_ACK' in stages and not any(e['kind']=='RESULT_REJECTED' for e in events),'missing_worker_ack')
            gate.need(stages.count('NATIVE_INVOKE')==1,'duplicate_native_invocation')
            net=r['result']['network'];total+=len(net)
            gate.need(all(n['method']=='GET' and n['status']==200 and n['session_header_present'] for n in net),'non_authenticated_read')
        if name=='metadata-smoke-02':
            net=s['operations'][1]['response']['result']['network']
            gate.need(len(net)==2 and net[1]['path']==METADATA_PATH and net[1]['query']['defIds']==[50573369]*21,'metadata_fanout_not_live_proven')
            gate.need(len(s['operations'][1]['response']['result']['auctions'])==21,'missing_native_rows')
        for relative,digest in s['preserved_checkpoints'].items():
            gate.need(hashlib.sha256((gate.ROOT/relative).read_bytes()).hexdigest()==digest,'historical_checkpoint_changed')
    outcome=gate.require_pass(gate.SIXTH_CHECKPOINT)
    gate.need(gate.selected_checkpoint()==gate.SIXTH_CHECKPOINT,'latest_checkpoint_not_selected')
    s=json.loads(gate.SIXTH_CHECKPOINT.read_text(encoding='utf8'))
    captures=json.loads((gate.SIXTH_CHECKPOINT.parent/'transport.json').read_text(encoding='utf8'))
    private_fields(captures)
    gate.need(len(captures)==len(s['operations']),'gate_transport_missing')
    for entry,capture in zip(s['operations'],captures):
        gate.need(capture['state']=='ACKNOWLEDGED' and capture['command']==entry['command'] and
            capture['result']==entry['response'],'gate_transport_disagrees')
    restart=json.loads((gate.SIXTH_CHECKPOINT.parent/'restart-readback.json').read_text(encoding='utf8'))
    gate.need(restart['decision_matches'] is True and restart['bid_commands']==0 and restart['ttl_seconds']==86400 and
        restart['cache_payload']['completed'] is True and restart['cache_resale']==s['uncached_quote']['resale_price'] and
        restart['context']==s['context'] and restart['definition_id']==s['candidate']['item']['definition_id'],'restart_evidence_mismatch')
    return dict(status='PASS',repair_probe_EA_GETs=total,metadata_fanout='LIVE_VERIFIED',gate=outcome)


if __name__=='__main__':print(json.dumps(validate()))

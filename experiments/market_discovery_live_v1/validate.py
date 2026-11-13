"""Independent read-only evidence audit; partial integrity is not completion."""
import argparse
import hashlib
import json
from pathlib import Path

from experiments.market_discovery.model import PROTOCOL, TIMINGS, reply, search, stamp
from experiments.market_discovery_followup_v1.server import persona_projection


from fc_access.evidence import evidence_hashes

def validate(directory):
    directory = Path(directory)
    errors, incomplete = [], []
    entry = json.loads((directory/'entry.json').read_text())
    frozen = json.loads(PROTOCOL.read_text())
    if entry['protocol_sha256'] != hashlib.sha256(PROTOCOL.read_bytes()).hexdigest():
        errors.append('frozen_protocol_hash_changed')
    for path, digest in evidence_hashes(entry['capture_source_hashes']).items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            errors.append('capture_source_changed:'+path)
    preflight = json.loads((directory/'preflight.json').read_text())
    reply(preflight['reply'])
    if preflight['status'] != 'PASS' or not persona_projection(preflight['persona']['projection'])['accepted']:
        errors.append('preflight_pc_validation_failed')
    if not any(n['path']=='/ut/game/fc27/transfermarket' and n['status']==200 and n['session_header_present']
               for n in preflight['reply']['result']['network']):
        errors.append('preflight_authenticated_200_missing')
    run = json.loads((directory/'observations.json').read_text())
    raw = [json.loads(line) for line in (directory/'records.jsonl').read_text().splitlines()]
    if run['mode'] != 'LIVE_READ_ONLY' or entry['mode'] != 'LIVE_READ_ONLY':
        errors.append('not_live_lineage')
    if run['account_mutations'] != 0:
        errors.append('account_mutations_out_of_scope')
    if len(raw) != len(run['records']):
        errors.append('raw_record_count_mismatch')
    total, by_strategy, by_window = 0, dict.fromkeys('ABC',0), {}
    previous = None
    stable = ('strategy','window','slot','criteria','submitted_utc','completed_utc','result','command_id','scheduled_utc')
    for index, record in enumerate(run['records']):
        if index < len(raw) and any(raw[index].get(k) != record.get(k) for k in stable):
            errors.append('raw_record_mismatch')
        if record['mode'] != 'LIVE_READ_ONLY' or record['game'] != 'fc27' or record['platform'] != 'pc':
            errors.append('record_market_or_lineage_mismatch')
        search(record['criteria'])
        reply({'result':record['result'],'timing':{k:record['timing'].get(k) for k in TIMINGS}})
        if record['strategy'] != frozen['timing']['order'][record['window']]:
            errors.append('wrong_strategy_order')
        if stamp(record['completed_utc']) < stamp(record['submitted_utc']):
            errors.append('reversed_read_time')
        offset = record['submitted_monotonic_offset_seconds']
        due = record['window']*300+record['slot']*30
        if not due-.05 <= offset <= due+1.1:
            errors.append('slot_accelerated_or_missed_slot_caught_up')
        if previous is not None and offset-previous < 29:
            errors.append('command_submission_schedule_too_close')
        previous = offset
        count = len(record['result']['network'])
        total += count
        by_strategy[record['strategy']] += count
        by_window[record['window']] = by_window.get(record['window'],0)+count
        if record['network_fresh'] and not any(n['path']=='/ut/game/fc27/transfermarket' and
                n['status']==200 and n['session_header_present'] for n in record['result']['network']):
            errors.append('fresh_authenticated_market_evidence_missing')
        for row in record['result']['auctions'] or []:
            if any(row['item'][k] != record['criteria'][k] for k in ('definition_id','club','league') if k in record['criteria']):
                errors.append('filter_identity_mismatch')
    if total > 72 or any(n>24 for n in by_strategy.values()) or any(n>8 for n in by_window.values()):
        errors.append('actual_EA_budget_exceeded')
    if run['protocol_completion'] != 'COMPLETED_NINE_WINDOWS' or run['stop_reason']:
        incomplete.append('finite_benchmark_stopped_before_completion')
    complete = [w for w in run['window_intervals'] if w['completed']]
    if len(complete) != 9 or [w['strategy'] for w in complete] != frozen['timing']['order']:
        incomplete.append('nine_completed_windows_missing')
    if len(complete)==9 and any(w['observed_seconds'] != 300 for w in complete):
        errors.append('incorrect_window_duration')
    if run['observation_interval']['monotonic_seconds'] < 2700:
        incomplete.append('2700_observation_seconds_not_obtained')
    if any(by_strategy[s] != 24 for s in 'ABC'):
        incomplete.append('matched_24_request_strategy_budgets_not_obtained')
    return {'integrity_status':'FAIL' if errors else 'PASS',
            'benchmark_completion':'BLOCKED' if incomplete else 'COMPLETED',
            'integrity_errors':sorted(set(errors)), 'completion_gaps':sorted(set(incomplete)),
            'completed_windows':len(complete), 'actual_EA_requests':total,
            'actual_EA_requests_by_strategy':by_strategy, 'account_mutations':run['account_mutations'],
            'pacing_proof':'Unchanged verified native 30-second guard plus protocol command-slot schedule; direct EA submission timestamps are not exposed',
            'scope':'Sanitized observations, not cryptographic proof; partial integrity PASS is not a completed comparison.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    result=validate(args.run_dir)
    print(json.dumps(result))
    return int(result['integrity_status']!='PASS' or result['benchmark_completion']!='COMPLETED')


if __name__=='__main__':
    raise SystemExit(main())

"""One-time capture of final 004-02 evidence index and stopped-process projection."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from baseline_00401 import processes
from check_00402_artifacts import window,successful

OUT=ROOT/'docs/research/004/004-02'


def write(name,value):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2);f.write('\n')


def main():
    if any((OUT/p).exists() for p in ['cleanup.json','verification.json','sealed-evidence.json']):
        raise FileExistsError('final_evidence_index_already_captured')
    windows=[];selected=None;actual=0;reserved=0
    for path in sorted(OUT.glob('status-array-*')):
        result,responses,_=window(path)
        actual+=sum(len(e['response']['network']) for e in responses);reserved+=result['reserved_requests']
        windows.append(dict(window=path.name,status=result['status'],reserved_requests=result['reserved_requests'],limitation=result.get('limitation')))
        if result['status']=='LIVE_VERIFIED_WITH_ACTUAL_LIMIT':successful(result,responses);selected=path.name
    if selected!='status-array-05':raise ValueError('final_live_retest_required')
    offline=json.loads((OUT/'offline-02/results.json').read_text())
    if len(offline['results'])!=38 or any(r['exit'] for r in offline['results']):raise ValueError('offline_regression_failed')
    write('cleanup.json',dict(at=datetime.now(timezone.utc).isoformat(),processes=processes(),
        original_service='absent',final_service='absent',temporary_services_stopped=[w['window'] for w in windows],
        controllers_launched=0,legacy_actors_launched=0,live_account_mutations=0))
    contracts=[
      dict(criterion=0,offline_evidence='controller_native_checks.cjs executes shipped page plus captured official DAO: ten DTOs, one invocation, one exact GET, no discovery confirmation',
           live_evidence_or_limitation='status-array-04 and status-array-05 each requested ten genuine retained targets in one authenticated status/lite GET; ten returned, zero omitted'),
      dict(criterion=1,offline_evidence='test_00402_controller.py tests wrong selectors/pairs, duplicates, missing rows, malformed versions, full-evidence conflicts, original-lite preservation, DTO and epoch links',
           live_evidence_or_limitation='Each successful window retained nineteen full watched rows, requested ten, preserved ten native version-0 responses and explicit full-read/current-DTO links; live null/malformed/omission branches did not occur'),
      dict(criterion=2,offline_evidence='Actual SQLite admission plus actual HTTP mutation delivery: authenticated entry/inventory, immutable decisions, failed persistence, strict schemas/scope, claimed tombstones, restart and disguised duplicate refusal',
           live_evidence_or_limitation='All live services were constructed read-only; no live mutation was permitted by this task. New authority mutation effects remain offline-verified only; pricing and full policy composition belong to later tasks'),
      dict(criterion=3,offline_evidence='Actual queue/request/XHR hooks distinguish async owned requests from same-URL background traffic; zero-owned/mismatched requests cannot confirm; actual receipts and independent confirmation remain separate',
           live_evidence_or_limitation='Both successful probes captured exactly three owned authenticated GETs through the actual native queue. No manual/background interleaving occurred; live concurrent attribution remains untested'),
      dict(criterion=4,offline_evidence='Actual page restoration after success/rejection/timeout/interruption, delayed sends and late callbacks; next command succeeds. SQLite uncertainties, duplicates and expired intents do not gate later targets. Legacy worker/page/receipt contracts pass',
           live_evidence_or_limitation='Success cleanup and three sequential commands occurred in each successful window; no induced live timeout or mutation uncertainty, so those branches are synthetic only'),
      dict(criterion=5,offline_evidence='12 Python tests execute shipped Node page/official source-backed DAO, strict parser/adapter/store/real loopback HTTP and actual worker callbacks; offline-02 contains 38 passing independent regression commands including every current Node checks suite',
           live_evidence_or_limitation='Fixtures are explicitly OFFLINE and are never represented as live proof'),
      dict(criterion=6,offline_evidence='check_00402_artifacts.py independently parses captured envelopes, exact pairs, statuses/counts/omissions, full-version linkage, budget recipes and independent watched comparisons; negative artifact cases reject manufactured proof',
           live_evidence_or_limitation='Verified official Edge control and designated saved zzorniss selection; final authenticated three-GET window exercised ten real targets, all closed/outbid, all returned version 0, no omissions, no market search, no raw IDs/secrets retained'),
      dict(criterion=7,offline_evidence='Exclusive window creation, fsynced reservation-before-delivery checkpoints, immutable evidence seals, restart/no-replay tests and independent stopped-process projection',
           live_evidence_or_limitation='All five windows are retained. 01 closed unattached; 02/03 were blocked before EA traffic by the erroneous persona-display-name guard. That defect was repaired and windows 04/05 passed separately. Six actual EA GETs total, eight conservatively reserved requests, zero mutations; all temporary services stopped')
    ]
    write('verification.json',dict(schema=1,task='004-02',status='DONE_WITH_EXPLICIT_LIVE_LIMITS',selected_window=selected,
        windows=windows,total_actual_EA_GETs=actual,total_reserved_requests=reserved,total_mutations=0,
        offline_results='offline-02/results.json',contracts=contracts))
    paths=[p for w in windows for p in (OUT/w['window']).iterdir() if p.name in {'checkpoint.jsonl','result.json','transport.sqlite'}]
    write('sealed-evidence.json',dict(schema=1,scope='Captured immutable finite read-only experiment evidence only; never mutable implementation bytes',
        sha256={p.relative_to(OUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))
    print(json.dumps(dict(selected_window=selected,actual_EA_GETs=actual,reserved_requests=reserved,mutations=0)))


if __name__=='__main__':main()

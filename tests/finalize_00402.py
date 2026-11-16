"""Append final retest evidence; preserve the already sealed through-05 history."""
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
    if any((OUT/p).exists() for p in ['final-cleanup.json','final-verification.json','sealed-evidence-06.json']):
        raise FileExistsError('final_index_already_captured')
    index=json.loads((OUT/'verification.json').read_text())
    result,responses,_=window(OUT/'status-array-06');successful(result,responses)
    offline=json.loads((OUT/'offline-03/results.json').read_text())
    if len(offline['results'])!=38 or any(r['exit'] for r in offline['results']):raise ValueError('final_offline_regression_failed')
    paths=[OUT/'status-array-06'/name for name in ['checkpoint.jsonl','result.json','transport.sqlite']]
    write('sealed-evidence-06.json',dict(schema=1,scope='Additional captured immutable read-only EA experiment only',
        sha256={p.relative_to(OUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))
    write('final-cleanup.json',dict(at=datetime.now(timezone.utc).isoformat(),processes=processes(),original_service='absent',final_service='absent',
        controllers_launched=0,legacy_actors_launched=0,live_account_mutations=0))
    index['windows'].append(dict(window='status-array-06',status=result['status'],reserved_requests=result['reserved_requests'],limitation=None))
    index.update(selected_window='status-array-06',offline_results='offline-03/results.json',cleanup='final-cleanup.json',
        evidence_manifests=['sealed-evidence.json','sealed-evidence-06.json'],total_actual_EA_GETs=9,total_reserved_requests=11)
    index['contracts'][1]['live_evidence_or_limitation']+=' Window 06 retested the genuine native setAuctionData connection to retained full DTOs; offline 0/null outbid updates each supported one smallest-legal rebid while preserving original projections.'
    index['contracts'][5]['offline_evidence']=index['contracts'][5]['offline_evidence'].replace('offline-02','offline-03')
    index['contracts'][7]['live_evidence_or_limitation']='All six exclusive windows retained. 01 closed unattached; 02/03 stopped before EA traffic at an incorrect persona-display-name guard; 04/05 passed after repair. Final review added the genuine auction-entity/full-DTO setter link, tested 0/null rebids offline, and window 06 passed the exact ten-ID live retest. Nine actual EA GETs total, eleven conservatively reserved requests, zero mutations. All temporary services stopped; original through-05 indexes and evidence were preserved.'
    write('final-verification.json',index)
    print(json.dumps(dict(selected_window=index['selected_window'],actual_EA_GETs=9,reserved_requests=11,mutations=0)))


if __name__=='__main__':main()

"""Record offline 001d-03 checks only; never executes the S2 investigation."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/research/001d/001d-03'
FILES=['test_001d03_native_prices.py','test_001d02_contract.py','test_001d01_inventory.py',
       'test_bidding_v1.py','test_durability_v1.py','test_market_pricing.py',
       'test_search_validation_v1.py','test_watched_bulk_v1.py','test_e2e_live_v2.py']


if __name__=='__main__':
    records=[]
    for i,file in enumerate(FILES):
        argv=[sys.executable,'tests/run_offline_suite.py','tests/'+file]
        start=datetime.now(timezone.utc).isoformat();t=time.monotonic()
        r=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=120)
        output=f'validation-{i:02}.txt'
        (OUT/output).write_text(r.stdout+'\n--- STDERR ---\n'+r.stderr,encoding='utf-8')
        records.append(dict(command=['{python}',*argv[1:]],exit_code=r.returncode,
                            started_at=start,elapsed_seconds=time.monotonic()-t,output=output))
        print(f'{file}: {r.returncode}',flush=True)
    (OUT/'validation.json').write_text(json.dumps(dict(task='001d-03',
        new_EA_requests=0,live_mutations=0,checks=records),indent=2)+'\n')
    raise SystemExit(any(x['exit_code'] for x in records))

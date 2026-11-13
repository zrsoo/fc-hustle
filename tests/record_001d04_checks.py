"""Record finite offline checks in the new task's directory only."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/research/001d/001d-04'
FILES=['test_001d04_pricing.py','test_001d03_native_prices.py','test_001d02_contract.py',
       'test_001d01_inventory.py','test_bidding_v1.py','test_durability_v1.py',
       'test_market_pricing.py','test_search_validation_v1.py','test_watched_bulk_v1.py']


if __name__=='__main__':
    records=[]
    for i,file in enumerate(FILES):
        argv=([sys.executable,'tests/run_offline_suite.py','tests/'+file]
              if file=='test_watched_bulk_v1.py' else [sys.executable,'tests/'+file])
        at=datetime.now(timezone.utc).isoformat();start=time.monotonic()
        run=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=120)
        output=f'validation-{i:02}.txt'
        (OUT/output).write_text(run.stdout+'\n--- STDERR ---\n'+run.stderr,encoding='utf-8')
        records.append(dict(command=['{python}',*argv[1:]],exit_code=run.returncode,
                            started_at=at,elapsed_seconds=time.monotonic()-start,output=output))
        print(f'{file}: {run.returncode}',flush=True)
    (OUT/'validation.json').write_text(json.dumps(dict(task='001d-04',checks=records,
        new_EA_requests=0,live_mutations=0),indent=2)+'\n')
    raise SystemExit(any(r['exit_code'] for r in records))

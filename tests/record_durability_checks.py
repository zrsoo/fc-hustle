"""Record exact commands and outputs without altering historical checks."""
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'docs/research/001c/001c-05'
commands=[
    [sys.executable,'tests/test_durability_v1.py'],
    [sys.executable,'tests/test_readiness_regressions.py'],
    [sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'],
    ['git','diff','--check'],
]
if __name__=='__main__':
    records=[]
    for n,c in enumerate(commands):
        r=subprocess.run(c,cwd=ROOT,capture_output=True,text=True,timeout=120)
        output=r.stdout+r.stderr
        (D/f'check-{n}.txt').write_text(output,encoding='utf-8')
        records.append({'command':['{python}' if v==sys.executable else v for v in c],
            'returncode':r.returncode,'output':f'check-{n}.txt'})
        (D/'checks.json').write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'commands':records,
            'earlier_observations':['Initial standalone search rejection test and first combined watched-bulk rejection test each encountered WinError 10053; immediate standalone search rerun passed. Historical sources remain unchanged.']},indent=2)+'\n')
        print(json.dumps(records[-1]),flush=True)
    (D/'checks.json').write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'commands':records,
        'earlier_observations':[{'command':['{python}','tests/test_search_validation_v1.py'],
          'result':'One initial run errored with WinError 10053 in the existing rejection test; immediate independent rerun passed. Prior sources were preserved.'}]},indent=2)+'\n')

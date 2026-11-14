"""Seal already-collected experiment evidence; this command never contacts EA."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.final_assessment import audit
from fc_access.actors_v1.final_run import Evidence
from fc_access.production_v1.executor import EdgeExecutor


def main():
    out=ROOT/'docs/research/002/002-12'
    evidence=Evidence(out/'shutdown.jsonl')
    try:
        # This is localhost health only; no native EA operation is dispatched.
        h=EdgeExecutor().request('/health')
        if h['mutations_enabled']:raise ValueError('write_authority_still_enabled')
        result=subprocess.run(['powershell','-NoProfile','-Command',
            "@(Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^python(w)?\\.exe$' -and $_.CommandLine -match '-m fc_access.actors_v1'}).Count"],
            cwd=ROOT,capture_output=True,text=True,timeout=20)
        if result.returncode or result.stdout.strip()!='0':raise ValueError('actor_processes_not_stopped')
        evidence.append('READ_ONLY_SERVICE_RESTORED',service=h['service'],schema=h['schema'],
            attached=h['attached'],mutations_enabled=h['mutations_enabled'],native_requests=0)
        evidence.append('PROCESS_VERIFICATION',actor_or_maintenance_processes=0,
            method='Windows process inventory; exact actor module match',verified=True)
    finally:evidence.close()
    report=audit(out/'live-01')
    with (out/'outcome.json').open('x',encoding='utf8') as handle:json.dump(report,handle,indent=2);handle.write('\n')
    # Only sealed captured experiment logs/responses/backups are hashed.
    captures=sorted(out.glob('*.jsonl'))+sorted((out/'live-01').glob('*.jsonl'))+sorted((out/'live-01/state-backup').glob('*.sqlite3'))+[out/'regressions.json']
    index=dict(schema=1,kind='SEALED_EXPERIMENT_EVIDENCE',task='002-12',
        files=[dict(path=str(p.relative_to(ROOT)).replace('\\','/'),bytes=p.stat().st_size,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in captures])
    with (out/'evidence-index.json').open('x',encoding='utf8') as handle:json.dump(index,handle,indent=2);handle.write('\n')
    print(json.dumps(dict(status=report['status'],sealed_captures=len(captures),
        actual_native_requests=report['metrics']['actual_native_requests'],mutations=report['metrics']['mutations'])))


if __name__=='__main__':main()

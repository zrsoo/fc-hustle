"""Seal the stopped continuation series. Local reads only; no EA dispatch."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.final_run import Evidence
from fc_access.actors_v1.final_series import audit_series
from fc_access.actors_v1.operator import inspect,retain
from fc_access.production_v1.executor import EdgeExecutor


def actor_count():
    query="@(Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object {$_.CommandLine -match '-m fc_access\\.actors_v1'}).Count"
    r=subprocess.run(['powershell','-NoProfile','-Command',query],cwd=ROOT,capture_output=True,text=True,timeout=25)
    if r.returncode or not r.stdout.strip().isdigit():raise ValueError('process_verification_failed')
    return int(r.stdout.strip())


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--latest',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    health=EdgeExecutor().request('/health')
    if health['service']!='fc-production-v1' or health['mutations_enabled']:raise ValueError('read_only_service_required')
    if actor_count():raise ValueError('actors_still_running')
    box=ROOT/'private-captures/final-remediation/native.sqlite3'
    checkpoint=out/'checkpoint.jsonl';e=Evidence(checkpoint)
    try:
        e.append('DURABLE_EXPORT',data=inspect(box,'export'))
        e.append('STATUS_SNAPSHOT',data=inspect(box))
        e.append('READ_ONLY_SERVICE_RESTORED',service=health['service'],schema=health['schema'],
            attached=health['attached'],mutations_enabled=False,native_requests=0)
        e.append('PROCESS_VERIFICATION',actor_or_maintenance_processes=0,verified=True,
            method='Windows process inventory; exact actor module match')
        e.append('RUN_STOPPED',remaining_processes=[],verified_process_exit=True,native_mutations=0)
    finally:e.close()
    retain(box,out/'state-backup')
    src=sqlite3.connect((ROOT/'private-captures/002-bulk-transfer-operations/production-readonly-after.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    dst=sqlite3.connect(out/'state-backup/transport.sqlite3')
    try:src.backup(dst)
    finally:src.close();dst.close()
    report=audit_series(args.latest,checkpoint)
    regression=ROOT/'docs/research/002/002-12/remediation-05/regressions-final.json'
    task_checks=ROOT/'docs/research/002/002-12/remediation-05/regressions-task-final.json'
    from check_00211_artifacts import regression_check
    offline=json.loads(regression.read_text());regression_check(offline)
    checks=json.loads(task_checks.read_text())
    if checks['status']!='PASS' or not all(r['exit_code']==0 and r['python_tests']>0 for r in checks['checks']):
        raise ValueError('final_task_offline_checks_failed')
    report['offline_current_checks']=dict(regression=str(regression.relative_to(ROOT)).replace('\\','/'),
        regression_python_tests=sum(r['python_tests'] for r in offline['checks']),
        regression_node_checks=sum(r['command'][0]=='node' for r in offline['checks']),
        task_checks=str(task_checks.relative_to(ROOT)).replace('\\','/'),
        task_python_tests=sum(r['python_tests'] for r in checks['checks']))
    with (out/'outcome.json').open('x',encoding='utf8') as f:json.dump(report,f,indent=2);f.write('\n')
    relative=lambda path:str(Path(path).resolve().relative_to(ROOT)).replace('\\','/')
    experiment=ROOT/'docs/research/002/002-12'
    captures=sorted(experiment.rglob('*.jsonl'))+sorted(experiment.rglob('*.sqlite3'))+sorted(experiment.rglob('regressions*.json'))
    index=dict(schema=1,kind='SEALED_EXPERIMENT_EVIDENCE',task='002-12',
        files=[dict(path=relative(path),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in captures])
    with (out/'evidence-index.json').open('x',encoding='utf8') as f:json.dump(index,f,indent=2);f.write('\n')
    selection=dict(schema=1,latest=relative(args.latest),checkpoint=relative(checkpoint),outcome=relative(out/'outcome.json'),
        evidence_index=relative(out/'evidence-index.json'))
    # This is a mutable selector, never sealed or source-hash checked. Earlier
    # reports/checkpoints remain immutable when a corrected review is appended.
    (experiment/'series-selection.json').write_text(json.dumps(selection,indent=2)+'\n',encoding='utf8')
    lines=['# Item 12 continuation review','',report['status'],'',
        'The original run and every stopped continuation remain sealed. No completed window, request budget or ambiguous mutation was replayed.',
        '', 'Repairs verified native page stride 20 with a 21-row lookahead, separate fresh-read rebids, exact independent owned-item lookup, and complete inactive-pile counting.',
        '', 'Actual native evidence includes minimum bids, fresh pricing, leading HOLD, naturally active outbids and minimum rebids, terminal LOST, exact WON ownership and paid cost 1200. The acquired physical card was moved once and listed at the stored 2000 BIN, native previous tick 1900, for an independently observed hour.',
        '', 'The listing callback failed closed on auxiliary network traffic. An independent later complete native read proved the listing effect; the original command was reconciled without retry. This callback failure remains in the report.',
        '', 'A scheduled one-call bulk relist reached EA once and the two naturally expired manual entries independently returned active at unchanged prices with expiry anchored to 3600 seconds. The callback reported bulk_contract_changed; its durable UNKNOWN/incompatible flag remains sticky. Actual readback evidence does not clear that runtime safety fence.',
        '', 'Further live execution is blocked by that unresolved bulk intent. No bulk flag was cleared and no sale, timer reset, capacity saturation or settlement was manufactured. Full live PASS remains unavailable.',
        '', 'Missing live evidence:']
    lines += [f'- LIVE-UNVERIFIED: {name}: {reason}' for name,reason in report['unverified'].items()]
    lines += ['',f"Active process time across {len(report['windows'])} windows: {report['metrics']['active_seconds']:.3f} seconds. Elapsed time including stopped recovery is separately reported. This was a series of explicitly resumed windows, not an uninterrupted run.",
        '', 'Whole-queue intervals, queue wait, native fanout, deadline misses, enrolled status observations and all native failures are retained in outcome.json. Historical component captures and offline doubles do not count as integrated native evidence.',
        '', 'All actor, maintenance and broker processes stopped. Local service restored with no mutation authority. The journal, mailbox, quote cache and transport were retained without pruning. The unexecuted ghost reservation from item 3 remains conservative and is excluded from real enrollment coverage.',
        '', f"Validation: {report['offline_current_checks']['regression_python_tests']} offline regression tests, {report['offline_current_checks']['regression_node_checks']} Node checks, and {report['offline_current_checks']['task_python_tests']} task behavior/artifact tests passed. The strict series acceptance validator exits nonzero while any named live evidence is missing."]
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(dict(status=report['status'],metrics={k:v for k,v in report['metrics'].items() if k not in {'per_window','independent_recovery_reads'}},
        missing=list(report['unverified']),sealed_captures=len(captures))))


if __name__=='__main__':main()

"""Independent offline acceptance receipts and Git publication checks for 003-02.

No EA calls, actors, mutable source hashes or reinterpretation of live evidence.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT = ROOT/'docs/research/003/003-02'
from run_00302_suites import INDEPENDENT

MODULES = {
    0: ['test_00302_continuous', 'test_00301_baseline', 'test_final_run_00212'],
    1: ['test_00302_continuous', 'test_00204_actors'],
    2: ['test_001d04_pricing', 'test_00202_pricing_optimization'],
    3: ['test_00204_actors', 'test_00205_occupancy', 'test_00206_capacity', 'test_00207_enrollment'],
    4: ['test_00208_resale', 'test_00209_bulk', 'test_00210_relist', 'test_00211_sold'],
    5: ['test_00302_continuous', 'test_001d06_foundation', 'test_00204_actors'],
    6: ['test_00302_continuous'],
    7: ['test_00302_continuous', 'test_bulk_blocker_recovery', 'test_final_list_refresh_00212'],
}
PUBLICATION_PATHS = [
    'fc_access/actors_v1/native.py', 'fc_access/production_v1/server.py',
    *['fc_access/continuous_v1/'+name for name in ['__init__.py','__main__.py','control.py','runtime.py','recovery.py','watchdog.py']],
    'tests/test_00302_continuous.py','tests/continuous_fixture.py','tests/run_00302_suites.py',
    'tests/check_00302_production.py','tests/test_00302_validator.py',
    'docs/continuous-production.md','docs/research/003/003-02/REPORT.md',
]


def need(value, reason):
    if not value: raise ValueError(reason)


def validate_receipt(group, value, read):
    need(value['task']=='003-02' and value['evidence_class']=='OFFLINE_REGRESSIONS_ONLY' and value['group']==group,
         'receipt_scope_mismatch')
    rows = value['results']
    expected = ([['{python}','-m','unittest','discover','-s','tests','-v']] if group=='python' else
        [['node',p.relative_to(ROOT).as_posix()] for p in sorted((ROOT/'tests').glob('*checks.cjs'))] if group=='node' else
        [['{python}',*cmd] for cmd in INDEPENDENT])
    need([r['command'] for r in rows]==expected, 'incomplete_or_wrong_suite_inventory')
    need(value['status']=='PASS' and all(r['exit_code']==0 for r in rows), 'suite_failed')
    output = []
    for row in rows:
        stdout, stderr = read(row['stdout']), read(row['stderr'])
        need(row['elapsed_seconds'] > 0 and row['finished'], 'execution_receipt_missing')
        if group=='python':
            summary = re.search(r'Ran (\d+) tests in [\d.]+s',stderr)
            need(summary and int(summary[1])==row['tests_run'] and row['tests_run']>=799 and
                 stderr.rstrip().endswith('\nOK') and 'FAILED (' not in stderr, 'python_completion_not_proven')
            need(not re.search(r'\) \.\.\. skipped\b', stderr), 'suite_skips_unreviewed')
            output.append(stderr)
        else:
            need(stdout.strip() and not stderr.strip(), 'suite_output_missing_or_error')
            output.append(stdout)
    return '\n'.join(output)


def receipt(group):
    return validate_receipt(group, json.loads((OUT/(group+'-suites.json')).read_text(encoding='utf8')),
                            lambda name: (OUT/name).read_text(encoding='utf8'))


def behavioral_receipts(index, log):
    for module in MODULES[index]:
        passed = re.findall(r'^test_\S+ \(' + re.escape(module) + r'\.[^\n]+\) \.\.\. ok$', log, re.M)
        need(len(passed)>=1, 'behavioral_module_not_verified:'+module)


def git(*args):
    r = subprocess.run(['git',*args],cwd=ROOT,text=True,capture_output=True,timeout=45)
    need(r.returncode==0, 'git_publication_check_failed')
    return r.stdout.strip()


def publication():
    tracked = set(git('ls-files','--',*PUBLICATION_PATHS).splitlines())
    need(tracked==set(PUBLICATION_PATHS), 'required_implementation_not_committed')
    need(not git('status','--porcelain','--',*PUBLICATION_PATHS), 'reviewed_paths_have_uncommitted_changes')
    need(git('branch','--show-current')=='main', 'production_review_not_on_main')
    remote = git('ls-remote','origin','refs/heads/main').split()[0]
    git('merge-base','--is-ancestor',git('rev-parse','HEAD'),remote)
    for path in PUBLICATION_PATHS:
        need(git('log','-1','--format=%H','--',path), 'committed_change_missing:'+path)
    return dict(published_head=git('rev-parse','HEAD'), remote_main=remote)


def documentation():
    doc = (ROOT/'docs/continuous-production.md').read_text(encoding='utf8')
    for term in ('fc_access.continuous_v1',' run ',' recover ',' status',' stop','5000','3660','86400',
                 '600','25','1000','11000','3600','two seconds','SUPERVISION_GAP','read-only','LIVE-UNVERIFIED',
                 'intent-database','foundation.sqlite3','monitor','CAPTCHA'):
        need(term in doc, 'operator_contract_missing:'+term)
    report = (OUT/'REPORT.md').read_text(encoding='utf8')
    for term in ('OFFLINE','LIVE-UNVERIFIED','2005','20','PARTIAL','ghost','commit','push'):
        need(term in report,'review_missing:'+term)
    from fc_access.continuous_v1.runtime import production_config
    need(production_config().discovery_max_pages==3, 'production_discovery_default_changed')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepublication',action='store_true')
    args=p.parse_args()
    results=[]
    try:
        log=receipt('python')
        for index in range(8):
            behavioral_receipts(index,log)
            results.append(dict(criterion=index,status='PASS'))
        receipt('node'); receipt('independent')
        results.append(dict(criterion=8,status='PASS'))
        documentation()
        pub = {} if args.prepublication else publication()
        results.append(dict(criterion=9,status='PUBLICATION_PENDING' if args.prepublication else 'PASS',**pub))
    except Exception as e:
        print(json.dumps(dict(status='FAIL',task='003-02',results=results,diagnostic=str(e))))
        return 1
    print(json.dumps(dict(status='REVIEW_READY' if args.prepublication else 'PASS',task='003-02',
                         evidence_class='OFFLINE_ONLY_NO_LIVE_LAUNCH',results=results)))
    return 0


if __name__=='__main__': raise SystemExit(main())

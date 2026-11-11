"""T7 offline audit helpers. No live access, account writes or evidence refresh."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from final_audit import privacy_findings
from test_001b_scope import preservation_defects

AUDIT = 'docs/research/001b/t7/'
DOCS = tuple('docs/research/001b-' + n + '.md' for n in (
    'price-providers', 'discovery-benchmarks', 'latency', 'proposed-flow',
    'obj002-addendum', 'discovery-decision', 'scope', 't3-harness', 't4-live-experiments'))
TESTS = tuple('tests/' + n for n in (
    'market_discovery_bridge_checks.cjs', 'test_001b_price_providers.py', 'test_001b_scope.py',
    'test_market_discovery_artifacts.py', 'test_market_discovery_harness.py',
    'test_market_discovery_transport.py', 'test_t4_live_evidence.py', 'test_t5_pricing.py',
    'test_t5_pricing_artifacts.py', 'test_t6_discovery_recommendation.py',
    'audit_001b.py', 'record_001b_checks.py', 'test_t7_audit.py', 'validate_001b.py'))
PREFIXES = ('docs/research/001b/', 'experiments/market_discovery/',
            'experiments/price_provider_research/')
MANIFEST = AUDIT + 'manifest.json'
SUMMARY = AUDIT + 'checks-verified/validation.json'
ENTRY = AUDIT + 'entry.json'
SUITE = ['{python}', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py']
REPLAYS = {
    'demo': ['{python}', '-m', 'experiments.market_discovery', 'demo'],
    'replay': ['{python}', '-m', 'experiments.market_discovery', 'replay'],
    'flow-demo': ['{python}', '-m', 'experiments.market_discovery', 'flow-demo'],
    't4': ['{python}', '-m', 'experiments.market_discovery.t4_evidence'],
    't5': ['{python}', '-m', 'experiments.market_discovery.t5_pricing'],
    't6': ['{python}', '-m', 'experiments.market_discovery.t6_analysis'],
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, stderr=subprocess.PIPE)


def in_scope(name):
    path = Path(name)
    return (not path.is_absolute() and '..' not in path.parts and '\\' not in name
            and (name in DOCS or name in TESTS or name.startswith(PREFIXES))
            and '__pycache__' not in path.parts
            and path.suffix not in ('.pyc', '.tmp', '.lock'))


def scoped_files():
    files = set(DOCS + TESTS)
    for directory in PREFIXES:
        files.update(p.relative_to(ROOT).as_posix() for p in (ROOT/directory).rglob('*')
                     if p.is_file() and in_scope(p.relative_to(ROOT).as_posix()))
    return sorted(files)


def privacy(name, text):
    # Schema property definitions are contracts, not captured item/trade values.
    # Scan their literal text for secrets; instance schemas are exercised by T3.
    scan_name = name + '.txt' if name.endswith('.schema.json') else name
    findings = privacy_findings(scan_name, text)
    if name.endswith('.json') and not name.endswith('.schema.json'):
        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = key.lower().replace('-', '_')
                    schema_auth = normalized == 'apikey' and (child == [] or child == {
                        'type': 'apiKey', 'description': 'Please enter token',
                        'name': 'X-AUTH-TOKEN', 'in': 'header'})
                    if normalized in {'token', 'api_key', 'apikey', 'client_secret', 'secret',
                                      'x_ut_sid', 'x_ut_phishing_token', 'set_cookie'} and child not in (None, False, '') and not schema_auth:
                        findings.append(name + ':private_json_field')
                    if key == 'evidence_key' and child not in (None, False, ''):
                        findings.append(name + ':exported_correlation_key')
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(json.loads(text))
    return sorted(set(findings))


def link_defects(name, text):
    errors = []
    for link in re.findall(r'\]\(([^)]+)\)', text):
        if link.startswith(('https://', 'http://', '#')):
            continue
        target = ((ROOT/name).parent/link.split('#')[0]).resolve()
        if not target.is_relative_to(ROOT) or not target.is_file():
            errors.append(name + ':broken_local_link')
    return errors


def mutation_defects(value):
    errors = []
    def walk(v, boundary=False):
        if isinstance(v, dict):
            if ('account_mutations' in v and not (boundary and v['account_mutations'] is False)
                    and (type(v['account_mutations']) is not int or v['account_mutations'] != 0)):
                errors.append('nonzero_or_invalid_account_mutations')
            if 'buy_intent' in v and v['buy_intent'] is not None:
                intent = v['buy_intent']
                if intent.get('mode') != 'DRY_RUN_ONLY' or intent.get('lineage') != 'SIMULATED':
                    errors.append('unsafe_buy_intent')
            for key, child in v.items():
                walk(child, boundary=key == 'boundary')
        elif isinstance(v, list):
            for child in v:
                walk(child)
    walk(value)
    return sorted(set(errors))


def validation_inputs():
    # Bind the recorded run to the exact code/evidence tested. Audit command
    # records and their manifest are outputs, excluded to avoid a hash cycle.
    return {name: digest((ROOT/name).read_bytes()) for name in scoped_files()
            if not name.startswith(AUDIT) or name in (ENTRY, AUDIT+'audit.md')}


def lineage_defects(report=None):
    # These checks recompute claims from underlying rows/HTTP observations;
    # matching an integrity hash alone is insufficient.
    from test_001b_price_providers import load_bundle, semantic_defects
    from test_t6_discovery_recommendation import docs, defects
    from experiments.market_discovery.t4_evidence import build_blocker_report, RUN
    from experiments.market_discovery.t6_analysis import OUTPUT
    errors = []
    if any(semantic_defects(load_bundle()).values()):
        errors.append('provider_claims_disagree_with_evidence')
    if defects(docs(), report if report is not None else json.loads(OUTPUT.read_bytes())):
        errors.append('discovery_latency_or_yield_claims_disagree_with_evidence')
    if build_blocker_report(ROOT/RUN) != load((RUN/'report.json').as_posix()):
        errors.append('live_blocker_report_disagrees_with_raw_preflights')
    return errors


def replay_result(key, value):
    """Verify new CLI output semantically; variable local timing stays unpinned."""
    base = 'experiments/market_discovery/runs/'
    if key == 'demo':
        from experiments.market_discovery.discovery import metrics, pagination
        from test_market_discovery_artifacts import check_schema
        contract = load('experiments/market_discovery/observation.schema.json')
        assert value['mode'] == 'SIMULATED' and value['account_mutations'] == 0
        assert len(value['records']) == 72 and value['overall'] == metrics(value['records'])
        assert value['live_opportunity_yield'] is None
        assert [w['strategy'] for w in value['windows']] == list('ABCBCACAB')
        for record in value['records']:
            check_schema(record, contract)
        for strategy in 'ABC':
            records = [r for r in value['records'] if r['strategy'] == strategy]
            assert len(records) == 24 and value['by_strategy'][strategy] == metrics(records)
        for window in value['windows']:
            records = [r for r in value['records'] if r['window'] == window['window']]
            assert window['metrics'] == metrics(records)
            assert window['pagination'] == pagination(records)
            assert window['budget']['requests'] == 8
        return {'mode': value['mode'], 'simulated_requests': len(value['records']), 'live_requests': 0}
    if key == 'replay':
        assert value == load(base+'t3-harness/historical.json')
        return {'mode': value['mode'], 'unique_auctions': value['overall']['unique_auctions'], 'new_live_samples': 0}
    if key == 'flow-demo':
        from test_market_discovery_artifacts import check_schema
        contract = load('experiments/market_discovery/observation.schema.json')
        for record in value['records']:
            check_schema(record, contract)
        intent = value['flow']['intent']
        assert value['mode'] == intent['lineage'] == 'SIMULATED'
        assert value['account_mutations'] == value['EA_live_requests'] == 0
        assert intent['mode'] == 'DRY_RUN_ONLY'
        assert intent['expected_profit'] == intent['target_sale_price']-intent['target_sale_price']//20-intent['buy_now_price']
        assert intent['expected_profit'] >= intent['X']
        assert value['budget']['requests'] == len(value['records']) == 2
        return {'mode': value['mode'], 'state': value['flow']['state'], 'reads': 2, 'live_requests': 0}
    if key == 't4':
        assert value == load(base+'t4-live-20261111T220200Z/report.json')
        return {'status': value['status'], 'authenticated_observation_seconds': 0, 'live_yield': None}
    if key == 't5':
        from test_t5_pricing_artifacts import semantic
        assert semantic(value) == semantic(load(base+'t5-pricing/report.json'))
        return {'mode': value['demonstration']['mode'], 'prepared_fixture_intents': 4, 'live_yield': None}
    if key == 't6':
        assert value == load(base+'t6-analysis/report.json')
        return {'status': value['status'], 'decision': value['decision'], 'live_yield': None}
    raise ValueError('unknown_replay')


def record_defects(summary):
    errors = []
    expected = {'suite': SUITE, **{key: argv + ['--output', '{output}'] for key, argv in REPLAYS.items()}}
    checks = summary.get('checks', [])
    if [c.get('key') for c in checks] != list(expected):
        return ['missing_or_duplicate_command_records']
    for check in checks:
        if check.get('command') != expected[check['key']] or check.get('exit_code') != 0:
            errors.append('failed_or_unrecognized_command:' + check['key'])
        for field in ('started_utc', 'ended_utc'):
            stamp = datetime.fromisoformat(check[field])
            if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
                errors.append('invalid_command_UTC')
        if check['ended_utc'] < check['started_utc']:
            errors.append('reversed_command_times')
        if not re.fullmatch('[0-9a-f]{64}', check.get('output_sha256', '')):
            errors.append('missing_output_digest')
        if check['key'] == 'suite':
            if check.get('tests_run', 0) < 168 or check.get('skipped_tests') is not False:
                errors.append('missing_tests_or_skips')
        elif not check.get('artifact_checks'):
            errors.append('missing_replay_artifact_check')
    if summary.get('status') != 'PASS' or summary.get('new_live_requests') != 0 or summary.get('account_mutations') != 0:
        errors.append('invalid_validation_scope_or_outcome')
    return errors


def commit_defects(baseline, files, read_git=git, read_bytes=None):
    read_bytes = read_bytes or (lambda name: (ROOT/name).read_bytes())
    errors = []
    read_git('merge-base', '--is-ancestor', baseline, 'HEAD')
    changed = read_git('diff', '--name-only', baseline, 'HEAD').decode().splitlines()
    if not changed or any(not in_scope(name) for name in changed):
        errors.append('missing_scoped_commit_or_unrelated_changes')
    for name in files:
        if read_git('show', 'HEAD:' + name) != read_bytes(name):
            errors.append('uncommitted_deliverable:' + name)
    return errors


def validate(require_commit=True):
    errors = {i: [] for i in range(5)}
    manifest = load(MANIFEST)
    names = scoped_files()
    expected = set(names) - {MANIFEST}
    pins = manifest['sha256']
    if set(pins) != expected:
        errors[1].append('manifest_missing_or_extra_files')
    for name in names:
        path = ROOT/name
        if not in_scope(name) or not path.is_file() or path.is_symlink():
            errors[1].append('missing_or_unsafe_file:' + name)
            continue
        if name != MANIFEST and pins.get(name) != digest(path.read_bytes()):
            errors[1].append('changed_artifact:' + name)
        text = path.read_text(encoding='utf-8')
        errors[3].extend(privacy(name, text))
        if path.suffix == '.md':
            errors[1].extend(link_defects(name, text))
        if path.suffix == '.json':
            errors[3].extend(mutation_defects(json.loads(text)))
    readme = (ROOT/'experiments/market_discovery/README.md').read_text(encoding='utf-8')
    audit_doc = AUDIT+'audit.md'
    for name in DOCS[:5] + ('experiments/market_discovery/fixtures/t5-opportunities.json',
                            'experiments/market_discovery/observation.schema.json',
                            'experiments/market_discovery/runs/t6-analysis/report.json', audit_doc):
        if name not in expected or (ROOT/name).stat().st_size < 50:
            errors[1].append('required_artifact_absent:' + name)
    for term in ('Python 3.10+', 'Node 22+', 'FC27', 'PC', '30 seconds', 'long_poll', 'alarm_30s'):
        if term not in readme:
            errors[0].append('missing_live_prerequisite:' + term)
    errors[0].extend(record_defects(load(SUMMARY)))
    if load(SUMMARY).get('inputs_sha256') != validation_inputs():
        errors[0].append('command_record_inputs_changed_since_execution')
    errors[2].extend(lineage_defects())
    lock = load('docs/research/001b/preservation.json')
    errors[3].extend(preservation_defects(lock, lambda name: (ROOT/name).read_bytes()))
    # Audit the untouched Objective 001 artifacts too, without treating schema
    # property definitions as actual captured identifiers.
    for name in lock['static_sha256']:
        errors[3].extend(privacy_findings(name, (ROOT/name).read_text(encoding='utf-8')))
    entry = load(ENTRY)
    if manifest['baseline_head'] != entry['baseline_head']:
        errors[4].append('entry_baseline_changed')
    if require_commit:
        errors[4].extend(commit_defects(entry['baseline_head'], names))
        for name in lock['static_sha256']:
            if git('show', 'HEAD:'+name) != git('show', entry['baseline_head']+':'+name):
                errors[3].append('objective_001_committed_bytes_changed:' + name)
        for name in entry['excluded_modified_tracked']:
            if git('show', 'HEAD:'+name) != git('show', entry['baseline_head']+':'+name):
                errors[4].append('preexisting_unrelated_change_committed:' + name)
    git('diff', '--check')
    git('diff', '--cached', '--check')
    return {i: sorted(set(v)) for i, v in errors.items() if v}

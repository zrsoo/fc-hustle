"""001d-07 acceptance: independent artifact checks plus a finite offline consumer.

All criteria are covered. No live actors, EA access or browser recovery.
Negative tests mutate only in-memory copies, never historical evidence.
"""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = 'docs/research/001d/001d-07/'
OUT = ROOT/BASE
from fc_access.production_v1.contracts import ROUTES, LOCAL_OPERATIONS, VERSION, parse_response, stamp
from record_001d07_checks import CHANGED, BASELINE


def raw(path):
    p=(ROOT/path).resolve()
    if not p.is_relative_to(ROOT):
        raise AssertionError('path outside workspace')
    return p.read_bytes()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load(path):
    return json.loads(raw(path))


def need(value, reason):
    if not value:
        raise AssertionError(reason)


FIX_IDS = {'D1','D2','D3','D4','D5','S1','S2'}
DEP_IDS = {'002-REBID','002-WIN-COST','002-MOVE-LIST-SETTLE','002-POLL-LOAD',
    '002-TIMER-REFUND','002-STATUS-RECONNECT','002-STATUS-HISTORY','002-UNSOLD-RULES',
    'D1-R2-WIRE','D5-LIVE-INTEGRATION'}


def check_findings(value, graph, reader=raw):
    need(value['schema']==1 and value['readiness']=='001D PARTIAL', 'unjustified readiness promotion')
    fixes=value['fixes']
    need(len(fixes)==7 and {f['id'] for f in fixes}==FIX_IDS, 'missing/duplicate fix')
    need(set(value['evidence_classes'])=={'IMPLEMENTED/OFFLINE_VALIDATED','LIVE_VERIFIED','LIVE-UNVERIFIED'}, 'evidence conflated')
    deps=value['dependencies']
    need(len(deps)==10 and {d['id'] for d in deps}==DEP_IDS, 'missing dependency')
    need(set(graph['dependencies'])==DEP_IDS, 'graph dependency mismatch')
    report=reader(BASE+'REPORT.md').decode('utf-8')
    regressions=json.loads(reader(BASE+'regressions.json'))['checks']
    passed={c['command'][-1] for c in regressions if c['exit_code']==0}
    for f in fixes:
        need(f['status'] in {'IMPLEMENTED','VERIFIED','PARTIAL','INVESTIGATION REQUIRED','DEFERRED TO 002'}, 'unsupported status')
        need(f['implementation_class']=='IMPLEMENTED/OFFLINE_VALIDATED', 'offline promoted to live')
        need(f['changed_paths'] and len(f['implementation'])>150, 'empty implementation')
        need(f['evidence_sources'] and f['offline_tests'] and f['bounded_read_only'], 'missing fix evidence')
        need(f['outstanding_dependencies'] and set(f['outstanding_dependencies'])<=DEP_IDS, 'missing fix gap')
        need('LIVE-UNVERIFIED' in f['bounded_read_only'], 'unobservable cases hidden')
        for p in f['changed_paths']+f['reused_paths']+f['evidence_sources']+f['offline_tests']:
            need(len(reader(p))>0, 'missing source/evidence '+p)
            need(p in report, 'report omits exact path '+p)
        need(set(f['offline_tests'])<=passed, 'offline test was not run successfully')
        need(f['implementation'] in report and f['bounded_read_only'] in report, 'report/checklist diverge')
    need(next(f for f in fixes if f['id']=='S1')['status']=='PARTIAL', 'S1 overclaimed')
    for d in deps:
        for k in ('id','status','owner','prerequisite','missing_operation','required_evidence'):
            need(d[k] and d[k] in report, 'missing concrete dependency '+k)
        need(len(d['missing_operation'])>80 and len(d['required_evidence'])>80, 'vague dependency')
        need(d['status']==('DEFERRED TO 002' if d['id'].startswith('002-') else 'INVESTIGATION REQUIRED'), 'deferral owner changed')
    scope=value['scope']
    for k in ('this_task_native_requests','this_task_live_bids','this_task_purchases',
              'this_task_item_moves','this_task_listings','this_task_recurring_actors','r2_searches'):
        need(type(scope[k]) is int and scope[k]==0, 'scope expanded '+k)
    need(scope['objective_001d_explicit_native_requests']==7, 'probe undercount')
    need(scope['objective_001d_local_helper_evaluations']==8, 'helper undercount')
    need(scope['sealed_histories_changed'] is False, 'history changed')
    need('background' in scope['traffic_scope'], 'account-wide traffic overclaim')


def check_graph(graph, reader=raw):
    need(graph['artifact']=='objective-002-integration-call-graph' and graph['version']=='1.0.0', 'graph version')
    need(graph['compatibility']==dict(wire_schema=2,price_service=1,quote=1,registry=1,journal=1), 'contract version confusion')
    need(graph['operations']=={op:dict(method=m,path=p) for op,(m,p) in ROUTES.items()}, 'route mismatch')
    need(set(graph['local_operations'])==LOCAL_OPERATIONS, 'missing additive local contract')
    ids={n['id'] for n in graph['nodes']}
    need(len(ids)==len(graph['nodes'])==23, 'missing graph node')
    for node in graph['nodes']:
        content=reader(node['path'])
        need(sha(content)==node['sha256'], 'stale graph source '+node['path'])
        need(node['contract'], 'missing consumer contract')
        if node['symbol']:
            tree=ast.parse(content)
            for name in node['symbol'].split('.'):
                tree=next((n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==name),None)
                need(tree is not None, 'unresolvable API symbol '+node['symbol'])
    for edge in graph['edges']:
        need(edge['source'] in ids and edge['target'] in ids and edge['condition'], 'dangling/unguarded graph edge')
    pairs={(e['source'],e['target']) for e in graph['edges']}
    need({('admit','quote'),('quote','cache'),('admit','decide'),('admit','queue'),('bid','dispatch_intent'),
          ('dispatch_intent','intent'),('intent','dispatch'),('dispatch','scheduler'),('adapter','scheduler'),('scheduler','edge'),('edge','server'),
          ('server','store'),('store','worker'),('worker','page'),('reconcile','readbacks')}<=pairs, 'integration graph incomplete')
    need(all(v in ids for v in graph['entrypoints'].values()), 'missing one-shot API')
    start=graph['startup']
    need(start['address']=='127.0.0.1:8784' and start['separately_running_service_required'] is True, 'local service dependency hidden')
    need(start['service_default_mutations'] is False and start['codex_supervisor_required'] is False, 'runtime boundary changed')
    need(start['import_or_json_load_starts_actors'] is False, 'consumer needs actor')
    need(graph['invariants']['production_bid_ceiling'] is None, 'experimental ceiling returned')
    need(graph['invariants']['production_move_list_operations'] is False, 'missing lifecycle implemented by assertion')
    need(graph['invariants']['missing_row']=='UNKNOWN' and graph['invariants']['closed_highest']=='PENDING', 'outcome overclaim')


class HandoffAcceptance(unittest.TestCase):
    def test_c0_focused_and_baseline_runs_have_real_outputs_and_disclosed_failures(self):
        doc=load(BASE+'regressions.json')
        checks=doc['checks']
        self.assertEqual([r['command'] for r in checks], [['{python}',p] for p in CHANGED]+[['{python}',*p] for p in BASELINE])
        self.assertEqual([r['exit_code'] for r in checks], [0]*13+[1]*5)
        self.assertEqual([r['tests_run'] for r in checks[:6]], [[12],[8],[10],[17],[7],[16]])
        for r in checks:
            self.assertLessEqual(stamp(r['started_at']),stamp(r['ended_at']))
            self.assertGreater(r['elapsed_seconds'],0)
            combined=b''
            for stream in ('stdout','stderr'):
                rec=r['streams'][stream]; data=raw(BASE+rec['path'])
                self.assertEqual(sha(data),rec['sha256']); combined+=data
            self.assertEqual(r['tests_run'],[int(n) for n in re.findall(rb'Ran (\d+) tests?',combined)])
            if r['exit_code']==0:
                self.assertRegex(combined.decode(),r'(?m)^OK\s*$')
        findings=load(BASE+'regression-findings.json')
        self.assertEqual([f['check_index'] for f in findings['failures']],list(range(13,18)))
        for f in findings['failures']:
            r=checks[f['check_index']]
            combined=b'\n'.join(raw(BASE+r['streams'][s]['path']) for s in ('stdout','stderr')).decode().replace('\r\n','\n')
            self.assertEqual(f['failing_cases'],re.findall(r'^(?:FAIL|ERROR): (.+)$',combined,re.M))
            self.assertEqual(f['command'],r['command'])
            self.assertIn('predate',f['diagnostic']) if f['check_index'] not in (13,15,16) else self.assertIn('migrations',f['diagnostic'])
        discovery=checks[-1]
        text=raw(BASE+discovery['streams']['stderr']['path']).decode()
        self.assertEqual(discovery['tests_run'],[434])
        self.assertIn('FAILED (failures=20, errors=4)',text)
        self.assertEqual(len(findings['failures'][-1]['failing_cases']),24)
        # Compare with the retained entry-era baseline, never overwrite it.
        old=load('docs/research/001d/baseline.json')['checks']
        self.assertEqual([r['exit_code'] for r in old],[0]*8+[1,0,1,1])
        self.assertEqual(doc['assertion_changes'],[])
        self.assertEqual(findings['resealed_artifacts'],[])

    def test_c1_c4_c6_complete_checklist_dependencies_and_partial_readiness(self):
        value=load(BASE+'checklist-v1.json'); graph=load(BASE+'integration-call-graph-v1.json')
        check_findings(value,graph)
        deps={d['id']:d for d in value['dependencies']}
        terms={'002-REBID':['outbid','smallest','independently'],
            '002-WIN-COST':['physical item','paid','PENDING'],
            '002-MOVE-LIST-SETTLE':['production','one native tick','settlement','realized profit'],
            '002-POLL-LOAD':['600-second','25-second','50-slot','truncation'],
            '002-TIMER-REFUND':['timer','refund','800'],
            '002-STATUS-RECONNECT':['reacquire','UNKNOWN','VERSION_UNOBSERVED'],
            '002-STATUS-HISTORY':['pseudonyms','UNKNOWN'],
            '002-UNSOLD-RULES':['duration','whether/when','price policy','no invented']}
        for id,words in terms.items():
            serialized=json.dumps(deps[id]).lower()
            for word in words: self.assertIn(word.lower(),serialized,id)
        report=raw(BASE+'REPORT.md').decode()
        for phrase in ('001D PARTIAL','not a FULL GO','R2','final Foundation live composition',
                       'lookup after reconnect','20 failures, 4 errors','pre-change REPORT',
                       'helper availability','seven explicit','No recurring actors, live bids, purchases, item moves or listings'):
            self.assertIn(phrase,report)

    def test_c2_c5_retained_live_scope_reparses_routes_identity_freshness_and_counts(self):
        s2=load('docs/research/001d/001d-03/s2-checkpoint.json')
        r1=load('docs/research/001d/001d-05/r1-checkpoint.json')
        s1=load('docs/research/001d/001d-05/s1-checkpoint.json')
        all_rows=s2['observations']+r1['observations']+s1['observations']
        network=[]; helpers=[]
        for row in all_rows:
            c,v=row['command'],row['response']
            self.assertEqual(parse_response(v,c,now=stamp(v['freshness']['observed_at'])),v)
            self.assertTrue(v['result']['success']); self.assertEqual(v['freshness']['source'],'native')
            self.assertNotIn(c['operation'],{'bid','move','list','purchase','search'})
            self.assertEqual(c['context'],s2['context'])
            if c['operation']=='price_helpers':
                self.assertEqual(v['freshness']['request_count'],0)
                self.assertEqual(v['result']['network'],[])
                helpers.extend(v['result']['probes'])
            else:
                self.assertEqual(v['freshness']['request_count'],1)
                self.assertEqual(len(v['result']['network']),1)
                n=v['result']['network'][0]
                self.assertEqual((n['method'],n['path']),ROUTES[c['operation']])
                self.assertEqual((n['method'],n['status'],n['session_header_present']),('GET',200,True))
                network.append(c)
        self.assertEqual(len(network),7); self.assertEqual(len(helpers),8)
        values={(r['direction'],r['value']):r['price'] for r in helpers}
        self.assertEqual(values['above',750],800); self.assertEqual(values['below',1500],1400)
        caps=next(x['response']['result']['caps'] for x in s2['observations'] if x['command']['operation']=='caps')
        self.assertEqual(caps,dict(definition_id=261855,minimum=700,maximum=10500))
        self.assertEqual(r1['reserved_native_requests'],4); self.assertEqual(s1['reserved_native_requests'],2)
        self.assertEqual(s2['reserved_native_requests'],1)
        self.assertEqual(s1['reconnect_inspection']['native_requests'],0)
        self.assertEqual(s1['reconnect_inspection']['retained_count'],0)
        self.assertEqual([r['response']['result']['retained_count'] for r in s1['source_inspections']],[0,1,0])
        watched,lite=[r['response']['result']['auctions'][0] for r in s1['observations']]
        self.assertEqual(watched['trade_id'],lite['trade_id'])
        self.assertEqual(watched['item']['item_id'],lite['item']['item_id'])
        self.assertEqual((watched['item']['definition_id'],lite['item']['definition_id']),(261855,0))
        self.assertEqual((lite['trade_state'],lite['bid_state'],lite['current_bid']),('closed','outbid',1200))
        ledger=load('docs/research/001d/001d-05/transport-evidence.json')
        self.assertEqual(len(ledger['service_command_inventory']),12)
        self.assertTrue(all(r['operation'] not in {'bid','purchase','move','list','search'} for r in ledger['service_command_inventory']))

    def test_c3_versioned_graph_resolves_to_current_code_and_offline_consumer_exits(self):
        graph=load(BASE+'integration-call-graph-v1.json')
        check_graph(graph)
        self.assertEqual(VERSION,2)
        self.assertEqual(graph['context_fields'],['account','persona','game','platform','identity_namespace'])
        # A consumer can inspect this with only JSON; networking, threads and
        # subprocess creation are forbidden during its execution.
        with patch('socket.socket',side_effect=AssertionError('network forbidden')), \
             patch('threading.Thread.start',side_effect=AssertionError('actors forbidden')), \
             patch('subprocess.Popen',side_effect=AssertionError('child actors forbidden')), \
             patch('builtins.print') as output:
            runpy.run_path(str(OUT/'consume_handoff.py'),run_name='__main__')
            summary=json.loads(output.call_args.args[0])
        self.assertEqual(summary['entrypoints'],graph['entrypoints'])
        self.assertEqual(summary['dependencies'],graph['dependencies'])
        child=subprocess.run([sys.executable,'-I',BASE+'consume_handoff.py'],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertEqual(json.loads(child.stdout),summary)

    def test_c0_c3_finite_python_foundation_consumes_contract_without_live_writes(self):
        from foundation_fixture import create, admitted
        with tempfile.TemporaryDirectory() as directory:
            with patch('socket.socket',side_effect=AssertionError('no live transport')), \
                 patch('threading.Thread.start',side_effect=AssertionError('no recurring actor')):
                f,p,clock=create(directory)
                try:
                    decision,_,_=admitted(f,p)
                    self.assertEqual((decision['action'],decision['amount'],decision['cap']),('BID',2500,10750))
                    self.assertEqual(p.bid_calls,0,'admission must never dispatch')
                    candidate=p.candidate; prices=f.admissions[candidate['trade_id']][2]
                    searches_before=sum(c['operation']=='search' and c['params']['purpose']=='pricing' for c in p.calls)
                    q=f.pricing.quote(candidate,prices)
                    searches_after=sum(c['operation']=='search' and c['params']['purpose']=='pricing' for c in p.calls)
                    self.assertEqual(searches_before,2); self.assertEqual(searches_after,2)
                    self.assertTrue(q.completed); self.assertEqual(q.max_affordable_bid,10750)
                    self.assertEqual(f.executor.scheduler.concurrency,1)
                    state=f.registry.current()
                    self.assertEqual(state['schema'],1); self.assertFalse(state['unresolved'])
                    self.assertEqual(p.real_account_writes,0)
                    self.assertFalse(any(c['operation']=='bid' for c in p.calls))
                finally:
                    f.close(); p.close()

    def test_c5_preserves_every_entry_byte_and_all_sealed_history(self):
        entry=load(BASE+'entry.json')
        self.assertTrue(entry['git_status'],'preceding implementation work must not be mistaken for our edits')
        self.assertEqual(len(entry['sha256']),696)
        for path,digest in entry['sha256'].items():
            self.assertEqual(sha(raw(path)),digest,path)
        # Original pre-change publication pins prove we did not replace the
        # obsolete inventory with a manufactured all-green final report.
        old=load('docs/research/001d/publication.json')
        for path,digest in old['sha256'].items():
            self.assertEqual(sha(raw(path)),digest,path)
        pub=load(BASE+'publication.json')
        for path,digest in pub['sha256'].items():
            self.assertEqual(sha(raw(path)),digest,path)
        required={BASE+p for p in ('REPORT.md','checklist-v1.json','integration-call-graph-v1.json',
            'consume_handoff.py','entry.json','regressions.json','regression-findings.json')}
        self.assertTrue(required<=set(pub['sha256']))
        self.assertIn('tests/test_001d07_handoff.py',pub['sha256'])

    def test_c1_c2_c3_c4_c6_missing_evidence_and_overclaims_fail_without_rewriting_files(self):
        value=load(BASE+'checklist-v1.json'); graph=load(BASE+'integration-call-graph-v1.json')
        for mutate in (
            lambda d:d.update(readiness='001D READY'),
            lambda d:d['fixes'].pop(),
            lambda d:d['dependencies'].pop(),
            lambda d:d['fixes'][0].update(implementation_class='LIVE_VERIFIED'),
            lambda d:d['fixes'][0].update(offline_tests=['tests/test_release_audit.py']),
            lambda d:d['fixes'][0].update(bounded_read_only='Everything is verified'),
            lambda d:d['scope'].update(r2_searches=2),
        ):
            v=deepcopy(value); mutate(v)
            with self.assertRaises(AssertionError): check_findings(v,graph)
        for mutate in (
            lambda g:g.update(version='2.0.0'),
            lambda g:g['operations']['balance'].update(path='/ut/game/fc27/user/currencies'),
            lambda g:g['nodes'][0].update(sha256='0'*64),
            lambda g:g['startup'].update(separately_running_service_required=False),
            lambda g:g['invariants'].update(production_bid_ceiling=1000),
            lambda g:g['invariants'].update(closed_highest='WON'),
            lambda g:g['edges'].clear(),
        ):
            g=deepcopy(graph); mutate(g)
            with self.assertRaises(AssertionError): check_graph(g)


if __name__=='__main__':
    unittest.main(verbosity=2)

"""All 001d-05 criteria; independent offline checks, never dispatch live probes.

python tests/test_001d05_inventory.py
Executes actual production JS with native/XHR mocks, then checks native evidence
at its recorded time, checkpoint preservation, exact budgets and 002 dependencies.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.production_v1.adapter import NativeAdapter
from fc_access.production_v1.contracts import stamp, ROUTES, VERSION
from historical_contracts import parse_response
from fc_access.production_v1.inventory import KnownTrade, compare_lite_identity, watched_status
from fc_access.production_v1 import investigate_reads, investigate_status
from test_001d02_contract import make_command, reply, hexid
from migration_001d03 import historical_reader
from migration_001d06 import source_before_foundation

OUT = ROOT / 'docs/research/001d/001d-05'


from fc_access.evidence import evidence_hashes

def load(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


class InventoryAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('node'):
            raise RuntimeError('Node.js required to execute native mocks')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'samples.json'
            run = subprocess.run(['node', 'tests/production_inventory_checks.cjs', str(path)], cwd=ROOT,
                                 capture_output=True, text=True, timeout=40)
            if run.returncode:
                raise AssertionError(run.stdout + run.stderr)
            cls.samples = json.loads(path.read_text())

    def test_c0_c1_actual_native_projection_parses_and_adapter_preserves_all_rows(self):
        successes = [s for s in self.samples if s['response']['result']['success']]
        self.assertTrue({'watched', 'unassigned', 'transfer_list', 'status', 'status_support'} <= {s['command']['operation'] for s in successes})
        for s in successes:
            c, r, at = s['command'], s['response'], stamp(s['now'])
            self.assertEqual(parse_response(r, c, now=at), r)
            class Executor:
                def attach(self, context, owner, epoch):
                    self_args = (context, owner, epoch)
                    assert self_args == (c['context'], c['fences']['owner'], c['fences']['epoch'])
                    return c['fences']
                def execute(self, value):
                    assert value == c
                    return deepcopy(r)
            a = NativeAdapter(Executor(), context=c['context'], owner=c['fences']['owner'], epoch=c['fences']['epoch'], now=lambda: at)
            actual = (a.known_status(c['id'], **c['params']) if c['operation'] == 'status'
                      else a.read(c['id'], c['operation'], c['params']))
            self.assertEqual(actual, r)
        large = [s for s in successes if len(s['response']['result'].get('auctions') or s['response']['result'].get('items') or []) == 50]
        self.assertEqual({s['command']['operation'] for s in large}, {'watched', 'transfer_list', 'unassigned'})

    def test_c0_c1_reject_forged_cache_only_routes_auth_source_status_and_freshness(self):
        now = datetime.now(timezone.utc)
        for op in ('watched', 'unassigned', 'transfer_list', 'balance'):
            c = make_command(op); base = reply(c, now)
            changes = [lambda v: v['result'].update(network=[]),
                       lambda v: v['freshness'].update(network_at=None),
                       lambda v: v['freshness'].update(source='fixture'),
                       lambda v: v['freshness'].update(request_count=0),
                       lambda v: v['freshness'].update(read_id=hexid(999)),
                       lambda v: v['freshness'].update(network_at=(now-timedelta(seconds=31)).isoformat()),
                       lambda v: v['result']['network'][0].update(method='POST'),
                       lambda v: v['result']['network'][0].update(path='/ut/game/fc27/user/currencies'),
                       lambda v: v['result']['network'][0].update(session_header_present=False),
                       lambda v: v['result']['network'][0].update(status=401),
                       lambda v: v['result'].update(status=201),
                       lambda v: v['result']['network'][0].update(query={'num': 21}),
                       lambda v: v['fences'].update(document=hexid(999)),
                       lambda v: v['context'].update(identity_namespace=hexid(999))]
            if op != 'balance':
                changes.append(lambda v: v['result'].update(cache_invalidated=False))
            for change in changes:
                v = deepcopy(base); change(v)
                with self.subTest(op=op, value=v), self.assertRaises(ValueError):
                    parse_response(v, c, now=now)
            self.assertEqual(parse_response(base, c, now=now), base)

    def test_c2_missing_unknown_and_closed_highest_pending_even_native_won(self):
        c = make_command('watched'); r = reply(c); now = stamp(r['freshness']['observed_at'])
        row = r['result']['auctions'][0]
        identity = KnownTrade(row['trade_id'], row['item']['item_id'], row['item']['definition_id'])
        def assess(v):
            return watched_status(v, c, identity, expected_context=c['context'], now=now)
        self.assertEqual(assess(r)['outcome'], 'WATCHING')
        empty = deepcopy(r); empty['result']['auctions'] = []
        self.assertEqual(assess(empty)['outcome'], 'UNKNOWN')
        for won in (True, False, None):
            v = deepcopy(r); v['result']['auctions'][0].update(trade_state='closed', bid_state='highest', expires=-1, native_is_won=won)
            result = assess(v)
            self.assertEqual(result['outcome'], 'PENDING'); self.assertFalse(result['ownership_proven'])
            self.assertEqual(result['reason'], 'INDEPENDENT_OWNED_ITEM_PROOF_REQUIRED')
        v = deepcopy(r); v['result']['auctions'][0].update(trade_state='closed', bid_state='outbid', expires=-1)
        self.assertEqual(assess(v)['outcome'], 'LOST')
        for key, value in (('item_id', 'item:'+'f'*24), ('definition_id', 10)):
            v = deepcopy(r); v['result']['auctions'][0]['item'][key] = value
            self.assertEqual(assess(v)['outcome'], 'UNKNOWN')
        v = deepcopy(r); v['freshness']['network_at'] = (now-timedelta(minutes=1)).isoformat()
        with self.assertRaises(ValueError): assess(v)
        with self.assertRaises(ValueError):
            watched_status(r, c, identity, expected_context={**c['context'], 'identity_namespace': hexid(999)}, now=now)

    def test_c2_c3_lite_zero_and_omitted_preserve_retained_identity_and_true_mismatch_fails(self):
        s = next(x for x in self.samples if x['command']['operation'] == 'status' and x['response']['result']['success'] and x['response']['result']['auctions'])
        c, r = s['command'], s['response']; known = KnownTrade(**c['params'])
        for definition in (0, None, known.definition_id):
            v = deepcopy(r); v['result']['auctions'][0]['item']['definition_id'] = definition
            self.assertEqual(parse_response(v, c, now=stamp(s['now'])), v)
            row = dict(trade_id=known.trade_id, item_id=known.item_id)
            if definition is not None: row['definition_id'] = definition
            self.assertEqual(compare_lite_identity(known, row), 'MATCH' if definition == known.definition_id else 'MATCH_RETAINED_VERSION_UNOBSERVED')
            self.assertEqual(known, KnownTrade(**c['params']))
        row = {**known.params(), 'definition_id': known.definition_id+1}
        self.assertEqual(compare_lite_identity(known, row), 'DIFFERENT_CARD')
        for key, value in (('definition_id', known.definition_id+1), ('item_id', 'item:'+'c'*24)):
            v = deepcopy(r); v['result']['auctions'][0]['item'][key] = value
            with self.assertRaisesRegex(ValueError, 'wrong_status_identity'): parse_response(v, c, now=stamp(s['now']))
        v = deepcopy(r); v['result']['network'][0]['query']['trade_id'] = 'trade:'+'c'*24
        with self.assertRaisesRegex(ValueError, 'wire_status_identity_mismatch'): parse_response(v, c, now=stamp(s['now']))

    def test_c3_c4_c5_actual_live_windows_routes_status_source_and_exact_counts(self):
        r1, s1 = load('r1-checkpoint.json'), load('s1-checkpoint.json')
        plan = json.loads((ROOT/'docs/research/001d/execution-plan.json').read_text())
        bounds = {w['id']: w for w in plan['windows']}
        self.assertEqual([x['command']['operation'] for x in r1['observations']], bounds[r1['window']]['operations'])
        # S1's same allowed two operations: watched first to reestablish native
        # mapping after review/reload, then status. No extra watched/status call.
        self.assertEqual([x['command']['operation'] for x in s1['observations']], ['watched', 'status'])
        for doc, count in ((r1, 4), (s1, 2)):
            self.assertEqual(doc['phase'], 'COMPLETED')
            self.assertEqual(doc['reserved_native_requests'], count); self.assertEqual(doc['actual_native_requests'], count)
            self.assertEqual(doc['mutations'], 0); self.assertNotIn('pending_command', doc)
            self.assertLessEqual(doc['elapsed_seconds'], bounds[doc['window']]['seconds'])
            self.assertEqual(doc['context'], r1['context'])
            for x in doc['observations']:
                c, v = x['command'], x['response']; f = v['freshness']; n = v['result']['network']
                self.assertEqual(c['context'], doc['context'])
                parse_response(v, c, now=stamp(f['observed_at']))
                self.assertEqual((v['result']['success'], v['result']['status'], len(n)), (True, 200, 1))
                self.assertEqual((n[0]['method'], n[0]['path']), ROUTES[c['operation']])
                self.assertTrue(n[0]['session_header_present']); self.assertEqual(f['source'], 'native')
                self.assertEqual(f['request_count'], 1); self.assertEqual(f['read_id'], c['id'])
                self.assertLessEqual(stamp(doc['started_at']), stamp(f['network_at']))
                self.assertLessEqual(stamp(f['observed_at']), stamp(doc['deadline']))
        self.assertEqual(len({x['command']['id'] for d in (r1,s1) for x in d['observations']}), 6)
        watched = s1['observations'][0]['response']['result']['auctions'][0]
        lite = s1['observations'][1]['response']['result']['auctions'][0]
        self.assertEqual(lite['item']['definition_id'], 0)
        identity = KnownTrade(**s1['known_identity'])
        self.assertEqual(compare_lite_identity(identity, dict(trade_id=lite['trade_id'], item_id=lite['item']['item_id'], definition_id=0)), 'MATCH_RETAINED_VERSION_UNOBSERVED')
        self.assertEqual(watched['item']['definition_id'], identity.definition_id)
        self.assertEqual((lite['trade_state'],lite['bid_state'],lite['current_bid'],lite['expires']), ('closed','outbid',1200,-1))
        self.assertEqual(s1['current_context'], 'EXACT_RETAINED_TRADE_LOOKUP_OBSERVED')
        self.assertEqual(s1['reconnect'], 'NATIVE_MAPPING_UNAVAILABLE_AFTER_RECONNECT')
        self.assertEqual(s1['reconnect_inspection']['native_requests'], 0)
        supports = s1['source_inspections']; self.assertEqual(len(supports), 3)
        self.assertEqual([v['response']['result']['retained_count'] for v in supports], [0,1,0])
        for value in supports:
            parse_response(value['response'], value['command'], now=stamp(value['response']['freshness']['observed_at']))
            self.assertTrue(value['response']['result']['source_match'])
            self.assertEqual(value['response']['freshness']['request_count'],0)
        self.assertNotEqual(supports[1]['command']['fences']['document'], supports[2]['command']['fences']['document'])
        self.assertGreater(supports[2]['command']['fences']['epoch'], supports[1]['command']['fences']['epoch'])
        ledger = load('transport-evidence.json')
        captures = r1['observations'] + s1['observations'] + supports
        expected = {x['command']['id']: x for x in captures}
        self.assertEqual(len(expected), 9); self.assertEqual(len(ledger['commands']), 9)
        self.assertEqual({x['command']['id'] for x in ledger['commands']}, set(expected))
        events = []
        for item in ledger['commands']:
            x = expected[item['command']['id']]
            self.assertEqual(item['command'],x['command']); self.assertEqual(item['response'],x['response'])
            self.assertEqual(item['state'],'ACKNOWLEDGED')
            self.assertEqual([e['event'] for e in item['events']], ['RESERVED','DELIVERED','ACKNOWLEDGED'])
            seq = [e['seq'] for e in item['events']]
            self.assertEqual(seq,sorted(set(seq))); self.assertEqual(len(seq),3); events.extend(seq)
        self.assertEqual(len(events),len(set(events)))
        command_inventory = ledger['service_command_inventory']
        self.assertEqual(len(command_inventory),12)
        self.assertEqual({x['id'] for x in command_inventory} - set(expected),
                         {x['command']['id'] for x in json.loads((ROOT/'docs/research/001d/001d-03/s2-checkpoint.json').read_text())['observations']})
        self.assertTrue(all(x['state']=='ACKNOWLEDGED' for x in command_inventory))
        self.assertFalse(any(x['operation'] in {'bid','move','list','purchase','search'} for x in command_inventory))

    def test_c4_c6_own_control_separate_gates_sealed_history_and_no_replay(self):
        for name in ('edge-r1-inspection.txt','edge-s1-selected.txt','edge-s1-attached.txt','edge-reconnect-reattached.txt'):
            first = (OUT/name).read_text(encoding='utf-8-sig').splitlines()[0]
            value = json.loads(first)
            self.assertTrue(value['foreground_verified']); self.assertTrue(value['edge_control_verified']); self.assertTrue(value['official_tab'])
        r1, s1 = load('r1-checkpoint.json'), load('s1-checkpoint.json')
        self.assertIn('agents_sha256', r1); self.assertIn('agents_sha256', s1)  # historical provenance
        h = r1['health_before']; self.assertTrue(h['attached']); self.assertFalse(h['mutations_enabled'])
        self.assertEqual(h['owner']['context'], r1['context'])
        # A completed window must refuse replay before even opening localhost.
        before = {p: p.read_bytes() for p in (investigate_reads.CHECKPOINT, investigate_status.CHECKPOINT)}
        with patch.object(investigate_reads, 'EdgeExecutor', side_effect=AssertionError('no_connection')), patch.object(investigate_status, 'EdgeExecutor', side_effect=AssertionError('no_connection')):
            for fn, reason in ((investigate_reads.run,'existing_checkpoint_no_replay'),
                               (investigate_status.prepare,'existing_checkpoint_no_replay'),
                               (investigate_status.run,'window_consumed_no_replay'),
                               (investigate_status.reconnect_inspection,'completed_inspection_no_replay')):
                with self.assertRaisesRegex(ValueError, reason): fn()
        for p, raw in before.items(): self.assertEqual(p.read_bytes(), raw)
        historic = historical_reader(lambda p: (ROOT/p).read_bytes())
        for record in ('entry.json','publication.json'):
            for p, digest in evidence_hashes(json.loads((ROOT/'docs/research/001d'/record).read_text())['sha256']).items():
                self.assertEqual(hashlib.sha256(historic(p)).hexdigest(), digest, p)
        sealed = json.loads((ROOT/'docs/research/001d/001d-03/s2-checkpoint.json').read_text())
        self.assertEqual((sealed['phase'],sealed['reserved_native_requests'],sealed['reserved_helper_evaluations']), ('COMPLETED',1,8))

    def test_c0_c3_c5_c6_report_paths_budget_dependencies_and_evidence_manifest(self):
        doc = (OUT/'REPORT.md').read_text(encoding='utf-8')
        manifest = load('evidence.json')
        self.assertEqual(manifest['new_native_requests'],6)
        self.assertEqual(manifest['local_source_inspections'],3)
        self.assertEqual(manifest['live_mutations'],0)
        for path, digest in evidence_hashes(manifest['sha256']).items():
            self.assertEqual(hashlib.sha256(source_before_foundation(path, (ROOT/path).read_bytes())).hexdigest(),digest,path)
        for path in manifest['production_paths']:
            self.assertTrue((ROOT/path.split(':')[0]).is_file()); self.assertIn('`'+path+'`',doc)
        deps = manifest['objective_002_dependencies']
        self.assertEqual({d['id'] for d in deps}, {'002-STATUS-RECONNECT','002-STATUS-HISTORY','002-NATURAL-OUTCOMES'})
        for dep in deps:
            self.assertIn(dep['id'], doc); self.assertTrue(dep['prerequisite']); self.assertTrue(dep['validation'])
        for phrase in ('LIVE_VERIFIED','OFFLINE_VALIDATED','LIVE-UNVERIFIED','UNKNOWN','PENDING','definition_id=0',
                       'AGENTS.md','No new bid','S2','16,268','six','background','initial reconnect attachment','untradeable'):
            self.assertIn(phrase,doc)
        source = (ROOT/'browser/production-v1/page.js').read_text()
        self.assertNotIn('performance.getEntriesByType',source)
        self.assertNotIn("KEY='06'",source)
        self.assertEqual(VERSION,2)


if __name__ == '__main__':
    unittest.main(verbosity=2)

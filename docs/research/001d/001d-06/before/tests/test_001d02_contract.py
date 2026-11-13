"""001d-02 acceptance: executes production Python, page and worker contracts.

Independent argv: python tests/test_001d02_contract.py. Only loopback fixtures;
no installed browser, credentials, EA traffic, or generated historical evidence.
"""
from copy import deepcopy
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from migration_001d03 import historical_reader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.production_v1.contracts import (VERSION, ROUTES, Search, command, parse_response,
    empty_result, correlate_readbacks, stamp, CONTEXT, FENCES, ITEM, AUCTION)
from fc_access.production_v1.adapter import NativeAdapter
from fc_access.production_v1.store import Store
from fc_access.production_v1.server import Server
from fc_access.production_v1.executor import EdgeExecutor

hexid = lambda n: f'{n:032x}'
CONTEXT_VALUE = dict(account=hexid(1), persona=hexid(2), game='fc27', platform='pc', identity_namespace=hexid(3))


def make_command(op='balance', params=None, n=10, host=None):
    return dict(schema=VERSION, id=hexid(n), operation=op, params=params or {}, context=deepcopy(CONTEXT_VALUE),
                fences=dict(owner=hexid(4), epoch=1, host_epoch=host or hexid(5), worker_epoch=hexid(6), document=hexid(7)))


def reply(c, at=None):
    at = at or datetime.now(timezone.utc)
    r = empty_result(None)
    r.update(success=True, status=200, cache_invalidated=c['operation'] in {'search', 'watched', 'unassigned', 'transfer_list'})
    op = c['operation']
    if op in {'watched', 'search', 'transfer_list'}:
        r['auctions'] = [{'trade_id': 'trade:'+'a'*24, 'item': {'item_id': 'item:'+'b'*24,
            'definition_id': c['params'].get('definition_id', 7654321), 'untradeable': False, 'last_sale_price': 7700},
            'starting_bid': 2500, 'current_bid': 0, 'buy_now_price': 15000, 'expires': 300,
            'trade_state': 'active', 'bid_state': 'none', 'native_is_won': False}]
    if op == 'balance': r['credits'] = 90000
    if op == 'unassigned': r['items'] = []
    if op == 'caps': r['caps'] = {'definition_id': c['params']['definition_id'], 'minimum': 150, 'maximum': 50000}
    query = {}
    if op == 'search':
        p = c['params']; query = dict(start=0, num=21, definitionId=p['definition_id'])
        for k, wire in [('max_bid', 'macr'), ('min_buy', 'minb'), ('max_buy', 'maxb')]:
            if k in p: query[wire] = p[k]
    if op == 'caps': query = {'defId': c['params']['definition_id']}
    method, path = ROUTES[op]
    r['network'] = [dict(host='utas.test.ea.com', method=method, path=path, query=query, status=200, session_header_present=True)]
    return dict(schema=VERSION, command_id=c['id'], operation=op, context=deepcopy(c['context']), fences=deepcopy(c['fences']), result=r,
        freshness=dict(observed_at=at.isoformat(), network_at=at.isoformat(), request_count=1, read_id=c['id'], source='native'),
        coverage=dict(complete=False, has_more=False), timing=dict(native_service_ms=12))


class ContractAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('node'):
            raise RuntimeError('Node.js required for mocked native acceptance')
        cls.temp = tempfile.TemporaryDirectory()
        out = Path(cls.temp.name)/'native.json'
        run = subprocess.run(['node', 'tests/production_page_checks.cjs', str(out)], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise AssertionError(run.stdout+run.stderr)
        cls.samples = json.loads(out.read_text())
        run = subprocess.run(['node', 'tests/production_worker_checks.cjs'], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise AssertionError(run.stdout+run.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_criteria_1_2_3_4_5_real_page_results_parse_without_dialect_translation(self):
        # 001d-05 adds a retained-identity status operation, checked separately by
        # test_001d05_inventory.py. This fixture retains its original D1 scope.
        self.assertEqual({s['command']['operation'] for s in self.samples}, set(ROUTES) - {'status'})
        for s in self.samples:
            with self.subTest(op=s['command']['operation']):
                original = deepcopy(s['response'])
                parsed = parse_response(s['response'], s['command'], now=stamp(s['now']))
                self.assertEqual(parsed, original)
                self.assertEqual(s['response'], original, 'route auditing mutated observed traffic')
        pricing = [s for s in self.samples if s['command']['operation'] == 'search' and 'max_buy' in s['command']['params']][0]
        self.assertEqual(pricing['response']['result']['network'][0]['query'], dict(start=0, num=21, definitionId=7654321, maxb=15000))
        self.assertEqual(pricing['response']['result']['auctions'][0]['buy_now_price'], 15000)
        bid = next(s for s in self.samples if s['command']['operation'] == 'bid')
        self.assertEqual(bid['command']['params']['amount'], 2500)

    def test_criteria_1_4_response_allowlists_and_full_correlation_are_enforced(self):
        c = make_command(); good = reply(c); now = stamp(good['freshness']['observed_at'])
        cases = []
        for key in ('schema', 'command_id', 'operation'):
            bad = deepcopy(good); bad[key] = 1 if key == 'schema' else hexid(123); cases.append(bad)
        for key in CONTEXT:
            bad = deepcopy(good); bad['context'][key] = 'changed'; cases.append(bad)
        for key in FENCES:
            bad = deepcopy(good); bad['fences'][key] = 2 if key == 'epoch' else hexid(999); cases.append(bad)
        bad = deepcopy(good); bad['fences']['epoch'] = True; cases.append(bad)
        for container in ([], ['result'], ['freshness'], ['coverage'], ['timing'], ['result', 'network', 0]):
            bad = deepcopy(good); d = bad
            for k in container: d = d[k]
            d['credentials'] = 'CANARY'; cases.append(bad)
        for key, value in [('request_count', True), ('request_count', 2), ('read_id', hexid(999)), ('source', 'fixture'),
                           ('network_at', None), ('network_at', (now-timedelta(seconds=31)).isoformat()),
                           ('observed_at', (now+timedelta(seconds=60)).isoformat())]:
            bad = deepcopy(good); bad['freshness'][key] = value; cases.append(bad)
        for key, value in [('session_header_present', False), ('status', 401), ('method', 'POST'),
                           ('path', '/ut/game/fc27/user/currencies'), ('path', '/ut/game/fc27/watchlist'), ('host', 'evil.example')]:
            bad = deepcopy(good); bad['result']['network'][0][key] = value; cases.append(bad)
        bad = deepcopy(good); bad['result']['network'] *= 2; bad['freshness']['request_count'] = 2; cases.append(bad)
        for val in (float('nan'), -1, True):
            bad = deepcopy(good); bad['timing']['native_service_ms'] = val; cases.append(bad)
        for bad in cases:
            with self.subTest(case=cases.index(bad)):
                with self.assertRaises((ValueError, TypeError)): parse_response(bad, c, now=now)

    def test_criteria_1_3_search_identity_wire_and_payload_negative_cases(self):
        c = make_command('search', Search.pricing(7654321, 15000).params()); good = reply(c)
        cases = []
        for path, value in [(['result', 'auctions', 0, 'item', 'definition_id'], 123),
                            (['result', 'auctions', 0, 'item', 'item_id'], None),
                            (['result', 'auctions', 0, 'trade_id'], None),
                            (['result', 'cache_invalidated'], False),
                            (['result', 'network', 0, 'query'], dict(start=0, num=21, definitionId=7654321, macr=15000)),
                            (['result', 'network', 0, 'query'], dict(start=20, num=21, definitionId=7654321, maxb=15000)),
                            (['result', 'network', 0, 'query'], dict(start=0, num=20, definitionId=7654321, maxb=15000)),
                            (['result', 'network', 0, 'query'], dict(start=0, num=21, definitionId=9999, maxb=15000))]:
            bad = deepcopy(good); d = bad
            for k in path[:-1]: d = d[k]
            d[path[-1]] = value; cases.append(bad)
        for container in (['result', 'auctions', 0], ['result', 'auctions', 0, 'item']):
            bad = deepcopy(good); d = bad
            for k in container: d = d[k]
            d['private'] = 'CANARY'; cases.append(bad)
        bad = deepcopy(good); bad['result']['auctions'] *= 2; cases.append(bad)
        bad = deepcopy(good); bad['result']['items'] = []; cases.append(bad)
        for bad in cases:
            with self.assertRaises(ValueError): parse_response(bad, c)
        for params in [Search.discovery(7654321).params() | {'min_buy': 10500}, Search.pricing(7654321).params() | {'max_bid': 1000},
                       Search.pricing(7654321).params() | {'page': 2}, Search.pricing(7654321).params() | {'count': 20},
                       Search.pricing(7654321).params() | {'fresh': False}]:
            with self.assertRaises(ValueError): command(make_command('search', params))

    def test_criterion_4_adapter_error_timeout_ambiguous_write_never_acknowledged(self):
        class Executor:
            mode = 'ok'
            def attach(self, context, owner, epoch): return make_command()['fences']
            def execute(self, c):
                if c['operation']=='price_helpers':
                    r=reply(make_command());r.update(command_id=c['id'],operation=c['operation'],context=c['context'],fences=c['fences'])
                    from native_price_fixture import FixturePriceAdapter
                    rows=FixturePriceAdapter().price_helpers(c['id'],c['params']['probes'])['result']['probes']
                    r['result']=dict(success=True,error=None,version=1,above_available=True,below_available=True,probes=rows,network=[])
                    r['freshness'].update(network_at=None,request_count=0,read_id=c['id']);r['coverage']['has_more']=None
                    return r
                if self.mode == 'timeout' and c['operation']=='bid': raise TimeoutError('SECRET_EXCEPTION')
                if self.mode == 'malformed': return {'secret': 'SECRET_BODY'}
                r = reply(c)
                if self.mode == 'failed': r['result'].update(success=False, error='service_failed')
                return r
        class Journal:
            def __init__(self): self.ids = set()
            def dispatch_once(self, c, send):
                if c['id'] in self.ids: raise ValueError('duplicate_intent')
                self.ids.add(c['id']); return send()
        e, j = Executor(), Journal()
        a = NativeAdapter(e, context=CONTEXT_VALUE, owner=hexid(4), epoch=1)
        self.assertEqual(a.balance(hexid(20))['result']['credits'], 90000)
        with self.assertRaises(ValueError): a.read(hexid(21), 'bid')
        p = self.bid_params()
        from fc_access.production_v1.prices import PriceService,CardKey
        import itertools
        ids=itertools.count(200)
        prices=PriceService(a,lambda:hexid(next(ids))).load(key=CardKey(7654321))
        a.watched(p['status_read_id']);a.balance(p['balance_read_id'])
        for n, mode in enumerate(('timeout', 'malformed', 'failed', 'ok'), 30):
            e.mode = mode
            r = a.dispatch_intent(hexid(n), p, journal=j,prices=prices,resale_price=12000)
            self.assertEqual(r['outcome'], 'ACKNOWLEDGED' if mode == 'ok' else 'UNKNOWN')
            self.assertNotIn('SECRET', json.dumps(r))
            with self.assertRaises(ValueError): a.dispatch_intent(hexid(n), p, journal=j,prices=prices,resale_price=12000)
        e.mode = 'malformed'
        with self.assertRaises(ValueError): a.balance(hexid(90))
        e.mode = 'failed'
        with self.assertRaisesRegex(ValueError, '^service_failed$'): a.balance(hexid(91))

    @staticmethod
    def bid_params():
        return dict(trade_id='trade:'+'a'*24, item_id='item:'+'b'*24, definition_id=7654321,
                    amount=2500, minimum=2500, cap=9000, deadline=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat(),
                    status_read_id=hexid(100), balance_read_id=hexid(101))

    def test_criteria_1_6_independent_readbacks_and_namespace_boundaries(self):
        write = make_command('bid', self.bid_params(), 120)
        sc, bc = make_command('watched', n=121), make_command('balance', n=122)
        at = datetime.now(timezone.utc); s, b = reply(sc, at), reply(bc, at)
        def correlate(status=s, balance=b, w=write, after=at-timedelta(seconds=1)):
            return correlate_readbacks(w, status, balance, status_command=sc, balance_command=bc, after=after, now=at)
        self.assertEqual(correlate()['state'], 'OBSERVED')
        closed = deepcopy(s); closed['result']['auctions'][0].update(trade_state='closed', bid_state='highest', native_is_won=True)
        self.assertEqual(correlate(closed)['state'], 'PENDING')
        for key in ('identity_namespace', 'account', 'persona', 'game', 'platform'):
            bad = deepcopy(s); bad['context'][key] = hexid(999)
            with self.assertRaises(ValueError): correlate(bad)
        for key, value in [('trade_id', 'trade:'+'c'*24), ('item_id', 'item:'+'c'*24), ('definition_id', 123)]:
            bad = deepcopy(s)
            (bad['result']['auctions'][0] if key == 'trade_id' else bad['result']['auctions'][0]['item'])[key] = value
            with self.assertRaises(ValueError): correlate(bad)
        bad = deepcopy(s); bad['command_id'] = write['params']['status_read_id']
        with self.assertRaises(ValueError): correlate(bad)
        with self.assertRaises(ValueError): correlate(after=at+timedelta(seconds=1))
        empty = deepcopy(s); empty['result']['auctions'] = []
        with self.assertRaisesRegex(ValueError, 'identity_unknown'): correlate(empty)

    def test_criteria_1_4_5_store_single_owner_restart_unknown_and_no_finite_budget(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'state.sqlite'; s = Store(path)
            c = make_command(host=s.host_epoch); p = {'context': c['context'], 'fences': c['fences']}
            s.activate(dict(context=c['context'], owner=c['fences']['owner'], epoch=1))
            for n in range(30):
                c['id'] = hexid(1000+n); s.enqueue(c, p)
                with self.assertRaises(ValueError): s.enqueue(c | {'id': hexid(2000+n)}, p)
                self.assertEqual(s.claim(p), c); self.assertIsNone(s.claim(p))
                s.finish(p, c['id'], reply(c)); self.assertEqual(s.result(c['id'])['result']['credits'], 90000)
                with self.assertRaises(ValueError): s.finish(p, c['id'], reply(c))
                with self.assertRaises(ValueError): s.enqueue(c, p)
            bid = make_command('bid', self.bid_params(), 3000, host=s.host_epoch)
            with self.assertRaisesRegex(ValueError, 'durable_intent'): s.enqueue(bid, p)
            bad = deepcopy(c); bad['credentials'] = 'SECRET'; bad['id'] = hexid(3001)
            with self.assertRaises(ValueError): s.enqueue(bad, p)
            c['id'] = hexid(3002); s.enqueue(c, p); s.claim(p)
            bad = reply(c); bad['secret'] = 'SECRET-CANARY'
            with self.assertRaises(ValueError): s.finish(p, c['id'], bad)
            self.assertIsNone(s.result(c['id']))
            s.db.close(); s2 = Store(path)
            self.assertNotEqual(s.host_epoch, s2.host_epoch)
            self.assertEqual(s2.db.execute('SELECT state FROM commands WHERE id=?', (c['id'],)).fetchone()[0], 'UNKNOWN')
            with self.assertRaises(ValueError): s2.claim(p)
            self.assertNotIn('SECRET', '\n'.join(s2.db.iterdump()))
            self.assertEqual(s2.owner()['epoch'], 2)
            # No old read limit/window exists, while replay and owner checks remain.
            p['fences'].update(epoch=2, host_epoch=s2.host_epoch)
            c['fences'] = deepcopy(p['fences'])
            with self.assertRaises(ValueError): s2.enqueue(c, p)
            s2.db.close()

    def test_criterion_4_actual_localhost_transport_pin_delivery_and_timeout(self):
        with tempfile.TemporaryDirectory() as t:
            server = Server(Path(t)/'server.sqlite', 0, wait_seconds=1, poll_seconds=.5)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            executor = EdgeExecutor(server.server_port, attach_timeout=1)
            def post(path, value, extension=False):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                body = json.dumps(value).encode(); headers = {'Content-Type': 'application/json'}
                if extension: headers['Origin'] = server.extension_origin
                conn.request('POST', path, body, headers)
                r = conn.getresponse(); result = r.status, json.loads(r.read()); conn.close(); return result
            try:
                c = make_command(host=server.store.host_epoch); p = {'context': c['context'], 'fences': c['fences']}
                self.assertEqual(post('/activate', dict(context=c['context'], owner=c['fences']['owner'], epoch=1))[0], 200)
                self.assertEqual(post('/hello', dict(schema=2, peer=p))[0], 403)
                self.assertEqual(post('/hello', dict(schema=2, peer=p), True)[0], 200)
                # The executor and adapter use precisely the same HTTP protocol.
                fences = executor.attach(c['context'], c['fences']['owner'], 1)
                self.assertEqual(fences, c['fences'])
                result = []
                worker = threading.Thread(target=lambda: result.append(post('/run', c))); worker.start()
                delivered = post('/next', p, True)[1]
                self.assertEqual(delivered, c)
                wrong = deepcopy(p); wrong['fences']['worker_epoch'] = hexid(999)
                self.assertEqual(post('/result', dict(peer=wrong, id=c['id'], result=reply(c)), True)[0], 409)
                self.assertEqual(post('/result', dict(peer=p, id=c['id'], result=reply(c)), True)[0], 200)
                worker.join(2); self.assertFalse(worker.is_alive()); self.assertEqual(result[0][0], 200)
                self.assertEqual(post('/next', p, True), (200, None))
                c['id'] = hexid(9999)
                with self.assertRaises(TimeoutError): executor.execute(c)
                self.assertEqual(server.store.db.execute('SELECT state FROM commands WHERE id=?', (c['id'],)).fetchone()[0], 'UNKNOWN')
                self.assertEqual(post('/run', c)[0], 409)
                self.assertEqual(post('/run', make_command('bid', self.bid_params(), 9998, host=server.store.host_epoch))[0], 409)
                self.assertIsNone(server.store.db.execute('SELECT 1 FROM commands WHERE id=?', (hexid(9998),)).fetchone())
            finally:
                server.shutdown(); server.server_close(); thread.join(2); server.store.db.close()

    def test_criteria_0_2_5_artifacts_and_historical_migration(self):
        doc = (ROOT/'docs/research/001d/001d-02/REPORT.md').read_text(encoding='utf-8')
        spec = json.loads((ROOT/'docs/research/001d/001d-02/protocol.json').read_text())
        self.assertEqual(spec['schema_version'], VERSION)
        self.assertEqual(spec['operations'], {op: {'method': m, 'path': p} for op, (m, p) in ROUTES.items() if op != 'status'})
        self.assertEqual(set(spec['command_fields']), set(make_command()))
        self.assertEqual(set(spec['response_fields']), set(reply(make_command())))
        self.assertEqual(set(spec['context_fields']), CONTEXT)
        self.assertEqual(set(spec['fence_fields']), FENCES)
        self.assertEqual(set(spec['item_fields']), ITEM)
        self.assertEqual(set(spec['auction_fields']), AUCTION)
        sample = reply(make_command())
        self.assertEqual(set(spec['result_fields']), set(sample['result']))
        self.assertEqual(set(spec['freshness_fields']), set(sample['freshness']))
        self.assertEqual(set(spec['network_fields']), set(sample['result']['network'][0]))
        for path in spec['authoritative_paths']:
            self.assertTrue((ROOT/path).is_file(), path); self.assertIn('`'+path+'`', doc)
        # The pre-change report is immutable. Migration only changes its test's
        # obsolete assertion about destinations never existing in the future.
        pub = json.loads((ROOT/'docs/research/001d/publication.json').read_text())
        entry = json.loads((ROOT/'docs/research/001d/entry.json').read_text())
        historical=historical_reader(lambda p:(ROOT/p).read_bytes())
        for p, digest in (pub['sha256'] | entry['sha256']).items():
            self.assertEqual(hashlib.sha256(historical(p)).hexdigest(), digest, p)
        live = json.loads((ROOT/'docs/research/001c/001c-06-resume-02/balance-after-opening.json').read_text())['response']
        self.assertTrue(live['success'])
        self.assertEqual(live['network'][0]['route'], '/ut/game/fc27/user/credits')
        self.assertTrue(live['network'][0]['session_header_present'])
        comparative = json.loads((ROOT/'docs/research/001c/001c-06-resume-02/comparables-2.json').read_text())['response']
        self.assertEqual(comparative['network'][0]['query']['definitionId'], 261855)
        maxbin = json.loads((ROOT/'docs/research/001c/001c-04/comparables-3.json').read_text())
        self.assertEqual(maxbin['network'][0]['query']['maxb'], 10000)
        self.assertEqual(maxbin['network'][0]['route'], ROUTES['search'][1])
        self.assertTrue(maxbin['network'][0]['session_header_present'])
        # Production cannot silently dispatch through an experimental adapter.
        for p in (ROOT/'fc_access/production_v1').glob('*.py'):
            for n in ast.walk(ast.parse(p.read_text())):
                if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(('fc_access.', 'experiments.')):
                    self.assertTrue(n.module.startswith('fc_access.production_v1'), (p, n.module))
        for phrase in ('schema 2', 'IMPLEMENTED', 'OFFLINE_VALIDATED', 'LIVE-UNVERIFIED', 'maxBuy', 'maxb', 'inclusive',
                       'identity_namespace', 'unrelated', '001d-01', 'No live EA requests', 'durable_intent', 'D2', 'D5'):
            self.assertIn(phrase, doc)


if __name__ == '__main__':
    unittest.main(verbosity=2)

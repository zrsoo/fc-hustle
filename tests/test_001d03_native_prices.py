"""001d-03: real Python service + real production JS; offline native doubles.

Independent invocation: python tests/test_001d03_native_prices.py
S2 assertions inspect retained observations only and never contact the account.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import ast
import itertools
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.production_v1.adapter import NativeAdapter
from fc_access.production_v1.contracts import command, parse_response, stamp
from fc_access.production_v1.prices import CardKey, PriceService, NATIVE_PATHS

hexid = lambda n: f'{n:032x}'
CTX = dict(account=hexid(1), persona=hexid(2), game='fc27', platform='pc', identity_namespace=hexid(3))
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class Page:
    def __init__(self):
        self.p = subprocess.Popen(['node', 'tests/native_price_rpc.cjs'], cwd=ROOT,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding='utf-8')
        self.commands = []

    def rpc(self, q):
        self.p.stdin.write(json.dumps(q)+'\n'); self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise AssertionError('native fixture exited: '+self.p.stderr.read())
        return json.loads(line)

    def attach(self, context, owner, epoch):
        return self.rpc(dict(action='attach'))

    def execute(self, c):
        self.commands.append(deepcopy(c))
        return self.rpc(c)

    def close(self):
        self.p.terminate(); self.p.communicate(timeout=5)


class NativePriceAcceptance(unittest.TestCase):
    def setup_service(self, config=None):
        p = Page(); self.addCleanup(p.close)
        p.rpc(dict(action='configure', **(config or {})))
        a = NativeAdapter(p, context=deepcopy(CTX), owner=hexid(4), epoch=1, now=lambda: NOW+timedelta(seconds=2))
        ids = itertools.count(100)
        service = PriceService(a, lambda: hexid(next(ids)))
        return p, a, service

    def test_c0_paths_runtime_dependencies_and_version(self):
        report = (ROOT/'docs/research/001d/001d-03/REPORT.md').read_text(encoding='utf-8')
        for path in ('fc_access/production_v1/prices.py', 'fc_access/production_v1/contracts.py',
                     'fc_access/production_v1/adapter.py', 'browser/production-v1/page.js'):
            self.assertIn(path, report); self.assertTrue((ROOT/path).is_file())
        for path in NATIVE_PATHS.values(): self.assertIn(path, report)
        for path in ('fc_access/bidding_v1/rules.py', 'fc_access/bidding_v1/adapter.py',
                     'fc_access/production_v1/prices.py', 'fc_access/production_v1/adapter.py'):
            source = (ROOT/path).read_text()
            for obsolete in ('reviewed_hashes', 'LIVE_VERIFIED', 'max_age=300', 'unsupported_increment_coverage', 'provenance.classification'):
                self.assertNotIn(obsolete, source)
        p, a, s = self.setup_service()
        rules = s.load(key=CardKey(7654321))
        self.assertEqual(s.version, 1)
        self.assertIs(s.validate(rules, key=CardKey(7654321), now=NOW+timedelta(days=3)), rules)
        self.assertEqual([c['operation'] for c in p.commands], ['price_helpers', 'caps'])

    def test_c1_exact_card_caps_and_absolute_helpers_not_bid_limits(self):
        p, a, s = self.setup_service({'cap': dict(definition_id=7654321, minimum=700, maximum=1500)})
        r = s.load(key=CardKey(7654321))
        self.assertEqual((r.minimum, r.maximum), (700, 1500))
        self.assertEqual((r.above(750), r.below(1500)), (800, 1400))
        self.assertEqual(r.minimum_bid(definition_id=7654321, platform='pc', starting_bid=150, current_bid=0), 150)
        self.assertEqual(r.minimum_bid(definition_id=7654321, platform='pc', starting_bid=700, current_bid=1500), 1600)
        self.assertEqual(r.floor(1999), 1900)
        self.assertEqual(p.rpc(dict(action='stats'))['calls'], ['caps'])

    def test_c2_opening_rebids_boundaries_and_integer_downward_caps(self):
        _, _, s = self.setup_service()
        r = s.load(key=CardKey(7654321))
        self.assertEqual(r.minimum_bid(definition_id=7654321, platform='pc', starting_bid=750, current_bid=0), 750)
        for value, expected in ((750, 800), (950, 1000), (1000, 1100), (9900, 10000),
                                (10000, 10250), (49750, 50000), (50000, 50500),
                                (99500, 100000), (100000, 101000), (15000000, None)):
            with self.subTest(value=value):
                self.assertEqual(r.minimum_bid(definition_id=7654321, platform='pc', starting_bid=150, current_bid=value), expected)
        for value, expected in ((1, None), (149, None), (150, 150), (151, 150), (174, 150),
                                (175, 150), (199, 150), (799, 750), (800, 800), (999, 950),
                                (1000, 1000), (1549, 1500), (1575, 1500), (1599, 1500),
                                (9999, 9900), (10000, 10000), (19999, 19750), (50049, 50000)):
            with self.subTest(floor=value): self.assertEqual(r.floor(value), expected)
        self.assertEqual(r.profitable_cap(1500, 51), 1300)  # 1500-75-51=1374
        self.assertIsNone(r.profitable_cap(1500, 1500))
        for v in (True, 1.5, -1):
            with self.assertRaises(ValueError): r.floor(v)
        with self.assertRaisesRegex(ValueError, 'illegal_starting_bid'):
            r.minimum_bid(definition_id=7654321, platform='pc', starting_bid=751, current_bid=0)

    def test_c3_fixed_listing_pair_and_no_lower_start(self):
        _, _, s = self.setup_service()
        r = s.load(key=CardKey(7654321))
        for resale, start in ((1500, 1400), (1000, 950), (10000, 9900), (50000, 49750)):
            pair = r.validate_listing(resale)
            self.assertEqual((pair.status, pair.buy_now_price, pair.starting_bid), ('LISTABLE', resale, start))
        for value, reason in ((150, 'no_legal_lower_start'), (100, 'bin_outside_card_limits'), (50500, 'bin_outside_card_limits')):
            pair = r.validate_listing(value)
            self.assertEqual((pair.status, pair.reason, pair.buy_now_price, pair.starting_bid), ('UNLISTABLE', reason, value, None))
        self.assertEqual(r.validate_listing(1575).status, 'NEEDS_RECONCILIATION')
        _, _, s = self.setup_service({'cap': dict(definition_id=7654321, minimum=1500, maximum=19999)})
        r = s.load(key=CardKey(7654321))
        self.assertEqual(r.validate_listing(1500).status, 'UNLISTABLE')
        self.assertEqual(r.validate_listing(19999).status, 'NEEDS_RECONCILIATION')
        self.assertEqual(r.validate_listing(19900).status, 'NEEDS_RECONCILIATION')
        self.assertEqual(r.validate_listing(19750).status, 'LISTABLE')

    def test_c2_c4_unavailable_mismatch_disagreement_fail_explicitly(self):
        for config, error in (({'missing':'helpers'}, 'helpers_unavailable'), ({'missing':'below'}, 'helpers_unavailable'),
                              ({'missing':'caps'}, 'service_unavailable'),
                              ({'cap':dict(definition_id=999999, minimum=150, maximum=50000)}, 'wrong_caps')):
            with self.subTest(config=config):
                p, a, s = self.setup_service(config)
                with self.assertRaisesRegex(ValueError, error): s.load(key=CardKey(7654321))
                self.assertEqual(s.validate_future_listing(key=CardKey(7654321), resale_price=1500).status, 'NEEDS_RECONCILIATION')
                self.assertNotIn('bid', p.rpc(dict(action='stats'))['calls'])
        p, a, s = self.setup_service()
        r = s.load(key=CardKey(7654321))
        with self.assertRaisesRegex(ValueError, 'identity_mismatch'):
            r.minimum_bid(definition_id=1, platform='pc', starting_bid=750, current_bid=0)
        self.assertEqual(r.validate_listing(1500, key=CardKey(1)).reason, 'rules_identity_mismatch')
        p.rpc(dict(action='configure', disagree=True))
        with self.assertRaisesRegex(ValueError, 'helper_disagreement'): r.floor(1549)
        self.assertEqual(r.validate_listing(1500).status, 'NEEDS_RECONCILIATION')
        a.fences['epoch'] += 1
        with self.assertRaisesRegex(ValueError, 'context_changed'): s.validate(r, key=r.key)

    def test_c2_c4_cap_refresh_invalidates_prior_snapshot_and_reciprocal_disagreement(self):
        p,a,s=self.setup_service()
        old=s.load(key=CardKey(7654321))
        new=s.load(key=CardKey(7654321))
        with self.assertRaisesRegex(ValueError,'caps_changed'): old.floor(750)
        self.assertEqual(new.floor(750),750)
        # Plausible monotone output still fails if reciprocal prices disagree.
        original=new.service.helper
        new.service.helper=lambda direction,value: 825 if (direction,value)==('above',750) else original(direction,value)
        with self.assertRaisesRegex(ValueError,'helper_disagreement'):
            new.minimum_bid(definition_id=7654321,platform='pc',starting_bid=750,current_bid=750)

    def test_c1_c4_helper_contract_rejects_forgery_and_network_claims(self):
        p, a, _ = self.setup_service()
        v = a.price_helpers(hexid(80), [dict(direction='above', value=750)])
        c = p.commands[-1]
        self.assertEqual(v['result']['probes'][0]['price'], 800)
        self.assertIsNone(v['freshness']['network_at'])
        changes = [lambda b:b['result'].update(version=2), lambda b:b['result'].update(above_available=False),
                   lambda b:b['result']['probes'][0].update(value=751), lambda b:b['result']['probes'][0].update(price=50),
                   lambda b:b['result']['probes'][0].update(price=True), lambda b:b['result'].update(probes=[]),
                   lambda b:b['result'].update(network=[{}]), lambda b:b['freshness'].update(network_at=NOW.isoformat()),
                   lambda b:b['freshness'].update(request_count=1), lambda b:b['context'].update(persona=hexid(90)),
                   lambda b:b['fences'].update(epoch=2), lambda b:b['result'].update(credentials='SECRET')]
        for change in changes:
            b = deepcopy(v); change(b)
            with self.assertRaises(ValueError): parse_response(b, c, now=NOW+timedelta(seconds=2))
        for params in (dict(version=True, probes=[]), dict(version=1, probes=[dict(direction='delta', value=750)]),
                       dict(version=1, probes=[dict(direction='above', value=True)]), dict(version=1, probes=[dict(direction='above', value=1)]*33)):
            b = deepcopy(c); b['params'] = params
            with self.assertRaises(ValueError): command(b)

    def test_c5_write_guards_and_no_live_writes(self):
        p, a, s = self.setup_service()
        r = s.load(key=CardKey(7654321))
        status = a.watched(hexid(60)); funds = a.balance(hexid(61)); row = status['result']['auctions'][0]
        params = dict(trade_id=row['trade_id'], item_id=row['item']['item_id'], definition_id=7654321,
                      amount=2500, minimum=2500, cap=9000, deadline=(NOW+timedelta(seconds=60)).isoformat(),
                      status_read_id=hexid(60), balance_read_id=hexid(61))
        class Journal:
            def __init__(self): self.intents=[]
            def dispatch_once(self, c, send):
                self.intents.append(c)
                return {'outcome':'NOT_DISPATCHED'} # Guard verification stops before mocked bid.
        journal = Journal()
        result = a.dispatch_intent(hexid(70), params, journal=journal, prices=r, resale_price=12000)
        self.assertEqual(result['outcome'], 'NOT_DISPATCHED')
        self.assertEqual(len(journal.intents), 1)
        for field, value in (('cap', 12000), ('item_id', 'item:'+'d'*24), ('definition_id', 1),
                             ('amount', 2600), ('balance_read_id', hexid(62))):
            changed = dict(params); changed[field] = value
            if field=='amount': changed['minimum']=value
            with self.assertRaises(ValueError): a.dispatch_intent(hexid(71), changed, journal=journal, prices=r, resale_price=12000)
        with self.assertRaisesRegex(ValueError, 'native_price_service_required'):
            a.dispatch_intent(hexid(72), params, journal=journal)
        a.responses[hexid(61)]['result']['credits']=2499
        with self.assertRaisesRegex(ValueError, 'bid_not_eligible'):
            a.dispatch_intent(hexid(73), params, journal=journal, prices=r, resale_price=12000)
        self.assertEqual(len(journal.intents),1)
        self.assertNotIn('bid', p.rpc(dict(action='stats'))['calls'])
        self.assertNotIn('list', p.rpc(dict(action='stats'))['calls'])
        # Installed HTTP Store still denies writes without a durable authorizer.
        from fc_access.production_v1.store import Store
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'db')
            try:
                owner=dict(context=deepcopy(a.context),owner=hexid(4),epoch=1); store.activate(owner)
                peer=dict(context=deepcopy(a.context),fences={**a.fences,'host_epoch':store.host_epoch})
                c={**a.envelope(hexid(75),'bid',params),'fences':peer['fences']}
                with self.assertRaisesRegex(ValueError,'durable_intent'): store.enqueue(c,peer)
            finally: store.db.close()

    def test_c6_bounded_s2_artifact_is_actual_read_only_scoped_evidence(self):
        doc=json.loads((ROOT/'docs/research/001d/001d-03/s2-checkpoint.json').read_text())
        self.assertEqual((doc['task'],doc['window'],doc['phase']),('001d-03','001D-S2','COMPLETED'))
        self.assertEqual((doc['reserved_native_requests'],doc['reserved_helper_evaluations'],doc['live_mutations'],doc['recurring_actors']),(1,8,0,0))
        self.assertLessEqual(doc['elapsed_seconds'],90)
        observations=doc['observations']
        self.assertEqual([x['command']['operation'] for x in observations],['price_helpers','caps','price_helpers'])
        for x in observations:
            parse_response(x['response'],x['command'],now=stamp(x['response']['freshness']['observed_at']))
        caps=observations[1]['response']['result']['caps']
        self.assertEqual(caps['definition_id'],doc['definition_id'])
        n=observations[1]['response']['result']['network']
        self.assertEqual(len(n),1); self.assertEqual((n[0]['method'],n[0]['status']),('GET',200))
        probes=observations[2]['response']['result']['probes']
        self.assertEqual([(p['direction'],p['value']) for p in probes],
                         [('above',750),('above',950),('above',1000),('above',9900),('below',1500),('below',1000),('below',10000),('below',caps['minimum'])])
        self.assertEqual([p['price'] for p in probes[:7]],[800,1000,1100,10000,1400,950,9900])
        self.assertEqual(doc['pair']['buy_now_price'],1500)
        self.assertEqual(doc['pair']['starting_bid'],1400)
        self.assertEqual(doc['transaction_verification'],'UNVERIFIED_NO_BID_OR_LISTING_EXECUTED')
        self.assertEqual(sum(x['response']['freshness']['request_count'] for x in observations),1)
        from unittest.mock import patch
        from fc_access.production_v1 import investigate_s2
        before=investigate_s2.CHECKPOINT.read_bytes()
        with patch.object(investigate_s2,'EdgeExecutor',side_effect=AssertionError('must_not_connect')):
            with self.assertRaisesRegex(ValueError,'window_consumed_no_replay'): investigate_s2.run()
            with self.assertRaisesRegex(ValueError,'existing_checkpoint_preserved'): investigate_s2.prepare()
        self.assertEqual(investigate_s2.CHECKPOINT.read_bytes(),before)

    def test_c3_c5_legacy_listing_rejects_pair_and_profit_failures_before_reservation(self):
        from dataclasses import replace
        from test_durability_v1 import HarnessTests, OwnedProof
        from test_bidding_v1 import status, fresh, State, cid
        case=HarnessTests();case.setUp();self.addCleanup(case.doCleanups)
        harness,adapter=case.harness()
        won=replace(status(state=State.LEADING,current=150),state=State.WON,
                    owned_item_id=status().identity.item_id,paid=150)
        proof=OwnedProof(won.identity,150,True,fresh(810))
        sends=[]
        for value in (150,1575,20100):
            with self.assertRaisesRegex(ValueError,'invalid_listing_price'):
                harness.won_action_once(cid(300),'list',won,proof,rules=case.rules,price=value,
                                        send=lambda:sends.append(1),readback=lambda:(True,fresh(820)))
        with self.assertRaisesRegex(ValueError,'unprofitable_listing'):
            harness.won_action_once(cid(301),'list',replace(won,current_bid=1000,paid=1000),replace(proof,paid=1000),
                                    rules=case.rules,price=1000,send=lambda:sends.append(1),readback=lambda:(True,fresh(820)))
        self.assertEqual(sends,[])
        self.assertEqual(harness.db.execute('SELECT COUNT(*) FROM actions').fetchone()[0],0)


if __name__=='__main__': unittest.main(verbosity=2)

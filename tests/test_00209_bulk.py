"""Offline production bulk acceptance: real protocol/SQLite and native page VM.

No account/session or fresh EA inventory is needed. Only sealed transaction
evidence is hashed; mutable implementation files are tested behaviorally.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from actors_fixture import ActorPage, Clock, CONTEXT
from native_price_fixture import auction
from fc_access.production_v1.foundation import Foundation, JournalAuthority
from fc_access.production_v1.bulk import BulkTransfer, pending, parameters
from fc_access.production_v1.contracts import BULK, command, parse_response
from fc_access.production_v1.store import Store
from fc_access.bidding_v1 import capacity


def inventory():
    rows = [auction(123+n, 15000+n*250, n+1) for n in range(6)]
    for n, r in enumerate(rows):
        r.update(trade_state='closed' if n < 2 else 'expired' if n < 4 else 'active',
                 current_bid=15000 if n < 2 else 0, expires=-1 if n < 4 else 100000,
                 bid_state='none', native_is_won=False)
    return rows


class BulkPage(ActorPage):
    def __init__(self, directory, clock):
        super().__init__(directory, clock)
        self.transfer_items = inventory()
        self.writes = []
        self.effect, self.timeout, self.partial = True, False, False
        self.corrupt = lambda c: None
        self.bad_proof = None
        self.block_readback = False
        self.response_error = None

    def execute(self, c):
        try:
            return super().execute(c)
        except Exception:
            # Model the HTTP service's finite delivery timeout/rejection, rather
            # than leave a synthetic read permanently DELIVERED in the double.
            self.store.uncertain(c['id'])
            raise

    def project_response(self, c, v):
        v = super().project_response(c, v)
        op = c['operation']
        if op == 'transfer_list':
            if self.block_readback and self.writes: raise TimeoutError('readback unavailable')
            v['coverage']['bulk'] = [dict(item_id=r['item']['item_id'], trade_owner=True,
                sold=r['trade_state']=='closed', expired=r['trade_state']=='expired',
                active=r['trade_state']=='active') for r in v['result']['auctions']]
            if self.bad_proof: self.bad_proof(v)
        if op in BULK:
            # A separate connection sees the committed intent AND claim before
            # this synthetic native effect, like the actual localhost service.
            assert JournalAuthority(self.directory/'journal.sqlite3')(c)
            self.writes.append(deepcopy(c))
            v['result']['network'][0]['body_empty'] = True
            if op == 'clear_sold':
                # One native DELETE with an internal refresh, then the executor
                # obtains its own independent Transfer List command.
                read = deepcopy(v['result']['network'][0])
                read.update(method='GET', path='/ut/game/fc27/tradepile')
                v['result']['network'].append(read)
                v['freshness']['request_count'] = 2
            targets = c['params']['expected_item_ids']
            if self.partial: targets = targets[:1]
            if self.effect:
                if op == 'clear_sold':
                    self.transfer_items = [r for r in self.transfer_items if r['item']['item_id'] not in targets]
                else:
                    for n, r in enumerate(self.transfer_items):
                        if r['item']['item_id'] in targets:
                            r.update(trade_state='active', trade_id=f'trade:{900+n:024x}', expires=3600)
            self.corrupt(c)
            if self.response_error:
                v['result'].update(success=False,error=self.response_error)
            if self.timeout:
                self.store.uncertain(c['id'])
                raise TimeoutError('lost response')
        return v


class Acceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.clock = Clock(); self.page = BulkPage(self.path, self.clock)
        self.f = self.open()
        self.addCleanup(self.page.close); self.addCleanup(lambda: self.f.close())

    def open(self):
        return Foundation(self.page, context=CONTEXT, journal_path=self.path/'journal.sqlite3',
            fixture=True, now=self.clock.now, clock=self.clock.monotonic, sleep=self.clock.sleep)

    def restart(self):
        self.f.close(); self.f = self.open()

    def relist_ready(self):
        self.page.transfer_items = self.page.transfer_items[2:]

    def test_c0_c2_c3_both_production_operations_account_wide_and_independent(self):
        original = deepcopy(self.page.transfer_items)
        self.assertEqual(self.f.bulk('clear_sold')['status'], 'CONFIRMED')
        self.assertEqual(self.page.transfer_items, original[2:])
        self.assertEqual(self.f.bulk('relist_all')['status'], 'CONFIRMED')
        self.assertEqual([c['operation'] for c in self.page.writes], ['clear_sold', 'relist_all'])
        for c in self.page.writes:
            p = c['params']
            self.assertNotIn('duration', p); self.assertNotIn('duration_seconds', p)
            self.assertEqual(len(p['expected_item_ids']), 2)
            self.assertTrue(JournalAuthority(self.f.journal_path).reconciled(c))
            events = [e for e in self.f.registry.events() if e.get('command_id') == c['id']]
            reasons = [e['reason'] for e in events if e['kind']=='BULK_TRANSFER']
            self.assertEqual(reasons, ['INTENT_DURABLE','DISPATCH_CLAIM','ACKNOWLEDGED','VERIFIED'])
            intent, verified = next(e for e in events if e.get('reason')=='INTENT_DURABLE'), events[-1]
            self.assertTrue(intent['account_wide'] and intent['includes_manual_items'])
            self.assertNotIn(verified['read_id'], {c['id'], p['before_read_id']})
            self.assertEqual(verified['readback']['operation'], 'transfer_list')
        # These fixture cards have no actor policy/enrollment: all manual cards
        # are included. Physical account occupancy remains complete and accurate.
        self.assertEqual(capacity.status(self.f.journal,self.f.registry.scope,now=self.clock.now())['occupied'],4)
        for a, b in zip(original[2:4], self.page.transfer_items[:2]):
            self.assertEqual(a['item'], b['item'])
            self.assertEqual((a['starting_bid'],a['buy_now_price']), (b['starting_bid'],b['buy_now_price']))
            self.assertEqual(b['expires'],3600); self.assertNotEqual(a['trade_id'], b['trade_id'])
        self.assertEqual(self.page.transfer_items[2:], original[4:])

    def test_c1_c5_consumed_sealed_research_and_empty_inventory_no_research_calls(self):
        from validate_bulk_transfer_evidence import validate
        validate()  # verifies only sealed captures/logs, including consumed slots
        self.page.transfer_items = []
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('threading.Thread.start', side_effect=AssertionError('recurring job forbidden')), \
             patch('subprocess.Popen', side_effect=AssertionError('research process forbidden')):
            service = BulkTransfer(self.f)
            self.assertEqual(self.page.calls, [])
            for op in BULK: self.assertEqual(service.execute(op)['status'], 'SKIPPED')
            count = len(self.page.calls); self.clock.sleep(7200)
            self.assertEqual(len(self.page.calls),count)
        self.assertEqual(self.page.writes, [])
        self.assertEqual({c['operation'] for c in self.page.calls}, {'transfer_list'})
        self.assertEqual(pending(self.f.journal,self.f.registry.scope),[])

    def test_c2_incomplete_unowned_unclassified_and_changed_predicates_fail_before_intent(self):
        for change in [lambda v:v['coverage'].update(complete=False,has_more=True,transfer_list=dict(
                          reason='TRANSFER_LIST_TRUNCATED',wire_count=6,callback_count=6,repository_count=6,repository_end_of_list=False)),
                       lambda v:v['coverage'].pop('bulk'),
                       lambda v:v['coverage']['bulk'][0].update(trade_owner=False),
                       lambda v:v['coverage']['bulk'][0].update(sold=False),
                       lambda v:v['result']['auctions'][0].update(trade_state='inactive'),
                       lambda v:v['result']['auctions'][0]['item'].update(item_id='item:'+'f'*24)]:
            with self.subTest(change=change):
                self.page.bad_proof = change
                with self.assertRaises((ValueError,TimeoutError)): self.f.bulk('clear_sold')
                self.assertEqual(self.page.writes, [])
                self.assertEqual(pending(self.f.journal,self.f.registry.scope), [])
        self.page.bad_proof = None
        with self.assertRaisesRegex(ValueError,'relist_with_sold_unproven'): self.f.bulk('relist_all')

    def test_c2_intent_only_failure_never_dispatches_on_restart(self):
        def fail(service, stage):
            if stage=='intent': raise OSError('crash seam')
        with patch.object(BulkTransfer,'checkpoint',fail):
            with self.assertRaises(OSError): self.f.bulk('clear_sold')
        self.assertEqual(self.page.writes,[])
        self.restart()
        self.assertEqual(self.f.bulk('clear_sold')['status'],'RECONCILIATION_ONLY')
        self.assertEqual(self.page.writes,[])

    def test_c2_dispatch_age_and_takeover_are_fenced(self):
        def age(service, stage):
            if stage=='claimed': self.clock.sleep(31)
        with patch.object(BulkTransfer,'checkpoint',age):
            with self.assertRaises(ValueError): self.f.bulk('clear_sold')
        self.assertEqual(self.page.writes,[])
        self.restart(); self.f.bulk('clear_sold'); self.assertEqual(self.page.writes,[])
        self.assertEqual(len(pending(self.f.journal,self.f.registry.scope)),1)

    def test_c2_epoch_takeover_after_durable_claim_blocks_send(self):
        def takeover(service, stage):
            if stage=='claimed': self.f.journal.session(self.f.registry.scope,'9'*32)
        with patch.object(BulkTransfer,'checkpoint',takeover):
            with self.assertRaisesRegex(ValueError,'stale_owner_or_epoch'): self.f.bulk('clear_sold')
        self.assertEqual(self.page.writes,[])
        self.restart(); self.f.bulk('clear_sold'); self.assertEqual(self.page.writes,[])

    def test_c4_partial_and_ack_without_effect_are_never_retried(self):
        self.page.partial=True
        self.assertEqual(self.f.bulk('clear_sold')['status'],'UNRESOLVED')
        self.restart()
        for _ in range(3): self.f.bulk('clear_sold')
        self.assertEqual(len(self.page.writes),1)
        self.assertEqual(len(pending(self.f.journal,self.f.registry.scope)),1)
        self.assertEqual(len(self.f.registry.current()['unresolved']),1)
        self.assertEqual(capacity.status(self.f.journal,self.f.registry.scope,now=self.clock.now())['occupied'],6)
        with self.assertRaisesRegex(ValueError,'read_cannot_write'): self.f.read('relist_all')

    def test_c4_lost_response_reconciles_without_retry(self):
        self.page.timeout=True
        self.assertEqual(self.f.bulk('clear_sold')['status'],'CONFIRMED')
        self.assertEqual(self.f.bulk('relist_all')['status'],'CONFIRMED')
        self.assertEqual(len(self.page.writes),2)
        self.restart()
        for op in BULK: self.assertEqual(self.f.bulk(op)['status'],'SKIPPED')
        self.assertEqual(len(self.page.writes),2)

    def test_c2_c4_restart_readback_failure_keeps_intent_then_read_only_recovery(self):
        self.page.block_readback=True
        self.assertEqual(self.f.bulk('clear_sold')['status'],'UNRESOLVED')
        self.restart(); self.page.block_readback=False
        self.assertEqual(self.f.bulk('relist_all')['status'],'RECONCILIATION_ONLY')
        self.assertEqual(len(self.page.writes),1)
        self.assertEqual(pending(self.f.journal,self.f.registry.scope),[])

    def test_c3_c4_changed_duration_prices_identity_or_unaffected_row_stays_closed(self):
        self.relist_ready()
        def corrupt(c): self.page.transfer_items[0]['expires']=7200
        self.page.corrupt=corrupt
        self.assertEqual(self.f.bulk('relist_all')['status'],'UNRESOLVED')
        self.assertEqual(self.f.journal.db.execute('SELECT incompatible FROM bulk_writes_v1').fetchone(),(1,))
        self.page.transfer_items[0]['expires']=3600
        self.restart()
        for _ in range(3): self.f.bulk('relist_all')
        self.assertEqual(len(self.page.writes),1)
        self.assertFalse(JournalAuthority(self.f.journal_path).reconciled(self.page.writes[0]))

    def test_c3_c4_negative_readbacks_each_in_fresh_workspace(self):
        changes=[lambda p:p.transfer_items[0].update(starting_bid=500),
                 lambda p:p.transfer_items[0].update(buy_now_price=500),
                 lambda p:p.transfer_items[0]['item'].update(item_id='item:'+'d'*24),
                 lambda p:p.transfer_items[0]['item'].update(definition_id=999),
                 lambda p:p.transfer_items[0].update(expires=3599),
                 lambda p:p.transfer_items[0].update(trade_id=p.transfer_items[1]['trade_id']),
                 lambda p:p.transfer_items[-1].update(buy_now_price=500),
                 lambda p:p.transfer_items.pop(),
                 lambda p:p.transfer_items.append(inventory()[0])]
        for n, change in enumerate(changes):
            with self.subTest(n=n):
                directory=self.path/str(n);directory.mkdir()
                p=BulkPage(directory,self.clock);p.transfer_items=p.transfer_items[2:]
                f=Foundation(p,context=CONTEXT,journal_path=directory/'journal.sqlite3',fixture=True,
                    now=self.clock.now,clock=self.clock.monotonic,sleep=self.clock.sleep)
                p.corrupt=lambda c:change(p)
                try:
                    self.assertEqual(f.bulk('relist_all')['status'],'UNRESOLVED')
                    for _ in range(2):f.bulk('relist_all')
                    self.assertEqual(len(p.writes),1)
                    self.assertEqual(len(pending(f.journal,f.registry.scope)),1)
                finally:f.close();p.close()

    def test_c0_c2_transport_rejects_forged_intents_extra_fields_and_all_fences(self):
        before=BulkTransfer(self.f).inventory()
        c=self.f.adapter.envelope(self.f.ids(),'clear_sold',parameters(before,'clear_sold'))
        self.assertFalse(JournalAuthority(self.f.journal_path)(c))
        with self.assertRaisesRegex(ValueError,'mutation_requires_durable_intent'):self.page.store.enqueue(c,self.page.peer)
        for field in ('duration','duration_seconds','item_id'):
            bad=deepcopy(c);bad['params'][field]=3600
            with self.assertRaises(ValueError):command(bad)
        self.page.effect=False
        self.f.bulk('clear_sold')
        c=self.page.writes[0]
        for where in ('context','fences'):
            for field in c[where]:
                bad=deepcopy(c);bad[where][field]=bad[where][field]+1 if field=='epoch' else '9'*32
                if field in {'game','platform'}:
                    with self.assertRaises(ValueError):JournalAuthority(self.f.journal_path)(bad)
                else:self.assertFalse(JournalAuthority(self.f.journal_path)(bad),field)
        with self.assertRaisesRegex(ValueError,'mutation_requires_durable_intent'):self.page.store.enqueue(c,self.page.peer)
        # Durable transport blocks a distinct write while the bulk is unresolved.
        other=deepcopy(c);other['id']=self.f.ids()
        with patch.object(self.page.store,'authorize_bid',lambda c:True):
            with self.assertRaisesRegex(ValueError,'duplicate_command'):self.page.store.enqueue(c,self.page.peer)
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):self.page.store.enqueue(other,self.page.peer)

    def test_c2_durable_commit_failures_do_not_grant_dispatch_or_confirmation(self):
        original=BulkTransfer.event
        def fail_intent(service,reason,**data):
            original(service,reason,**data)
            if reason=='INTENT_DURABLE':raise OSError('synthetic journal failure')
        with patch.object(BulkTransfer,'event',fail_intent):
            with self.assertRaises(OSError):self.f.bulk('clear_sold')
        self.assertEqual(self.page.writes,[])
        self.assertEqual(pending(self.f.journal,self.f.registry.scope),[])
        def fail_verified(service,reason,**data):
            original(service,reason,**data)
            if reason=='VERIFIED':raise OSError('synthetic readback commit failure')
        with patch.object(BulkTransfer,'event',fail_verified):
            with self.assertRaises(OSError):self.f.bulk('clear_sold')
        self.assertEqual(len(self.page.writes),1)
        self.assertEqual(len(pending(self.f.journal,self.f.registry.scope)),1)
        self.f.bulk('clear_sold')
        self.assertEqual(len(self.page.writes),1)
        self.assertEqual(pending(self.f.journal,self.f.registry.scope),[])

    def test_c4_relist_partial_unknown_and_no_effect_ack_do_not_authorize_more_writes(self):
        self.relist_ready();self.page.partial=True;self.page.timeout=True
        self.assertEqual(self.f.bulk('relist_all')['status'],'UNRESOLVED')
        self.restart()
        for _ in range(3):self.f.bulk('relist_all')
        self.assertEqual(len(self.page.writes),1)
        self.assertEqual(len(pending(self.f.journal,self.f.registry.scope)),1)

    def test_c4_success_ack_without_native_effect_stays_unresolved(self):
        self.page.effect=False
        self.assertEqual(self.f.bulk('clear_sold')['status'],'UNRESOLVED')
        self.restart()
        for _ in range(3):self.f.bulk('clear_sold')
        self.assertEqual(len(self.page.writes),1)
        self.assertEqual(len(pending(self.f.journal,self.f.registry.scope)),1)

    def test_c4_explicit_wire_contract_change_cannot_be_cleared_by_good_readback(self):
        self.page.response_error='bulk_contract_changed'
        self.assertEqual(self.f.bulk('clear_sold')['status'],'UNRESOLVED')
        self.assertEqual(len(self.page.transfer_items),4,'physical side effect did occur')
        self.restart()
        for _ in range(3):self.f.bulk('clear_sold')
        self.assertEqual(len(self.page.writes),1)
        self.assertEqual(self.f.journal.db.execute('SELECT incompatible FROM bulk_writes_v1').fetchone(),(1,))
        self.assertEqual(len(pending(self.f.journal,self.f.registry.scope)),1)

    def test_c0_c4_changed_wire_semantics_rejected_by_production_parser(self):
        self.f.bulk('clear_sold')
        c=self.page.writes[0];v=self.page.store.result(c['id'])
        for alter in [lambda v:v['result']['network'].append(deepcopy(v['result']['network'][0])),
                      lambda v:v['result']['network'][0].update(body_empty=False),
                      lambda v:v['result']['network'][0].update(query={'num':1}),
                      lambda v:v['result']['network'][0].update(method='POST'),
                      lambda v:v['result']['network'][0].update(path='/ut/game/fc27/item'),
                      lambda v:v['result']['network'][0].update(session_header_present=False)]:
            bad=deepcopy(v);alter(bad);bad['freshness']['request_count']=len(bad['result']['network'])
            with self.assertRaises(ValueError):parse_response(bad,c,now=self.clock.now(),source='fixture')

    def test_c0_c2_c3_c4_c5_deployed_javascript_contract_and_worker(self):
        result=subprocess.run(['node','tests/production_bulk_checks.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS',result.stdout)

    def test_c2_priority_serialization_uses_shared_scheduler(self):
        f=self.f
        before=BulkTransfer(f).inventory()
        maintenance=f.adapter.envelope(f.ids(),'clear_sold',parameters(before,'clear_sold'))
        watched=f.adapter.envelope(f.ids(),'watched',{})
        f.executor.submit(maintenance);f.executor.submit(watched)
        self.assertEqual(f.executor.run_one(),watched['id'])
        self.assertEqual(f.executor.scheduler.concurrency,1)
        self.assertEqual(f.executor.run_one(),maintenance['id'])
        # This scheduler test has no durable intent and therefore sends no write.
        self.assertEqual(self.page.writes,[])

    def test_c4_real_process_crashes_all_durable_boundaries(self):
        for op in BULK:
            for stage in ('intent','claimed','sent','ack','readback'):
                with self.subTest(op=op,stage=stage):
                    directory=self.path/(op+'-'+stage);directory.mkdir()
                    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--crash',str(directory),op,stage],
                        cwd=ROOT,capture_output=True,text=True,timeout=20)
                    self.assertEqual(result.returncode,23,result.stdout+result.stderr)
                    p=BulkPage(directory,self.clock)
                    evidence=directory/'effect.json'
                    if evidence.exists():p.transfer_items=json.loads(evidence.read_text())
                    elif op=='relist_all':p.transfer_items=p.transfer_items[2:]
                    f=Foundation(p,context=CONTEXT,journal_path=directory/'journal.sqlite3',fixture=True,
                        now=self.clock.now,clock=self.clock.monotonic,sleep=self.clock.sleep)
                    try:
                        self.clock.sleep(1)
                        f.bulk(op)
                        self.assertEqual(p.writes,[])
                        state=f.journal.db.execute('SELECT state FROM bulk_writes_v1').fetchone()[0]
                        self.assertEqual(state,'RECONCILED' if stage in {'sent','ack','readback'} else
                            'INTENT' if stage=='intent' else 'UNKNOWN')
                    finally:f.close();p.close()


def crash_worker(directory,op,stage):
    import os
    directory=Path(directory);clock=Clock();p=BulkPage(directory,clock)
    if op=='relist_all':p.transfer_items=p.transfer_items[2:]
    f=Foundation(p,context=CONTEXT,journal_path=directory/'journal.sqlite3',fixture=True,
        now=clock.now,clock=clock.monotonic,sleep=clock.sleep)
    p.corrupt=lambda c:(directory/'effect.json').write_text(json.dumps(p.transfer_items))
    def checkpoint(self,value):
        if value==stage:os._exit(23)
    with patch.object(BulkTransfer,'checkpoint',checkpoint):f.bulk(op)
    raise AssertionError('crash seam not reached')


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--crash':crash_worker(*sys.argv[2:])
    else:unittest.main(verbosity=2)

"""Deterministic OFFLINE bulk contracts, guards and crash-safe dispatch tests."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.bulk_transfer_v1.contracts import groups, preflight, reconcile
from fc_access.bulk_transfer_v1.server import Store, validate_command, validate_response
from fc_access.production_v1.store import Store as ProductionStore

NOW=datetime(2030,1,1,tzinfo=timezone.utc)
CONTEXT=dict(account='1'*32,persona='2'*32,identity_namespace='3'*32,game='fc27',platform='pc')


def row(n,state='active',bid=0):
    return dict(trade_id=f'trade:{n:024x}',item_id=f'item:{n:024x}',definition_id=123+n,
        starting_bid=700,current_bid=bid,buy_now_price=1500,expires=3600 if state=='active' else -1,
        trade_state=state,bid_state='none',trade_owner=True)


def rows():
    return [row(1,'closed',1500),row(2,'closed',1500),row(3,'expired'),row(4),row(5)]


def network(method='GET',path='/ut/game/fc27/tradepile',at=NOW):
    return dict(host='utas.mob.v1.prd.futc-ext.gcp.ea.com',method=method,path=path,query_empty=True,
        request_body=None,body_kind='empty',status=200,session_header_present=True,
        started_at=at.isoformat(),ended_at=(at+timedelta(milliseconds=100)).isoformat(),response=dict(kind='empty'))


def response(c,inventory=None):
    v=dict(schema=2,command_id=c['id'],operation=c['operation'],context=c['context'],fences=c['fences'],
        observed_at=NOW.isoformat(),success=True,error=None,status=200,network=[network()],sources=[],inventory=None,callback=None)
    if inventory is not None:
        v['inventory']=dict(rows=inventory,occupancy=len(inventory),capacity=100,complete=True)
    if c['operation'] in ('bulk_clear_sold','bulk_relist_all'):
        method,path=('DELETE','/ut/game/fc27/trade/sold') if c['operation']=='bulk_clear_sold' else ('PUT','/ut/game/fc27/auctionhouse/relist')
        v['network']=[network(method,path)]
        v['callback']=dict(success=True,status=200,error_code=None,item_ids=[])
    return v


def params(before,cid,op):
    g=groups(before)
    p=dict(before_read_id=cid,expected_item_ids=[r['item_id'] for r in g['sold' if op=='bulk_clear_sold' else 'expired']],
        expected_inventory_ids=[r['item_id'] for r in before],expected_sold_count=len(g['sold']),expected_expired_count=len(g['expired']))
    if op=='bulk_relist_all':p['duration_seconds']=3600
    return p


class BulkContracts(unittest.TestCase):
    def test_native_states_filter_only_sold_and_expired_owned_entries(self):
        g=groups(rows());self.assertEqual({k:len(v) for k,v in g.items()},dict(sold=2,expired=1,other=2))
        for change in (dict(trade_owner=False),dict(current_bid=0),dict(trade_state='active')):
            altered=rows();altered[0].update(change)
            with self.assertRaisesRegex(ValueError,'authorized_scope'):preflight('bulk_clear_sold',altered)
        self.assertEqual(len(preflight('bulk_clear_sold',rows())),2)

    def test_actual_five_sold_four_expired_inventory_is_outside_original_authorization(self):
        more=[row(n,'closed',1000) for n in range(1,6)]+[row(n,'expired') for n in range(6,10)]+[row(n) for n in range(10,13)]
        self.assertEqual({k:len(v) for k,v in groups(more).items()},dict(sold=5,expired=4,other=3))
        for op in ('bulk_clear_sold','bulk_relist_all'):
            with self.assertRaisesRegex(ValueError,'authorized_scope'):preflight(op,more)

    def test_clear_reconciliation_requires_exact_removal_and_unchanged_unsold(self):
        before=rows();after=deepcopy(before[2:]);after[-1]['expires']-=1
        t=dict(mutation_started=NOW.isoformat(),mutation_ended=NOW.isoformat(),read_started=NOW.isoformat(),read_ended=(NOW+timedelta(seconds=1)).isoformat())
        self.assertEqual(reconcile('bulk_clear_sold',before,after,**t)['occupancy_delta'],-2)
        for change in (lambda r:r.pop(),lambda r:r.append(before[0]),lambda r:r[0].update(starting_bid=800),lambda r:r[0].update(trade_state='active')):
            bad=deepcopy(after);change(bad)
            with self.assertRaises(ValueError):reconcile('bulk_clear_sold',before,bad,**t)

    def test_relist_preserves_physical_item_and_prices_requires_one_hour(self):
        before=rows()[2:];after=deepcopy(before)
        after[0].update(trade_id='trade:'+'f'*24,trade_state='active',expires=3598)
        t=dict(mutation_started=NOW.isoformat(),mutation_ended=(NOW+timedelta(seconds=1)).isoformat(),
               read_started=(NOW+timedelta(seconds=2)).isoformat(),read_ended=(NOW+timedelta(seconds=3)).isoformat())
        out=reconcile('bulk_relist_all',before,after,**t)
        self.assertEqual(out['relisted'][0]['item_id'],before[0]['item_id'])
        self.assertEqual(out['relisted'][0]['new_trade_id'],'trade:'+'f'*24)
        for change in (dict(expires=7200),dict(expires=3500),dict(starting_bid=750),dict(buy_now_price=1400),dict(item_id='item:'+'e'*24),dict(current_bid=750)):
            bad=deepcopy(after);bad[0].update(change)
            with self.assertRaises(ValueError):reconcile('bulk_relist_all',before,bad,**t)
        with self.assertRaisesRegex(ValueError,'fresh_readback'):reconcile('bulk_relist_all',before,after,**{**t,'read_started':(NOW-timedelta(seconds=1)).isoformat()})

    def test_multiple_expired_fixture_is_not_claimed_as_live_proof(self):
        before=[row(1,'expired'),row(2,'expired')];after=deepcopy(before)
        for r in after:r.update(trade_state='active',expires=3599,trade_id='trade:'+r['item_id'][5:])
        t=dict(mutation_started=NOW.isoformat(),mutation_ended=NOW.isoformat(),read_started=NOW.isoformat(),read_ended=(NOW+timedelta(seconds=1)).isoformat())
        self.assertEqual(len(reconcile('bulk_relist_all',before,after,**t)['relisted']),2)


class BulkJournal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'window.sqlite'
        self.store=Store(self.path);self.addCleanup(self.store.db.close);self.store.now=lambda:NOW
        self.owner=dict(context=CONTEXT,owner='4'*32,epoch=1);self.store.activate(self.owner)
        self.peer=dict(context=CONTEXT,fences=dict(owner='4'*32,epoch=1,host_epoch=self.store.host_epoch,worker_epoch='5'*32,document='6'*32))
    def command(self,n,op='bulk_inventory',p=None):
        return dict(schema=2,id=f'{n:032x}',operation=op,params=p or {},**deepcopy(self.peer))
    def read(self,n=1,items=None,at=None):
        c=self.command(n);self.store.enqueue(c,self.peer);self.store.claim(self.peer)
        v=response(c,rows() if items is None else items)
        if at is not None:v.update(observed_at=at.isoformat(),network=[network(at=at)])
        self.store.finish(self.peer,c['id'],v);return c
    def test_intent_before_claim_duplicate_operation_and_restart_never_redispatch(self):
        read=self.read();c=self.command(2,'bulk_clear_sold',params(rows(),read['id'],'bulk_clear_sold'))
        self.store.enqueue(c,self.peer)
        self.assertEqual(self.store.db.execute('SELECT state FROM bulk_intents').fetchone(),('INTENT_DURABLE',))
        self.assertEqual(self.store.claim(self.peer),c)
        self.assertIsNone(self.store.claim(self.peer))
        self.store.finish(self.peer,c['id'],response(c))
        with self.assertRaisesRegex(ValueError,'consumed_no_retry'):
            self.store.enqueue(self.command(3,'bulk_clear_sold',c['params']),self.peer)
        with self.assertRaisesRegex(ValueError,'independently_confirmed'):
            self.store.enqueue(self.command(4,'bulk_relist_all',params(rows()[2:],read['id'],'bulk_relist_all')),self.peer)
        reopened=Store(self.path);self.addCleanup(reopened.db.close)
        self.assertEqual(reopened.db.execute('SELECT state FROM bulk_intents').fetchone(),('UNKNOWN',))
        self.assertEqual(reopened.db.execute('SELECT COUNT(*) FROM bulk_intents').fetchone(),(1,))
    def test_unconfirmed_ack_requires_independent_readback_and_preserves_events(self):
        read=self.read();c=self.command(2,'bulk_clear_sold',params(rows(),read['id'],'bulk_clear_sold'))
        self.store.enqueue(c,self.peer);self.store.claim(self.peer);self.store.finish(self.peer,c['id'],response(c))
        self.assertEqual(self.store.db.execute('SELECT state FROM bulk_intents').fetchone(),('ACKNOWLEDGED_UNRECONCILED',))
        after=self.read(3,rows()[2:],at=NOW+timedelta(seconds=1))
        self.assertEqual(self.store.reconcile('bulk_clear_sold',after['id'])['outcome'],'CONFIRMED')
        self.assertEqual(self.store.db.execute('SELECT state FROM bulk_intents').fetchone(),('CONFIRMED',))
        with self.assertRaisesRegex(Exception,'append_only'):self.store.db.execute('DELETE FROM events')
    def test_unexpected_counts_stale_wrong_fences_and_price_duration_contracts_block(self):
        more=rows()+[row(6,'expired')];read=self.read(items=more)
        c=self.command(2,'bulk_clear_sold',params(more,read['id'],'bulk_clear_sold'))
        with self.assertRaisesRegex(ValueError,'authorized_scope'):self.store.enqueue(c,self.peer)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM bulk_intents').fetchone(),(0,))
        read=self.read(3);c=self.command(4,'bulk_clear_sold',params(rows(),read['id'],'bulk_clear_sold'))
        self.store.now=lambda:NOW+timedelta(seconds=31)
        with self.assertRaisesRegex(ValueError,'stale_prewrite'):self.store.enqueue(c,self.peer)
        c['fences']['document']='a'*32
        with self.assertRaisesRegex(ValueError,'wrong_peer'):self.store.enqueue(c,self.peer)
        q=self.command(5,'bulk_relist_all',params(rows()[2:],read['id'],'bulk_relist_all'));q['params']['duration_seconds']=7200
        with self.assertRaisesRegex(ValueError,'one_hour'):validate_command(q)
    def test_ambiguous_extra_request_wrong_route_and_private_fields_are_rejected(self):
        r=self.read();c=self.command(2,'bulk_clear_sold',params(rows(),r['id'],'bulk_clear_sold'))
        for change in (lambda v:v['network'].append(deepcopy(v['network'][0])),
                       lambda v:v['network'][0].update(path='/ut/game/fc27/tradepile'),
                       lambda v:v['network'][0].update(session_header_present=False),
                       lambda v:v.update(token='private'),lambda v:v['callback'].update(raw_body='private')):
            v=response(c);change(v)
            with self.assertRaises(ValueError):validate_response(v,c)
    def test_production_default_rejects_bulk_dialect(self):
        store=ProductionStore(Path(self.tmp.name)/'production.sqlite');self.addCleanup(store.db.close)
        store.activate(self.owner)
        peer=deepcopy(self.peer);peer['fences']['host_epoch']=store.host_epoch
        c=self.command(9,'bulk_clear_sold',params(rows(),'1'*32,'bulk_clear_sold'));c['fences']=peer['fences']
        with self.assertRaisesRegex(ValueError,'unsupported_operation'):store.enqueue(c,peer)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM commands').fetchone(),(0,))
    def test_explicit_user_revision_preserves_consumed_budgets_and_cannot_reset_intents(self):
        more=[row(n,'closed',1000) for n in range(1,6)]+[row(n,'expired') for n in range(6,10)]+[row(10)]
        read=self.read(items=more)
        before=self.store.db.execute('SELECT * FROM research_window').fetchone()
        self.store.authorize_revision(5,4)
        self.assertEqual(self.store.db.execute('SELECT * FROM research_window').fetchone(),before)
        c=self.command(2,'bulk_clear_sold',params(more,read['id'],'bulk_clear_sold'))
        self.store.enqueue(c,self.peer)
        with self.assertRaisesRegex(ValueError,'revision_after_intent'):
            self.store.authorize_revision(2,1)
        reopened=Store(self.path);self.addCleanup(reopened.db.close)
        self.assertEqual(reopened.db.execute('SELECT sold,expired FROM bulk_authorization').fetchone(),(5,4))
        self.assertEqual(reopened.db.execute('SELECT * FROM research_window').fetchone(),before)
    def test_requested_login_selection_quarantines_previous_inventory_without_reset(self):
        read=self.read();before=self.store.db.execute('SELECT * FROM research_window').fetchone()
        selected=dict(context={**CONTEXT, 'account':'9'*32,'identity_namespace':'a'*32},owner='b'*32,epoch=2)
        self.store.select_account_context(selected)
        self.assertEqual(self.store.db.execute('SELECT * FROM research_window').fetchone(),before)
        peer=dict(context=selected['context'],fences={**self.peer['fences'],'owner':selected['owner'],'epoch':2})
        c=self.command(2,'bulk_clear_sold',params(rows(),read['id'],'bulk_clear_sold'));c.update(peer)
        with self.assertRaisesRegex(ValueError,'same_context_inventory'):
            self.store.enqueue(c,peer)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM bulk_intents').fetchone(),(0,))
    def test_lost_native_callback_is_unknown_until_a_separate_read_proves_removal(self):
        read=self.read();c=self.command(2,'bulk_clear_sold',params(rows(),read['id'],'bulk_clear_sold'))
        self.store.enqueue(c,self.peer);self.store.claim(self.peer)
        lost=response(c);lost.update(success=False,error='native_timeout_no_retry',callback=None,status=None)
        self.store.finish(self.peer,c['id'],lost)
        self.assertEqual(self.store.db.execute('SELECT state FROM bulk_intents').fetchone(),('UNKNOWN',))
        with self.assertRaisesRegex(ValueError,'consumed_no_retry'):
            self.store.enqueue(self.command(3,'bulk_clear_sold',c['params']),self.peer)
        after=self.read(4,rows()[2:],at=NOW+timedelta(seconds=1))
        self.assertEqual(self.store.reconcile('bulk_clear_sold',after['id'])['outcome'],'CONFIRMED')
        owner=self.store.owner();window=self.store.db.execute('SELECT * FROM research_window').fetchone()
        journal=Store.open_reconciler(self.path)
        try:
            self.assertEqual(journal.db.execute('SELECT * FROM research_window').fetchone(),window)
            self.assertEqual(journal.owner(),owner)
        finally:journal.db.close()
    def test_finite_cli_refuses_recorded_write_before_reading_or_contacting_EA(self):
        from fc_access.bulk_transfer_v1 import once
        out=Path(self.tmp.name)/'evidence';out.mkdir();(out/'clear-sold.json').write_text('{}')
        with (patch.object(once,'OUT',out),
              patch.object(once,'run',side_effect=AssertionError('no native request')),
              patch.object(once.Store,'open_reconciler',side_effect=AssertionError('no journal restart'))):
            with self.assertRaisesRegex(ValueError,'existing_bulk_attempt_no_replay'):
                once.once('bulk_clear_sold')


class BulkJavascript(unittest.TestCase):
    def test_actual_page_contract(self):
        r=subprocess.run(['node','tests/bulk_transfer_checks.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)


if __name__=='__main__':unittest.main(verbosity=2)

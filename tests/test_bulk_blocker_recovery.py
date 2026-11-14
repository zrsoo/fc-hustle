"""Offline captured-effect replay in temporary state; never connects to EA."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.production_v1.bulk_recovery import record,verify_effect,recover
from fc_access.production_v1.bulk import BulkTransfer,pending,mutation_authorized
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.contracts import stamp
from fc_access.actors_v1.final_supervisor import review_resume

CID='869ed95434e70ea0d7ba599945751fd2'
POST='6e33cd4b3db2b17b52792740a1948701'
BASE=ROOT/'docs/research/002/002-12/review-03/state-backup'


def copy_database(source,target):
    a=sqlite3.connect(source.resolve().as_uri()+'?immutable=1',uri=True);b=sqlite3.connect(target)
    a.backup(b);a.close();b.close()


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for name in ['journal.sqlite3','native.sqlite3','transport.sqlite3','completed-quotes.sqlite3']:
            copy_database(BASE/name,self.root/name)
        self.c,self.r=record(self.root/'transport.sqlite3',CID)
        _,self.before=record(self.root/'transport.sqlite3',self.c['params']['before_read_id'])
        _,self.after=record(self.root/'transport.sqlite3',POST)
        d=sqlite3.connect(self.root/'native.sqlite3')
        self.start,self.end=d.execute('select started,finished from work where id=?',(CID,)).fetchone();d.close()

    def test_captured_effect_requires_one_write_and_full_identity_price_hour_survivor_proof(self):
        self.assertTrue(verify_effect(self.c,self.r,self.before,self.after,started=self.start,finished=self.end))
        for change in ['price','hour','identity','missing','survivor','wire','duplicate','wrong_context','wrong_read','wrong_interval']:
            c,r,b,a=deepcopy((self.c,self.r,self.before,self.after));end=self.end
            target=next(x for x in a['result']['auctions'] if x['item']['item_id'] in c['params']['expected_item_ids'])
            if change=='price':target['buy_now_price']+=100
            elif change=='hour':target['expires']=7200
            elif change=='identity':target['item']['definition_id']+=1
            elif change=='missing':a['result']['auctions'].remove(target)
            elif change=='survivor':next(x for x in a['result']['auctions'] if x is not target and x['item']['item_id'] not in c['params']['expected_item_ids'])['buy_now_price']+=100
            elif change=='wire':r['result']['network'][0]['body_empty']=False
            elif change=='duplicate':r['result']['network'].append(deepcopy(r['result']['network'][0]))
            elif change=='wrong_context':a['context']['account']='0'*32
            elif change=='wrong_read':a['command_id']=c['id']
            elif change=='wrong_interval':end='2030-01-01T00:00:00+00:00'
            with self.subTest(change=change),self.assertRaises(ValueError):
                verify_effect(c,r,b,a,started=self.start,finished=end)

    def test_real_sqlite_transition_is_audited_immutable_and_cannot_authorize_redispatch(self):
        after=deepcopy(self.after)
        sold=next(a for a in after['result']['auctions'] if a['item']['definition_id']==246420)
        sold.update(trade_state='closed',current_bid=sold['buy_now_price'],expires=-1)
        sold['item'].update(last_sale_price=0,untradeable=True)
        class OfflineExecutor:
            def ownership_epoch(self,context):return 100
            def attach(self,context,owner,epoch):return dict(after['fences'],owner=owner,epoch=epoch)
            def execute(self,c):raise AssertionError('no native operation in offline recovery test')
        f=Foundation(OfflineExecutor(),context=self.c['context'],journal_path=self.root/'journal.sqlite3',
            now=lambda:stamp(self.after['freshness']['observed_at'])+timedelta(seconds=1))
        try:
            kwargs=dict(transport_path=self.root/'transport.sqlite3',post_read_id=POST,mailbox_path=self.root/'native.sqlite3')
            with patch.object(BulkTransfer,'inventory',side_effect=TimeoutError('offline failed fresh read')):
                with self.assertRaises(TimeoutError):recover(f,CID,**kwargs)
            self.assertEqual(f.journal.db.execute('select state,incompatible from bulk_writes_v1 where id=?',(CID,)).fetchone(),('UNKNOWN',1))
            wrong=deepcopy(after);wrong['result']['auctions'][0]['item']['definition_id']+=1
            with patch.object(BulkTransfer,'inventory',return_value=wrong):
                with self.assertRaisesRegex(ValueError,'current_inventory_identity'):recover(f,CID,**kwargs)
            with patch.object(BulkTransfer,'inventory',return_value=after) as read:
                result=recover(f,CID,**kwargs);self.assertEqual(result['status'],'RECONCILED');self.assertEqual(read.call_count,1)
                self.assertEqual(recover(f,CID,**kwargs)['status'],'ALREADY_RECONCILED');self.assertEqual(read.call_count,1)
            self.assertEqual(f.journal.db.execute('select state,incompatible from bulk_writes_v1 where id=?',(CID,)).fetchone(),('RECONCILED',1))
            self.assertTrue(mutation_authorized(f.journal_path,self.c,reconciled=True))
            self.assertFalse(mutation_authorized(f.journal_path,self.c))
            self.assertFalse(any(x['command_id']==CID for x in pending(f.journal,f.registry.scope)))
            with self.assertRaisesRegex(sqlite3.Error,'immutable_bulk_recovery'):
                f.journal.db.execute('delete from bulk_recoveries_v1 where id=?',(CID,))
            # The supervisor accepts only journal proof plus an independent read.
            d=sqlite3.connect(self.root/'native.sqlite3');runtime=json.loads(d.execute('select body from runtime where id=1').fetchone()[0]);runtime['journal']=str(f.journal_path)
            d.execute('update runtime set body=? where id=1',(json.dumps(runtime),));d.commit();d.close()
            checked=review_resume(ROOT/'docs/research/002/002-12/remediation-05/live-06',self.root/'native.sqlite3',120)
            self.assertGreater(checked['prior_active_wall_seconds'],0)
        finally:f.close()

    def test_failed_current_read_cannot_clear_the_old_safety_fence(self):
        # No recovery entry exists merely because the historical effect is true.
        self.assertFalse(mutation_authorized(self.root/'journal.sqlite3',self.c,reconciled=True))
        d=sqlite3.connect(self.root/'journal.sqlite3');self.assertEqual(d.execute('select state,incompatible from bulk_writes_v1 where id=?',(CID,)).fetchone(),('UNKNOWN',1));d.close()


if __name__=='__main__':unittest.main(verbosity=2)

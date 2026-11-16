"""Genuine unconfirmed rebid: retain ambiguity, reconcile independently, no replay."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.continuous_v1.evidence import read_db
from fc_access.production_v1.contracts import parse_response,stamp


class RebidRecovery(unittest.TestCase):
    out=ROOT/'docs/research/003/003-04/production-07/incident-bid-01'
    bid='f5cda85c74edb70030debf0df6d4b42e'

    def test_actual_successful_native_callback_is_not_rebid_acceptance(self):
        bundle=Path(json.loads((self.out/'before.json').read_text())['path'])
        with closing(read_db(bundle/'native.sqlite3')) as db:
            c,v=db.execute('SELECT command,response FROM work WHERE id=?',(self.bid,)).fetchone()
            c,v=json.loads(c),json.loads(v)
        parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']),require_bid_receipt=True)
        r=v['result']['bid_receipt']
        self.assertEqual((r['verdict'],r['native_success'],r['before_bid_state'],r['auction']['bid_state']),
                         ('UNCONFIRMED',True,'outbid','outbid'))
        self.assertEqual((r['wire_item_count'],r['matching_item_count'],r['wire_amount']),(1,1,c['params']['amount']))
        self.assertFalse(v['result']['success']);self.assertIsNone(v['freshness']['network_at'])
        invented=deepcopy(v);invented['result'].update(success=True,error=None)
        invented['result']['bid_receipt'].update(verdict='ACCEPTED',reason='MATCHING_NATIVE_PARTICIPATION')
        with self.assertRaises(ValueError):
            parse_response(invented,c,source='native',now=stamp(v['freshness']['observed_at']),require_bid_receipt=True)
        with closing(read_db(bundle/'journal.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(self.bid,)).fetchone(),('UNKNOWN',))
        with closing(read_db(bundle/'control.sqlite3')) as db:
            self.assertTrue(db.execute("SELECT 1 FROM records WHERE kind='RUN_STOPPED' AND run='760f9855eefafd615cb6ccf52be1748f' AND json_extract(body,'$.verified_process_exit')=1").fetchone())

    def test_new_authenticated_personal_read_reconciles_without_second_bid_or_cancelled_read(self):
        bundle=Path(json.loads((self.out/'after-reconciliation.json').read_text())['path'])
        reads=[r for line in (self.out/'fresh-reads/native.jsonl').read_text().splitlines() if
               (r:=json.loads(line))['kind']=='NATIVE_READ']
        with closing(read_db(bundle/'journal.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(self.bid,)).fetchone(),('RECONCILED',))
            proof=json.loads(db.execute("SELECT data FROM events WHERE command_id=? AND reason='BID_VERIFIED'",(self.bid,)).fetchone()[0])
        read=next(r for r in reads if r['command']['id']==proof['read_id'])
        self.assertEqual(read['command']['operation'],'watched')
        for r in reads:
            c,v=r['command'],r['response']
            parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']))
            self.assertTrue(v['result']['success']);self.assertTrue(v['result']['network'])
            self.assertTrue(all(n['method']=='GET' and n['status']==200 for n in v['result']['network']))
        self.assertFalse(any(r['command']['id']==self.bid for r in reads))
        with closing(read_db(bundle/'transport.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE command_id=? AND event='DELIVERED'",(self.bid,)).fetchone()[0],1)
        with closing(read_db(bundle/'native.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT state,started,reason FROM work WHERE id='b91803b82ff6964ba5cbb8d0b6dadb5a'").fetchone(),('UNKNOWN',None,'CALLER_TIMEOUT'))
            self.assertFalse(any(json.loads(x)['kind']=='DISPATCH_CLAIM' for (x,) in db.execute("SELECT body FROM native_events WHERE id='b91803b82ff6964ba5cbb8d0b6dadb5a'")))
        result=json.loads((self.out/'fresh-reads/result.json').read_text())
        self.assertEqual((result['status'],result['account_mutations']),('PASS',0))


if __name__=='__main__':unittest.main(verbosity=2)

"""Retained live no-wire balance failure and independently reconciled bid.

Read only. No UI input, network calls, actor starts, proof amendments or replay.
"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.continuous_v1.evidence import read_db,records
from fc_access.production_v1.contracts import parse_response,stamp


class BalanceRecovery(unittest.TestCase):
    base=ROOT/'private-captures/003-04/production-06/incident-native-01'
    read='bff5c9a35b418770299dbbaf76090996'
    bid='091085ef9a4121ef218e17cbfc98930b'

    def test_callback_without_wire_is_retained_failed_consumed_and_stops_segment(self):
        with closing(read_db(self.base/'sealed/native.sqlite3')) as db:
            state,c,v=db.execute('SELECT state,command,response FROM work WHERE id=?',(self.read,)).fetchone()
            c,v=json.loads(c),json.loads(v)
            self.assertEqual((state,c['operation']),('DONE','balance'))
            self.assertEqual(sum(json.loads(b)['kind']=='DISPATCH_CLAIM' for (b,) in
                db.execute('SELECT body FROM native_events WHERE id=?',(self.read,))),1)
        parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']))
        self.assertFalse(v['result']['success']);self.assertEqual(v['result']['error'],'ambiguous_network')
        self.assertEqual(v['result']['network'],[]);self.assertEqual(v['freshness']['request_count'],0)
        self.assertIsNone(v['freshness']['network_at']);self.assertIsNone(v['result']['credits'])
        fabricated=deepcopy(v);fabricated['result'].update(success=True,error=None,credits=59427)
        with self.assertRaises(ValueError):
            parse_response(fabricated,c,source='native',now=stamp(v['freshness']['observed_at']))
        with closing(read_db(self.base/'sealed/transport.sqlite3')) as db:
            self.assertEqual(json.loads(db.execute('SELECT result FROM commands WHERE id=?',(self.read,)).fetchone()[0]),v)
        with closing(read_db(self.base/'sealed/control.sqlite3')) as db:rows=records(db)
        stopped=next(r for r in rows if r['kind']=='RUN_STOPPED' and r['run']=='adb917726e7774d2e2558a1e578ed1d3')
        self.assertTrue(stopped['body']['verified_process_exit'])
        self.assertEqual(stopped['body']['remaining_processes'],[])
        self.assertTrue(any(r['kind']=='STOP_REQUESTED' and r['body']['reason']=='AMBIGUOUS_OR_FAILED_NATIVE_COMMAND'
                            and r['seq']<stopped['seq'] for r in rows))

    def test_pending_real_bid_reconciled_only_by_new_authenticated_gets(self):
        with closing(read_db(self.base/'sealed/journal.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(self.bid,)).fetchone(),('ACKNOWLEDGED',))
        with closing(read_db(self.base/'after-reconciliation/journal.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(self.bid,)).fetchone(),('RECONCILED',))
            proof=json.loads(db.execute("SELECT data FROM events WHERE command_id=? AND reason IN ('BID_VERIFIED','LOST_VERIFIED','WON_VERIFIED') ORDER BY rowid DESC LIMIT 1",(self.bid,)).fetchone()[0])
        out=ROOT/'docs/research/003/003-04/production-06/incident-native-01/fresh-reads'
        reads=[r for line in (out/'native.jsonl').read_text().splitlines() if (r:=json.loads(line))['kind']=='NATIVE_READ']
        self.assertIn(proof['read_id'],{r['command']['id'] for r in reads})
        self.assertTrue({self.read,self.bid}.isdisjoint(r['command']['id'] for r in reads))
        for row in reads:
            c,v=row['command'],row['response']
            parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']))
            self.assertTrue(v['result']['success']);self.assertGreater(v['freshness']['request_count'],0)
            self.assertTrue(all(n['method']=='GET' and n['status']==200 for n in v['result']['network']))
        result=json.loads((out/'result.json').read_text())
        self.assertEqual((result['status'],result['account_mutations'],result['recovery']['commitments']),('PASS',0,0))
        with closing(read_db(self.base/'after-reconciliation/transport.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE command_id=? AND event='DELIVERED'",(self.bid,)).fetchone()[0],1)


if __name__=='__main__':unittest.main(verbosity=2)

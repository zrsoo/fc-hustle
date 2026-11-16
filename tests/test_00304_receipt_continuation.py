"""Actual retained receipt runtime evidence and negative audit contracts.

No EA calls, actor starts, proof amendments or replay. Synthetic negative
examples remain in memory or temporary directories, never live evidence.
"""
from contextlib import closing,nullcontext
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from check_00304_live import (OUT,load,lines,incident_contract,accepted_bid_readback_contract,
                             segment_contract,capture_boundary_contract)
from fc_access.continuous_v1.evidence import read_db,records,assess
import probe_00304_prelaunch as prelaunch


class ReceiptContinuation(unittest.TestCase):
    def setUp(self):
        self.episode=OUT/'production-04'
        self.bundle=Path(load(self.episode/'audit-baseline.json')['path'])
        with closing(read_db(self.bundle/'control.sqlite3')) as db:self.rows=records(db)
        self.run=load(self.bundle/'manifest.json')['run']
        self.fences=next(r['body']['fences'] for r in self.rows if r['run']==self.run and r['kind']=='ATTACHED')
        runs={json.dumps(r['body']['fences'],sort_keys=True):r['run'] for r in self.rows if r['kind']=='ATTACHED'}
        self.commands={}
        with closing(read_db(self.bundle/'native.sqlite3')) as db:
            for c,r in db.execute('SELECT command,response FROM work'):
                c=json.loads(c);self.commands[c['id']]=dict(run=runs.get(json.dumps(c['fences'],sort_keys=True)),
                                                         command=c,response=json.loads(r) if r else None)
        for r in self.rows:
            if r['kind']=='RECOVERY_READ':self.commands[r['body']['command']['id']]=dict(run=r['run'],**r['body'])

    def current_bids(self):
        return [v for v in self.commands.values() if v['run']==self.run and v['command']['operation']=='bid']

    def test_genuine_receipt_is_durable_and_has_distinct_native_personal_readback(self):
        bids=self.current_bids();self.assertTrue(bids)
        with closing(read_db(self.bundle/'journal.sqlite3')) as db:
            for v in bids:
                cid=v['command']['id'];receipt=v['response']['result']['bid_receipt']
                self.assertEqual(receipt['verdict'],'ACCEPTED')
                self.assertEqual(receipt['wire_item_count'],1);self.assertEqual(receipt['native_item_count'],1)
                self.assertEqual(json.loads(db.execute('SELECT receipt FROM bid_receipts_v1 WHERE command_id=?',(cid,)).fetchone()[0]),receipt)
                self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(cid,)).fetchone(),('RECONCILED',))
                proof=db.execute("SELECT data FROM events WHERE command_id=? AND reason IN ('BID_VERIFIED','LOST_VERIFIED','WON_VERIFIED') ORDER BY seq DESC",(cid,)).fetchone()
                self.assertIsNotNone(proof)
                read=self.commands[json.loads(proof[0])['read_id']]
                accepted_bid_readback_contract(v,read)
        with closing(read_db(self.bundle/'native.sqlite3')) as db:
            for v in bids:
                kinds=[json.loads(b)['kind'] for (b,) in db.execute('SELECT body FROM native_events WHERE id=?',(v['command']['id'],))]
                self.assertEqual(kinds.count('DISPATCH_CLAIM'),1)

    def test_http_success_none_stale_wrong_physical_or_missing_receipt_cannot_replace_live_proof(self):
        bid=self.current_bids()[0]
        with closing(read_db(self.bundle/'journal.sqlite3')) as db:
            proof=json.loads(db.execute("SELECT data FROM events WHERE command_id=? AND reason='BID_VERIFIED'",(bid['command']['id'],)).fetchone()[0])
        read=self.commands[proof['read_id']]
        for fault in ('missing-receipt','empty-native','none','wrong-item','wrong-version','old-read','wrong-context'):
            w=deepcopy(bid);r=deepcopy(read)
            target=next(a for a in r['response']['result']['auctions'] if a['trade_id']==w['command']['params']['trade_id'])
            if fault=='missing-receipt':w['response']['result'].pop('bid_receipt')
            if fault=='empty-native':w['response']['result']['bid_receipt']['native_item_count']=0
            if fault=='none':target['bid_state']='none'
            if fault=='wrong-item':target['item']['item_id']='item:'+'e'*24
            if fault=='wrong-version':target['item']['definition_id']+=1
            if fault=='old-read':r['response']['freshness']['network_at']=w['response']['freshness']['network_at']
            if fault=='wrong-context':r['command']['context']['persona']='0'*32
            with self.subTest(fault=fault),self.assertRaises(ValueError):accepted_bid_readback_contract(w,r)

    def test_both_old_commands_are_retired_only_by_separate_explicit_operator_nonregistration(self):
        with closing(read_db(self.bundle/'journal.sqlite3')) as db:
            for name in ['resolved-doue-incident.json','resolved-alvarez-incident.json']:
                incident=load(self.episode/name);cid=incident['triggering_command_id']
                proof=json.loads(db.execute('SELECT proof FROM operator_nonregistrations_v1 WHERE command_id=?',(cid,)).fetchone()[0])
                self.assertEqual(proof['source'],'operator');self.assertEqual(proof['outcome'],'NOT_REGISTERED')
                self.assertFalse(proof['native_outcome_verified']);self.assertFalse(proof['refund_claimed'])
                self.assertTrue(proof['authorization']);self.assertTrue(proof['attestation'])
                self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(cid,)).fetchone(),('RECONCILED',))
                self.assertEqual(db.execute('SELECT phase FROM capacity_slots_v1 WHERE trade_id=?',(proof['identity']['trade_id'],)).fetchone(),('OPERATOR_NOT_REGISTERED',))
                self.assertIsNone(db.execute("SELECT 1 FROM events WHERE command_id=? AND reason IN ('BID_VERIFIED','LOST_VERIFIED','WON_VERIFIED')",(cid,)).fetchone())
                for path in ['production-02/incident-identity-01/exact-status.jsonl',
                             'production-03/incident-outcome-01/native-diagnostic.jsonl',
                             'production-03/incident-outcome-01/terminal-diagnostic.jsonl',
                             'production-03/incident-outcome-01/followup-status.jsonl']:
                    for row in lines(OUT/path):
                        if row['kind']=='NATIVE_READ':self.commands[row['command']['id']]=dict(run=incident['run'],command=row['command'],response=row['response'])
                incident_contract(incident,self.rows,self.commands,operator_proof=proof)
                for key,value in [('authorization',''),('source','native'),('native_outcome_verified',True),('outcome','LOST')]:
                    bad=deepcopy(proof);bad[key]=value
                    with self.subTest(command=cid,key=key),self.assertRaises(ValueError):
                        incident_contract(incident,self.rows,self.commands,operator_proof=bad)
            self.assertIsNotNone(db.execute('SELECT proof FROM operator_losses_v1 WHERE command_id=?',
                ('ff4174653771149736e63b1ac12630f9',)).fetchone()) # Earlier operator assertion was not rewritten.

    def test_receipt_experiment_remains_consumed_and_was_not_replayed_as_production(self):
        live=load(OUT/'bid-receipt-repair-01/independent-live-validation.json')
        self.assertEqual(live['status'],'PASS');self.assertEqual(live['ea_requests'],16);self.assertEqual(live['mutations'],1)
        self.assertNotIn(live['bid_command_id'],[v['command']['id'] for v in self.current_bids()])
        with closing(read_db(self.bundle/'journal.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(live['bid_command_id'],)).fetchone(),('RECONCILED',))
        report=assess(self.bundle)
        self.assertEqual(report['evidence_class'],'NATIVE_CAPTURE_REQUIRES_CASE_REVIEW')
        capture_boundary_contract(dict(phase='CONTINUOUS_PRODUCTION',cancelled_before_dispatch=[
            'e84dcddef494468d3e12a2766ccd6fba','97d2b4e437f0d7f3990be2b6876e98a7']),self.bundle,report)
        snapshots=[r for r in self.rows if r['run']==self.run and r['kind']=='SNAPSHOT']
        self.assertGreater(snapshots[-1]['body']['native_requests_observed'],16)
        self.assertFalse(any(r['run']==self.run and r['kind'] in {'STOP_REQUESTED','INCIDENT','SUPERVISION_GAP'} for r in self.rows))
        with closing(read_db(self.bundle/'journal.sqlite3')) as db:
            resolved={r[0] for table in ('commands','bulk_writes_v1','resale_writes_v1')
                      for r in db.execute('SELECT id FROM '+table+" WHERE state='RECONCILED'")}
        self.assertGreater(segment_contract(self.rows,self.run,minimum=1,resolved_intents=resolved),0)

    def test_fresh_prelaunch_retained_account_identity_inventory_and_existing_commitment(self):
        p=load(self.episode/'prelaunch-reads/result.json');proof=load(self.episode/'independent-prelaunch.json')
        self.assertEqual(p['status'],'PASS');self.assertEqual(p['actors_started'],0);self.assertEqual(p['account_mutations'],0)
        self.assertEqual(p['recovery']['commitments'],1)
        self.assertFalse(set(proof['read_ids'])&set(proof['prior_read_ids']))
        self.assertEqual(len(proof['physical_identities']),5)
        self.assertFalse(proof['consumed_receipt_experiment_replayed'])
        self.assertFalse(proof['prior_historical_command_replayed'])

    def test_prelaunch_rejects_every_mutation_before_transport_and_never_reuses_an_output(self):
        class Edge:
            calls=[]
            context=load(OUT/'context.json')
            def request(self,path):return dict(service='fc-production-v1',mutations_enabled=False,attached=True,owner=dict(context=self.context))
            def execute(self,c):self.calls.append(c);raise AssertionError('must not send mutation')
        for operation in ('bid','move','list','clear_sold','relist_all'):
            with self.subTest(operation=operation),tempfile.TemporaryDirectory() as folder:
                target=Path(folder)/'offline-rejection';Edge.calls=[]
                def fake_foundation(executor,**kwargs):return executor.execute(dict(operation=operation))
                with patch.object(prelaunch,'EdgeExecutor',Edge),patch.object(prelaunch,'Foundation',fake_foundation),\
                     patch.object(prelaunch,'process_lock',lambda path:nullcontext()):
                    result=prelaunch.probe(target,Edge.context)
                    self.assertEqual(result['status'],'STOPPED')
                    self.assertEqual(result['reason'],'read_only_prelaunch_operation_required')
                    self.assertFalse(Edge.calls)
                    with self.assertRaises(FileExistsError):prelaunch.probe(target,Edge.context)


if __name__=='__main__':unittest.main(verbosity=2)

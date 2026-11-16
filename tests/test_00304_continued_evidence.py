"""Behavioral audit regressions and retained production-03 artifact checks.

In-memory examples test rejection paths only; they never create live evidence.
"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from check_00304_live import (OUT,load,lines,browser_contract,login_evidence_contract,
                             incident_contract,semantic_case)
from fc_access.continuous_v1.evidence import read_db,records
from watch_00304_evidence import ReviewWatch


class ContinuedEvidence(unittest.TestCase):
    def setUp(self):
        self.episode=OUT/'production-03'

    def native_probe(self):
        return {r['command']['id']:(r['command'],r['response'])
                for r in lines(self.episode/'prelaunch-reads/native.jsonl') if r['kind']=='NATIVE_READ'}

    def test_fresh_probe_retains_three_independent_native_reads_and_physical_continuity(self):
        result=load(self.episode/'prelaunch-reads/result.json')
        proof=load(self.episode/'independent-prelaunch.json')
        reads=self.native_probe()
        prior={r['command']['id'] for r in lines(OUT/'production-02/operator-resolution-01/live-recovery/native.jsonl')
               if r['kind']=='NATIVE_READ'}
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['account_mutations'],0)
        self.assertEqual(result['unresolved'],0)
        self.assertTrue(proof['physical_item_continuity'])
        self.assertEqual(len(proof['physical_items']),5)
        self.assertFalse(set(reads)&prior)
        self.assertEqual(set(reads),set(result['recovery']['read_ids']))
        self.assertEqual({c['operation'] for c,r in reads.values()},{'watched','balance','transfer_list'})
        for command,response in reads.values():
            self.assertEqual(command['context'],proof['intended_context'])
            self.assertEqual(response['context'],proof['intended_context'])
            self.assertTrue(response['result']['success'])
            self.assertEqual([(n['method'],n['status']) for n in response['result']['network']],[('GET',200)])

    def test_normal_saved_login_needs_retained_ui_selection_and_real_authentication_readbacks(self):
        rows=lines(self.episode/'browser-recovery.jsonl');browser_contract(rows)
        review=next(r for r in rows if r['kind']=='LOGIN_REVIEW')
        capture=load(OUT/review['evidence']);native=self.native_probe()
        login_evidence_contract(review,capture,native)
        for fault in ('wrong-account','challenge','credentials','missing-review'):
            changed=deepcopy(rows)
            r=next(r for r in changed if r['kind']=='LOGIN_REVIEW')
            if fault=='wrong-account':r['designated_saved_account']='someone-else'
            if fault=='challenge':r['challenge_bypassed']=True
            if fault=='credentials':r['credentials_or_session_extracted']=True
            if fault=='missing-review':changed.remove(r)
            with self.subTest(fault=fault),self.assertRaises(ValueError):browser_contract(changed)
        for fault in ('no-ui','ambiguous-account','no-home','no-native','failed-native'):
            c=deepcopy(capture);n=deepcopy(native)
            if fault=='no-ui':c['events']=[]
            if fault=='ambiguous-account':
                for e in c['events']:
                    e['captured_ui_output']=e['captured_ui_output'].replace('"designated_saved_account_option_count":1',
                                                                          '"designated_saved_account_option_count":2')
            if fault=='no-home':
                for e in c['events']:e['captured_ui_output']=e['captured_ui_output'].replace('"app_home":true','"app_home":false')
            if fault=='no-native':n={}
            if fault=='failed-native':next(iter(n.values()))[1]['result']['success']=False
            with self.subTest(fault=fault),self.assertRaises(ValueError):login_evidence_contract(review,c,n)

    def test_operator_resolution_preserves_unknown_native_outcome_and_checks_restart_reads(self):
        incident=load(self.episode/'resolved-prior-incident.json')
        exports=lines(ROOT/'private-captures/continuous-evidence/00304-production03-periodic/events.jsonl')
        bundle=Path(next(r['path'] for r in reversed(exports) if r['kind']=='CAPTURED'))
        with closing(read_db(bundle/'control.sqlite3')) as db:rows=records(db)
        fences={json.dumps(r['body']['fences'],sort_keys=True):r['run'] for r in rows if r['kind']=='ATTACHED'}
        commands={}
        with closing(read_db(bundle/'native.sqlite3')) as db:
            for c,r in db.execute('SELECT command,response FROM work'):
                c=json.loads(c);commands[c['id']]=dict(run=fences.get(json.dumps(c['fences'],sort_keys=True)),
                                                     command=c,response=json.loads(r) if r else None)
        for r in rows:
            if r['kind']=='RECOVERY_READ':commands[r['body']['command']['id']]=dict(run=r['run'],**r['body'])
        for r in lines(OUT/'production-02/incident-identity-01/exact-status.jsonl'):
            if r['kind']=='NATIVE_READ':commands[r['command']['id']]=dict(run=incident['run'],command=r['command'],response=r['response'])
        with closing(read_db(bundle/'journal.sqlite3')) as db:
            proof=json.loads(db.execute('SELECT proof FROM operator_losses_v1 WHERE command_id=?',
                                        (incident['triggering_command_id'],)).fetchone()[0])
        incident_contract(incident,rows,commands,operator_proof=proof)
        for field,value in [('source','native'),('native_outcome_verified',True),('refund_claimed',True),
                            ('authorization',''),('amount',700),('command_id','unrelated')]:
            p=deepcopy(proof);p[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):incident_contract(incident,rows,commands,operator_proof=p)
        changed=deepcopy(incident);changed['restart_reconciliation']['read_ids']=['fabricated']
        with self.assertRaisesRegex(ValueError,'restart_readbacks_missing'):
            incident_contract(changed,rows,commands,operator_proof=proof)

    def test_exact_status_coverage_requires_an_actual_prior_bid_and_distinct_native_branch(self):
        identity=dict(trade_id='trade',item_id='item',definition_id=123)
        def value(cid,op,seconds,auctions,params=None):
            return dict(command=dict(id=cid,operation=op,params=params or {}),response=dict(
                freshness=dict(network_at=f'2030-01-01T00:00:0{seconds}Z'),
                result=dict(success=True,auctions=auctions)))
        row=dict(trade_id='trade',item=dict(item_id='item',definition_id=0),trade_state='closed',bid_state='outbid',expires=-1)
        values=[value('bid','bid',1,[],identity),value('watched','watched',2,[]),value('status','status',3,[row],identity)]
        observations=dict(registry=[dict(kind='EXACT_STATUS',reason='EXACT_STATUS_RECOVERED',source='native',
                                        identity=identity,watched_read_id='watched',read_id='status')])
        self.assertTrue(semantic_case('post_bid_selector_reconciliation',values,observations))
        for fault in ('no-bid','watched-present','wrong-item','wrong-version','old-status','no-status','pending-only','offline-event'):
            v=deepcopy(values);o=deepcopy(observations)
            if fault=='no-bid':v.pop(0)
            if fault=='watched-present':v[1]['response']['result']['auctions']=[deepcopy(row)]
            if fault=='wrong-item':v[2]['response']['result']['auctions'][0]['item']['item_id']='different'
            if fault=='wrong-version':v[2]['response']['result']['auctions'][0]['item']['definition_id']=124
            if fault=='old-status':v[2]['response']['freshness']['network_at']='2030-01-01T00:00:00Z'
            if fault=='no-status':v.pop()
            if fault=='pending-only':v[2]['response']['result']['auctions'][0]['bid_state']='none'
            if fault=='offline-event':o['registry'][0]['source']='fixture'
            with self.subTest(fault=fault):self.assertFalse(semantic_case('post_bid_selector_reconciliation',v,o))

    def test_actual_minimum_bid_can_be_independently_read_back_after_a_competitor_outbids_it(self):
        # Exercise the existing minimum-bid contract with a later genuine outbid shape.
        identity=dict(trade_id='trade',item_id='physical',definition_id=123)
        row=dict(trade_id='trade',item=dict(item_id='physical',definition_id=123),starting_bid=700,
                 current_bid=750,bid_state='none')
        def response(rows,at):return dict(result=dict(success=True,auctions=rows),freshness=dict(network_at=at))
        before=dict(command=dict(id='search',operation='search'),response=response([row],'2030-01-01T00:00:00Z'))
        funds=dict(command=dict(id='funds',operation='balance'),response=dict(result=dict(success=True,credits=60000)))
        helper=dict(command=dict(id='ticks',operation='price_helpers'),response=dict(result=dict(success=True,
                     probes=[dict(direction='above',value=750,price=800)])))
        bid=dict(command=dict(id='bid',operation='bid',params=dict(**identity,amount=800,minimum=800,cap=4300,
                     status_read_id='search',balance_read_id='funds')),
                 response=response([],'2030-01-01T00:00:01Z'))
        later=deepcopy(row);later.update(current_bid=900,bid_state='outbid')
        after=dict(command=dict(id='after',operation='watched'),response=response([later],'2030-01-01T00:00:02Z'))
        values=[before,funds,helper,bid,after];observations=dict(registry=[dict(kind='ENROLLMENT',trade_id='trade')])
        self.assertTrue(semantic_case('minimum_initial_bid',values,observations))
        later['item']['item_id']='different-physical-item'
        self.assertFalse(semantic_case('minimum_initial_bid',values,observations))

    def test_persistent_review_keeps_running_for_missing_events_and_after_four_hour_success(self):
        for status,missing in [('INCOMPLETE',['won']),('PASS',[])]:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);snapshot=root/'snapshot';snapshot.mkdir()
                db=sqlite3.connect(snapshot/'control.sqlite3')
                db.execute('CREATE TABLE records(run TEXT,kind TEXT)');db.commit()
                exports=root/'export.jsonl';exports.write_text(json.dumps(dict(kind='CAPTURED',run='offline-fixture',path=str(snapshot)))+'\n')
                index=root/'index.json';index.write_text(json.dumps(dict(run='offline-fixture',export_events=str(exports),matrix='matrix.json')))
                calls=[]
                def review(index):
                    calls.append(index)
                    return dict(cases=[]),dict(verified_cases=[],unverified_cases=missing,healthy_seconds=14410)
                def assess(index,directory):return dict(status=status)
                watch=ReviewWatch(index,root/'receipts','offline-fixture',reviewer=review,assessor=assess)
                try:
                    self.assertTrue(watch.step())
                    self.assertTrue(watch.step())
                    self.assertEqual(len(calls),1) # No duplicate review of the same capture.
                    receipts=list((root/'receipts').glob('review-*.json'));self.assertEqual(len(receipts),1)
                    self.assertEqual(load(receipts[0])['coverage']['unverified_cases'],missing)
                    db.execute("INSERT INTO records VALUES('offline-fixture','RUN_STOPPED')");db.commit()
                    # A new sealed stopped capture, not a coverage target, ends this watch.
                    snapshot2=root/'stopped';snapshot2.mkdir()
                    with closing(sqlite3.connect(snapshot2/'control.sqlite3')) as target:db.backup(target)
                    with exports.open('a') as f:f.write(json.dumps(dict(kind='CAPTURED',run='offline-fixture',path=str(snapshot2)))+'\n')
                    self.assertFalse(watch.step())
                finally:watch.close();db.close()

    def test_uncertain_write_needs_native_reconciliation_and_cannot_use_operator_loss_or_unsent_read(self):
        identity=dict(trade_id='trade',item_id='item',definition_id=123)
        command=dict(id='old-bid',operation='bid',params=dict(**identity,amount=800))
        later=dict(command=dict(id='proof',operation='status',params=identity),response=dict(
            result=dict(success=True,auctions=[dict(trade_id='trade',item=dict(item_id='item',definition_id=0),
                bid_state='outbid',trade_state='closed',expires=-1,current_bid=900)]),freshness=dict(network_at='2030-01-01T00:00:10Z')))
        observations=dict(controls=[dict(kind='NATIVE_RESULT',at='2030-01-01T00:00:00Z',body=dict(state='UNKNOWN',command=command))],
            bid_events=[dict(command_id='old-bid',reason='LOST_VERIFIED',data=dict(read_id='proof'))])
        self.assertTrue(semantic_case('uncertain_reconciliation',[later],observations))
        for fault in ('operator','unsent-read','wrong-command','no-readback','wrong-item','wrong-version','stale'):
            o=deepcopy(observations);v=deepcopy(later)
            if fault=='operator':o['bid_events'][0]['reason']='OPERATOR_LOST_CONFIRMED'
            if fault=='unsent-read':o['controls'][0]['body']['command']['operation']='watched'
            if fault=='wrong-command':o['bid_events'][0]['command_id']='unrelated'
            if fault=='no-readback':o['bid_events'][0]['data']['read_id']='unretained'
            if fault=='wrong-item':v['response']['result']['auctions'][0]['item']['item_id']='other'
            if fault=='wrong-version':v['response']['result']['auctions'][0]['item']['definition_id']=124
            if fault=='stale':v['response']['freshness']['network_at']='2029-01-01T00:00:00Z'
            with self.subTest(fault=fault):self.assertFalse(semantic_case('uncertain_reconciliation',[v],o))


if __name__=='__main__':unittest.main(verbosity=2)

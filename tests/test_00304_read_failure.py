"""No-status failure retention, controlled stop and actual independent recovery.

VM/native doubles stay offline. Historical read failure and its subsequent
real native reconciliation are inspected separately, without rewriting either.
"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from fc_access.production_v1.contracts import parse_response,stamp
from fc_access.production_v1.diagnostics import validate_records
from fc_access.production_v1.store import Store
from fc_access.continuous_v1.evidence import read_db,records,assess
from check_00304_live import capture_boundary_contract
import test_00302_continuous as continuous


class ReadFailure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample=json.loads(subprocess.check_output(['node','tests/production_network_failure_checks.cjs','--sample'],cwd=ROOT,text=True))

    def test_actual_page_failure_has_no_http_status_or_freshness_and_diagnostic_is_typed(self):
        c,v=self.sample['command'],self.sample['response']
        parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']))
        self.assertFalse(v['result']['success']);self.assertIsNone(v['freshness']['network_at'])
        self.assertIsNone(v['result']['network'][0]['status'])
        validate_records(self.sample['diagnostics'])
        event=next(r for r in self.sample['diagnostics'] if r['stage']=='EA_RESPONSE')
        self.assertTrue(event['detail']['xhr_zero_status'])
        for field,value in [('xhr_zero_status',0),('cookie','credential-canary')]:
            bad=deepcopy(self.sample['diagnostics']);bad[0]['detail'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_records(bad)
        zero=deepcopy(v);zero['result']['network'][0]['status']=0
        with self.assertRaisesRegex(ValueError,'invalid_network_status'):
            parse_response(zero,c,source='native',now=stamp(v['freshness']['observed_at']))
        success=deepcopy(v);success['result'].update(success=True,error=None)
        with self.assertRaises(ValueError):parse_response(success,c,source='native',now=stamp(v['freshness']['observed_at']))

    def test_host_retains_entire_failed_envelope_and_never_replays_its_consumed_id(self):
        with tempfile.TemporaryDirectory() as folder:
            c,v=deepcopy(self.sample['command']),deepcopy(self.sample['response'])
            store=Store(Path(folder)/'transport.sqlite3',now=lambda:stamp(v['freshness']['observed_at']))
            try:
                c['fences']['host_epoch']=store.host_epoch;v['fences']=deepcopy(c['fences'])
                peer=dict(context=c['context'],fences=c['fences'])
                store.activate(dict(context=c['context'],owner=c['fences']['owner'],epoch=c['fences']['epoch']))
                store.enqueue(c,peer);self.assertEqual(store.claim(peer),c)
                store.finish(peer,c['id'],v)
                self.assertEqual(store.result(c['id']),v)
                self.assertEqual(store.db.execute('SELECT state FROM commands WHERE id=?',(c['id'],)).fetchone(),('UNKNOWN',))
                self.assertIsNone(store.claim(peer))
                with self.assertRaisesRegex(ValueError,'duplicate_command'):store.enqueue(c,peer)
                self.assertFalse(any('RESULT_REJECTED' in e for (e,) in store.db.execute('SELECT event FROM events')))
            finally:store.db.close()

    def test_continuous_broker_retains_failed_result_stops_and_does_not_retry(self):
        case=continuous.ContinuousBehavior('test_native_timeout_and_invalid_schema_are_not_retried')
        self.addCleanup(case.doCleanups);case.setUp()
        c=case.enqueue('watched','bidder');v=deepcopy(self.sample['response'])
        v.update(command_id=c['id'],context=c['context'],fences=c['fences'])
        v['freshness'].update(read_id=c['id'],source='fixture',observed_at=case.clock.now().isoformat())
        with patch.object(case.page,'execute',return_value=v) as execute:
            with self.assertRaisesRegex(ValueError,'reconciliation'):case.broker.run_one()
            self.assertEqual(execute.call_count,1)
            with self.assertRaisesRegex(ValueError,'stopped'):case.broker.run_one()
            self.assertEqual(execute.call_count,1)
        row=case.box.db.execute('SELECT state,response FROM work WHERE id=?',(c['id'],)).fetchone()
        self.assertEqual(row[0],'DONE');self.assertEqual(json.loads(row[1]),v)
        result=case.control.latest(case.run,'NATIVE_RESULT')
        self.assertFalse(result['response']['result']['success']);self.assertEqual(result['state'],'DONE')
        self.assertIsNotNone(case.control.latest(case.run,'STOP_REQUESTED'))

    def test_actual_stopped_read_and_pending_bid_are_preserved_then_independently_reconciled(self):
        out=ROOT/'docs/research/003/003-04/production-04/incident-read-01'
        before=Path(json.loads((out/'backup.json').read_text())['path'])
        after=json.loads((out/'after-reconciliation.json').read_text())['databases']
        read='2f2909de513d3229cc6a8e293449c872';bid='663b8845906ad81b8b9cde2af179674a'
        with closing(read_db(before/'native.sqlite3')) as db:
            row=db.execute('SELECT state,started,response FROM work WHERE id=?',(read,)).fetchone()
            self.assertEqual(row[0],'UNKNOWN');self.assertIsNotNone(row[1]);self.assertIsNone(row[2])
            kinds=[json.loads(b)['kind'] for (b,) in db.execute('SELECT body FROM native_events WHERE id=?',(read,))]
            self.assertEqual(kinds.count('DISPATCH_CLAIM'),1)
        with closing(read_db(before/'transport.sqlite3')) as db:
            events=[json.loads(e) for (e,) in db.execute('SELECT event FROM events WHERE command_id=?',(read,)) if e.startswith('{')]
            rejected=next(e for e in events if e.get('kind')=='RESULT_REJECTED')
            self.assertEqual(rejected['reason'],'invalid_network_status')
            self.assertFalse(rejected['summary']['success'])
            self.assertIsNone(rejected['summary']['network'][0]['status'])
        with closing(read_db(before/'journal.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(bid,)).fetchone(),('ACKNOWLEDGED',))
        with closing(read_db(after['journal']['path'])) as db:
            self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',(bid,)).fetchone(),('RECONCILED',))
            proof=json.loads(db.execute("SELECT data FROM events WHERE command_id=? AND reason IN ('BID_VERIFIED','LOST_VERIFIED','WON_VERIFIED')",(bid,)).fetchone()[0])
        fresh=[r for line in (out/'fresh-reads/native.jsonl').read_text().splitlines() if (r:=json.loads(line))['kind']=='NATIVE_READ']
        self.assertIn(proof['read_id'],{r['command']['id'] for r in fresh})
        self.assertNotIn(read,{r['command']['id'] for r in fresh})
        self.assertTrue(all(r['command']['operation'] in {'watched','balance','transfer_list','status','owned_item','unassigned','caps'} and
                            r['response']['result']['success'] for r in fresh))
        self.assertTrue(all(n['method']=='GET' and n['status']==200 for r in fresh for n in r['response']['result']['network']))
        self.assertEqual(json.loads((out/'fresh-reads/result.json').read_text())['account_mutations'],0)

    def test_documented_read_failure_is_diagnosable_but_cannot_waive_an_uncertain_mutation(self):
        out=ROOT/'docs/research/003/003-04/production-04/incident-read-01'
        before=Path(json.loads((out/'backup.json').read_text())['path']);report=assess(before)
        index=dict(phase='CONTINUOUS_PRODUCTION',documented_read_failures=['2f2909de513d3229cc6a8e293449c872'],
                   cancelled_before_dispatch=['57a7d48bfd6ac5712d7cf9b6cc6698f8'])
        capture_boundary_contract(index,before,report)
        bad=deepcopy(index);bad['documented_read_failures']=[]
        with self.assertRaisesRegex(ValueError,'unresolved_capture_findings'):capture_boundary_contract(bad,before,report)
        bad=deepcopy(index);bad['documented_read_failures'].append('663b8845906ad81b8b9cde2af179674a')
        invented=deepcopy(report);invented['findings'].append(dict(reference=dict(command_id='663b8845906ad81b8b9cde2af179674a'),reason='UNSETTLED_COMMAND'))
        with self.assertRaisesRegex(ValueError,'unresolved_capture_findings'):capture_boundary_contract(bad,before,invented)


if __name__=='__main__':unittest.main(verbosity=2)

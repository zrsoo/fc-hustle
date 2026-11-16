"""Bounded route categories preserve strict overlap stops and credential privacy."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.production_v1.diagnostics import validate_records
from fc_access.production_v1.contracts import parse_response,stamp
from fc_access.continuous_v1.evidence import read_db


class RouteDiagnostics(unittest.TestCase):
    def test_actual_page_keeps_unknown_post_failed_and_exports_only_categories(self):
        rows=json.loads(subprocess.check_output(['node','tests/production_route_diagnostic_checks.cjs','--sample'],cwd=ROOT,text=True))
        self.assertEqual(len(rows),3)
        for row in rows:
            c,v=row['command'],row['response']
            parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']))
            validate_records(row['diagnostics'])
            self.assertFalse(v['result']['success']);self.assertIsNone(v['result']['credits'])
            self.assertIsNone(v['freshness']['network_at'])
            bad=deepcopy(row['diagnostics']);event=next(r for r in bad if r['stage']=='UNCLASSIFIED_EA_REQUEST')
            event['detail']['route_group']='CREDENTIAL-CANARY'
            with self.assertRaises(ValueError):validate_records(bad)
            event['detail']['route_group']='OTHER';event['detail']['path']='/private/CREDENTIAL-CANARY'
            with self.assertRaises(ValueError):validate_records(bad)

    def test_actual_opaque_live_overlap_is_retained_not_reclassified_retrospectively(self):
        p=ROOT/'docs/research/003/003-04/production-08/incident-traffic-01'
        bundle=Path(json.loads((p/'before.json').read_text())['path'])
        cid='91186a211aac82aceceaa141ba77799c'
        with closing(read_db(bundle/'native.sqlite3')) as db:
            c,v=db.execute('SELECT command,response FROM work WHERE id=?',(cid,)).fetchone();c,v=json.loads(c),json.loads(v)
            self.assertEqual(sum(json.loads(b)['kind']=='DISPATCH_CLAIM' for (b,) in db.execute('SELECT body FROM native_events WHERE id=?',(cid,))),1)
        self.assertEqual(c['operation'],'balance');self.assertFalse(v['result']['success'])
        self.assertEqual(v['result']['error'],'ambiguous_network')
        self.assertEqual([(n['method'],n['path']) for n in v['result']['network']],
            [('POST','/unexpected'),('GET','/ut/game/fc27/trade/status/lite'),('GET','/ut/game/fc27/user/credits')])
        self.assertTrue(all(n['status']==200 for n in v['result']['network']))
        self.assertIsNone(v['result']['credits']);self.assertIsNone(v['freshness']['network_at'])
        # Diagnostic repair adds no information to the already sealed result.
        self.assertNotIn('route_group',json.dumps(v))
        with closing(read_db(bundle/'control.sqlite3')) as db:
            row=db.execute("SELECT body FROM records WHERE run='a19ffc3e44a3c5ec3374a7bfece9b404' AND kind='RUN_STOPPED'").fetchone()
            self.assertTrue(json.loads(row[0])['verified_process_exit'])


if __name__=='__main__':unittest.main(verbosity=2)

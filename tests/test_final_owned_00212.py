"""Independent owned-by-ID fallback tests; synthetic services and temporary state."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_00208_resale import ResalePage,Clock,CONTEXT
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.contracts import parse_response,stamp
from fc_access.actors_v1.actors import Acquirer,Bidder
from fc_access.actors_v1.maintenance import TransferMaintenance
from fc_access.actors_v1.sold import SoldClear
from fc_access.actors_v1.final_run import preflight,Evidence,load_evidence
from datetime import datetime,timezone


class OwnedLookup(unittest.TestCase):
    def test_inactive_native_defaults_preserve_physical_count_and_reject_explicit_conflicts(self):
        r=subprocess.run(['node','tests/final_inactive_checks.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_complete_inactive_pile_allows_resale_but_keeps_bulk_blocked_and_incomplete_pile_stops(self):
        captures=load_evidence(ROOT/'docs/research/002/002-12/remediation-04/preflight.jsonl')
        samples={r['command']['operation']:r['response'] for r in captures if r['kind']=='NATIVE_READ'}
        peer=dict(context=samples['balance']['context'],fences=samples['balance']['fences'])
        class ReadOnlyDouble:
            incomplete=False
            def request(self,path):return dict(service='fc-production-v1',schema=2,attached=True,peer=peer)
            def execute(self,c):
                v=deepcopy(samples[c['operation']]);v['command_id']=c['id'];v['fences']=c['fences']
                now=datetime.now(timezone.utc).isoformat();v['freshness'].update(read_id=c['id'],network_at=now,observed_at=now)
                if self.incomplete and c['operation']=='transfer_list':v['coverage']['complete']=False
                return v
        with tempfile.TemporaryDirectory() as temp:
            double=ReadOnlyDouble()
            with closing(Evidence(Path(temp)/'complete.jsonl')) as e:
                self.assertTrue(preflight(double,e,sleep=lambda _:None))
            rows=load_evidence(Path(temp)/'complete.jsonl')
            self.assertTrue(any(r['kind']=='BULK_BLOCKED_UNTIL_CLASSIFIED' for r in rows))
            double.incomplete=True
            with closing(Evidence(Path(temp)/'incomplete.jsonl')) as e:
                self.assertFalse(preflight(double,e,sleep=lambda _:None))

    def test_actual_native_page_and_python_contract_agree_and_reject_wrong_owned_id(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'capture.json'
            r=subprocess.run(['node','tests/final_owned_checks.cjs',str(path)],cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            data=json.loads(path.read_text());self.assertEqual(data['evidence_class'],'OFFLINE_DOUBLE')
            for sample in data['samples']:parse_response(sample['response'],sample['command'],now=stamp(sample['now']))
            owned=data['samples'][-1];bad=deepcopy(owned['response'])
            bad['result']['network'][0]['query']['item_id']='item:'+'a'*24
            with self.assertRaises(ValueError):parse_response(bad,owned['command'],now=stamp(owned['now']))

    def test_won_outside_unassigned_requires_exact_independent_owned_item_and_paid_cost(self):
        with tempfile.TemporaryDirectory() as temp:
            clock=Clock();page=ResalePage(Path(temp),clock)
            f=Foundation(page,context=CONTEXT,journal_path=Path(temp)/'journal.sqlite3',fixture=True,
                now=clock.now,clock=clock.monotonic,sleep=clock.sleep)
            try:
                a,b=Acquirer(f),Bidder(f);a.cycle()
                page.candidate.update(trade_state='closed',expires=-1,native_is_won=True,bid_state='highest')
                page.watched=[deepcopy(page.candidate)];page.owned=[]
                item=deepcopy(page.candidate['item']);item['last_sale_price']=799;page.owned_by_id=[item]
                b.cycle();self.assertEqual(page.mutations,[])
                item['last_sale_price']=800;b.cycle();b.cycle()
                self.assertEqual([c['operation'] for c in page.mutations],['move','list'])
                self.assertTrue(any(c['operation']=='owned_item' for c in page.calls))
                proof=next(e for e in f.registry.events() if e.get('reason')=='OWNED_WIN_VERIFIED')
                self.assertEqual(f.adapter.responses[proof['owned_read_id']]['operation'],'owned_item')
                self.assertEqual(proof['paid'],800)
            finally:f.close();page.close()

    def test_unclassified_inactive_inventory_blocks_maintenance_without_disabling_resale_actor(self):
        with tempfile.TemporaryDirectory() as temp:
            clock=Clock();page=ResalePage(Path(temp),clock)
            f=Foundation(page,context=CONTEXT,journal_path=Path(temp)/'journal.sqlite3',fixture=True,
                now=clock.now,clock=clock.monotonic,sleep=clock.sleep)
            try:
                with patch.object(SoldClear,'step',side_effect=ValueError('unproven_native_bulk_semantics')):
                    self.assertEqual(TransferMaintenance(f).cycle()['status'],'BLOCKED_NATIVE_INVENTORY')
                self.assertFalse(page.mutations)
                with patch.object(SoldClear,'step',side_effect=ValueError('stale_owner_or_epoch')):
                    with self.assertRaises(ValueError):TransferMaintenance(f).cycle()
            finally:f.close();page.close()


if __name__=='__main__':unittest.main(verbosity=2)

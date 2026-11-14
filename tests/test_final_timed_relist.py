"""Verify real expiry-countdown contracts with delayed independent readbacks."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_00209_bulk import BulkPage,Clock,CONTEXT
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.bulk import BulkTransfer


class TimedRelist(unittest.TestCase):
    def run_case(self,duration):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);clock=Clock();page=BulkPage(root,clock);page.transfer_items=page.transfer_items[2:]
            f=Foundation(page,context=CONTEXT,journal_path=root/'journal.sqlite3',fixture=True,
                now=clock.now,clock=clock.monotonic,sleep=clock.sleep)
            try:
                def elapsed(service,stage):
                    if stage!='ack':return
                    clock.sleep(12)
                    targets=set(page.writes[-1]['params']['expected_item_ids'])
                    for row in page.transfer_items:
                        if row['item']['item_id'] in targets:row['expires']=duration-12
                        elif row['expires']>0:row['expires']-=12
                with patch.object(BulkTransfer,'checkpoint',elapsed):result=f.bulk('relist_all')
                self.assertEqual(len(page.writes),1)
                return result['status']
            finally:f.close();page.close()

    def test_delayed_3588_remaining_proves_actual_3600_second_listing(self):
        self.assertEqual(self.run_case(3600),'CONFIRMED')

    def test_actual_half_hour_or_two_hour_server_duration_is_rejected(self):
        for duration in (1800,7200):
            with self.subTest(duration=duration):self.assertEqual(self.run_case(duration),'UNRESOLVED')


if __name__=='__main__':unittest.main(verbosity=2)

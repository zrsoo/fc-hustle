"""Offline protocol agreement for the mandatory native listing refresh."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.production_v1.contracts import parse_response,stamp


class ListingRefresh(unittest.TestCase):
    def test_native_refresh_is_counted_and_exactly_bound_while_duplicates_wrong_ids_and_writes_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'double.json'
            r=subprocess.run(['node','tests/list_refresh_checks.cjs',str(path)],cwd=ROOT,capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            data=json.loads(path.read_text());self.assertEqual(data['evidence_class'],'OFFLINE_DOUBLE')
            for sample in data['samples']:
                c,v=sample['command'],sample['response'];now=stamp(sample['now'])
                parse_response(v,c,now=now)
                for case in ('item','duplicate','count','host','status'):
                    wrong=deepcopy(v);aux=wrong['result']['network'][1]
                    if case=='item':aux['query']['item_id']='item:'+'a'*24
                    if case=='duplicate':wrong['result']['network'].append(deepcopy(aux));wrong['freshness']['request_count']+=1
                    if case=='count':wrong['freshness']['request_count']=1
                    if case=='host':aux['host']='utas.other.ea.com'
                    if case=='status':aux['status']=401
                    with self.subTest(case=case),self.assertRaises(ValueError):parse_response(wrong,c,now=now)


if __name__=='__main__':unittest.main(verbosity=2)

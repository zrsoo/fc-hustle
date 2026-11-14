"""Captured native effects require full independent proof even after HTTP 200."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from check_final_series_00212 import selected
from fc_access.actors_v1.final_run import load_evidence
from fc_access.actors_v1.final_assessment import bulk_proof


class NativeEffect(unittest.TestCase):
    def test_actual_expired_relist_effect_and_negative_wire_price_duration_identity_and_recovery_cases(self):
        root=ROOT/'docs/research/002/002-12';ids={}
        for log in root.rglob('*.jsonl'):
            if log.name not in {'native.jsonl','supervisor.jsonl','checkpoint.jsonl'}:
                for r in load_evidence(log):
                    if r['kind']=='NATIVE_READ':ids[r['command']['id']]=r['response']
            elif log.name=='native.jsonl':
                for r in load_evidence(log):
                    if r['kind']=='DISPATCH_RESULT' and r['response']:ids[r['command']['id']]=r['response']
        writes=[r for r in load_evidence(root/'remediation-05/live-06/native.jsonl')
            if r['kind']=='DISPATCH_RESULT' and r['command']['operation']=='relist_all']
        self.assertEqual(len(writes),1);w=writes[0]
        pre=ids[w['command']['params']['before_read_id']]
        post=next(r['response'] for r in load_evidence(root/'remediation-05/reconciliation-02.jsonl')
            if r['kind']=='NATIVE_READ' and r['command']['operation']=='transfer_list')
        s=selected();export=next(r['data'] for r in load_evidence(ROOT/s['checkpoint']) if r['kind']=='DURABLE_EXPORT')
        work=next(r for r in export['native'] if r['command_id']==w['command']['id'])
        kwargs=dict(started_at=work['started'],finished_at=work['finished'],recovery=True,effect_only=True)
        self.assertFalse(w['response']['result']['success'])
        self.assertTrue(bulk_proof(w,pre,post,**kwargs))
        with self.assertRaises(ValueError):bulk_proof(w,pre,post,started_at=work['started'],finished_at=work['finished'])
        for case in ('body','status','method','extra_write','price','hour','identity','missing_target','context','wrong_recovery_owner'):
            write,before,after=deepcopy((w,pre,post))
            n=write['response']['result']['network'][0]
            target=next(a for a in after['result']['auctions'] if a['item']['item_id'] in write['command']['params']['expected_item_ids'])
            if case=='body':n['body_empty']=False
            if case=='status':n['status']=403
            if case=='method':n['method']='GET'
            if case=='extra_write':write['response']['result']['network'].append(dict(n,method='POST'))
            if case=='price':target['buy_now_price']+=100
            if case=='hour':target['expires']=7200
            if case=='identity':target['item']['definition_id']+=1
            if case=='missing_target':after['result']['auctions'].remove(target)
            if case=='context':after['context']['account']='a'*32
            if case=='wrong_recovery_owner':after['fences'].update(epoch=write['command']['fences']['epoch'],owner='a'*32)
            with self.subTest(case=case),self.assertRaises(ValueError):bulk_proof(write,before,after,**kwargs)


if __name__=='__main__':unittest.main(verbosity=2)

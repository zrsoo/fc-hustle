"""Independent listing-proof negative cases using only isolated native doubles."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_00208_resale import ResalePage,Clock,CONTEXT
from fc_access.production_v1.foundation import Foundation
from fc_access.actors_v1.actors import Acquirer,Bidder
from fc_access.actors_v1.final_assessment import listing_proof


class ListingAssessment(unittest.TestCase):
    def test_owned_paid_caps_stored_price_native_tick_independent_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);clock=Clock();page=ResalePage(root,clock)
            f=Foundation(page,context=CONTEXT,journal_path=root/'journal.sqlite3',fixture=True,
                now=clock.now,clock=clock.monotonic,sleep=clock.sleep)
            try:
                a,b=Acquirer(f),Bidder(f);a.cycle()
                page.candidate.update(trade_state='closed',expires=0,native_is_won=True,bid_state='highest')
                page.watched=[deepcopy(page.candidate)];page.owned=[deepcopy(page.candidate['item'])]
                page.owned[0]['last_sale_price']=800;b.cycle();b.cycle()
                c=next(c for c in page.mutations if c['operation']=='list');p=c['params']
                write=dict(command=c,response=page.store.result(c['id']))
                before=f.adapter.responses[p['owned_read_id']];caps=f.adapter.responses[p['caps_read_id']]
                event=next(e for e in reversed(f.registry.events()) if e.get('command_id')==c['id'] and e.get('reason')=='VERIFIED')
                after=f.adapter.responses[event['read_ids'][0]]
                kwargs=dict(stored_price=p['buy_now_price'],previous_tick=p['starting_bid'],started_at=page.listed_at)
                self.assertTrue(listing_proof(write,before,caps,after,**kwargs))
                ambiguous=deepcopy(write)
                ambiguous['response']['result'].update(success=False,error='ambiguous_network')
                with self.assertRaises(ValueError):listing_proof(ambiguous,before,caps,after,**kwargs)
                self.assertTrue(listing_proof(ambiguous,before,caps,after,**kwargs,reconciled=True))
                bad=deepcopy(ambiguous)
                bad['response']['result']['network'].append(deepcopy(bad['response']['result']['network'][0]))
                with self.assertRaises(ValueError):listing_proof(bad,before,caps,after,**kwargs,reconciled=True)
                for mutation in ('price','duration','ownership','paid','read_reuse','caps','tick'):
                    w,pre,cap,post,k=deepcopy((write,before,caps,after,kwargs))
                    if mutation=='price':post['result']['auctions'][0]['buy_now_price']+=100
                    if mutation=='duration':post['result']['auctions'][0]['expires']=7200
                    if mutation=='ownership':pre['result']['auctions'][0]['item']['item_id']='item:'+'a'*24
                    if mutation=='paid':pre['result']['auctions'][0]['item']['last_sale_price']=799
                    if mutation=='read_reuse':post['command_id']=pre['command_id']
                    if mutation=='caps':cap['result']['caps']['maximum']=p['buy_now_price']-100
                    if mutation=='tick':k['previous_tick']-=100
                    with self.subTest(mutation=mutation),self.assertRaises(ValueError):listing_proof(w,pre,cap,post,**k)
            finally:f.close();page.close()


if __name__=='__main__':unittest.main(verbosity=2)

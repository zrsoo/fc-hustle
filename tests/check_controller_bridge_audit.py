"""Independently parse retained read-only captures and replay the production quote."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.protocol import delivery_response
from fc_access.production_v1.contracts import stamp
from fc_access.production_v1.adapter import NativeAdapter
from fc_access.production_v1.prices import PriceService,CardKey
from fc_access.production_v1.pricing import PricingService
from fc_access.production_v1.price_cache import QuoteCache

BASE=ROOT/'docs/research/004/bridge-audit'


def validate():
    seal=json.loads((BASE/'sealed-live-evidence.json').read_text(encoding='utf-8'))
    allowed={f'{directory}/{name}' for directory in ('live-01','live-02')
             for name in ('checkpoint.jsonl','result.json','transport.sqlite')}|{'live-01/quotes.sqlite'}
    assert set(seal['files'])==allowed
    for name,digest in seal['files'].items():
        assert hashlib.sha256((BASE/name).read_bytes()).hexdigest()==digest,'captured evidence changed'
    windows=[]
    for name in ('live-01','live-02'):
        records=[json.loads(line) for line in (BASE/name/'checkpoint.jsonl').read_text(encoding='utf-8').splitlines()]
        reserved=[r for r in records if r['kind']=='RESERVED_BEFORE_DELIVERY']
        native=[r for r in records if r['kind']=='NATIVE_RESULT']
        final=json.loads((BASE/name/'result.json').read_text(encoding='utf-8'))
        assert records[0]['kind']=='PREPARED' and records[-1]['kind']=='CLOSED'
        assert final['controllers_started']==final['mutations']==final['max_mutations']==0
        assert final['service_stopped'] and final['pending_commands']==0
        assert len(reserved)==len(native)==final['commands']<=final['max_commands']
        assert sum(r['reserved_ea'] for r in reserved)==final['reserved_ea_requests']<=final['max_reserved_ea_requests']
        count=0
        for reservation,record in zip(reserved,native):
            c,v=record['command'],record['response']
            assert reservation['command']==c and c['operation'] in {'balance','watched','search','status_batch','transfer_list','unassigned','caps','price_helpers'}
            assert stamp(reservation['at'])<=stamp(record['at'])
            at=v['observed_at'] if c['schema']==4 else v['freshness']['observed_at']
            delivery_response(v,c,now=stamp(at))
            r=v if c['schema']==4 else v['result'];assert r['success']
            assert all(n['method']=='GET' and n['status']==200 and n['session_header_present'] for n in r['network'])
            count+=len(r['network'])
        assert count==final['actual_ea_requests']<=final['reserved_ea_requests']
        windows.append((native,final))
    first,final=windows[0]
    balance=next(r['response'] for r in first if r['command']['operation']=='balance')
    assert balance['credits']==63702 and len(balance['network'])==1 and balance['designated_account_verified']
    discovery=next(r for r in first if r['command']['operation']=='search' and r['command']['params']['purpose']=='discovery')
    assert discovery['command']['params']==dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000)
    quote=final['pricing'];candidate_id=quote['evidence']['candidate']['trade_id']
    candidate=next(r for r in discovery['response']['result']['auctions'] if r['trade_id']==candidate_id)
    pricing=[r for r in first if r['command']['operation']=='search' and r['command']['params']['purpose']=='pricing']
    assert len(pricing)==2 and pricing[0]['command']['params']['definition_id']==251852
    assert 'max_buy' not in pricing[0]['command']['params'] and pricing[1]['command']['params']['max_buy']==4600
    assert pricing[1]['response']['result']['network'][0]['query']['maxb']==4600

    # Replay exact retained native envelopes, without fabricating timestamps or
    # contacting localhost/EA. IDs and parameters must match each retained call.
    start=next(i for i,r in enumerate(first) if r['command']['operation']=='price_helpers')
    stream=first[start:]
    class Replay:
        def __init__(self):self.index=0;self.now=stamp(stream[0]['response']['freshness']['observed_at'])
        def attach(self,*args):return deepcopy(stream[0]['command']['fences'])
        def execute(self,c):
            row=stream[self.index];assert c==row['command'],'retained native contract changed'
            self.index+=1;self.now=stamp(row['response']['freshness']['observed_at'])
            return deepcopy(row['response'])
    replay=Replay();context=stream[0]['command']['context'];fences=stream[0]['command']['fences']
    adapter=NativeAdapter(replay,context=context,owner=fences['owner'],epoch=fences['epoch'],now=lambda:replay.now)
    ids=lambda:stream[replay.index]['command']['id']
    prices=PriceService(adapter,ids);rules=prices.load(key=CardKey(251852))
    assert prices.helpers([('above',500),('below',11000)])==[550,10750]
    with tempfile.TemporaryDirectory() as path:
        cache=QuoteCache(Path(path)/'quotes.sqlite')
        try:
            pricing_service=PricingService(adapter,ids,cache)
            rebuilt=pricing_service.quote(candidate,rules,X=500)
            assert replay.index==len(stream) and rebuilt.completed and rebuilt.status=='COMPLETE'
            assert rebuilt.resale_price==quote['resale_price']==4200
            assert rebuilt.max_affordable_bid==quote['max_affordable_bid']==3400
            assert rebuilt.evidence['first_min']==4600 and rebuilt.evidence['price_searches']==2
            assert rebuilt.evidence['exclusions']==quote['evidence']['exclusions']
            before=replay.index;hit=pricing_service.quote(candidate,rules,X=500)
            assert hit.evidence['cache_hit'] and replay.index==before
        finally:cache.close()
    assert final['cache']==dict(hit=True,extra_ea_requests=0,resale_price=4200,restart_readable=True)
    status_rows,status_final=windows[1]
    assert status_final['status_links']==dict(requested=10,returned=10,missing=0,validated_full_version_links=10)
    market=status_rows[0]['response'];status=status_rows[1]['response'];command=status_rows[1]['command']
    expected=[dict(trade_id=r['trade_id'],item_id=r['item']['item_id'],definition_id=r['item']['definition_id']) for r in market['result']['auctions'][:10]]
    assert command['params']['targets']==expected and len(status['network'])==1 and len(status['auctions'])==10
    for row,link,target in zip(status['auctions'],status['links'],expected):
        assert row['trade_id']==target['trade_id'] and row['item']['item_id']==target['item_id']
        assert link['target']==target and link['full_read_id']==market['command_id'] and link['current_dto_matches']
    return dict(status='PASS',retained_ea_gets=sum(v['actual_ea_requests'] for _,v in windows),
        mutations=0,commands=sum(v['commands'] for _,v in windows),balance=63702,
        independent_pricing_replay=True,first_min=4600,resale_price=4200,ceiling=3400,
        cache_hit_without_get=True,exact_status_targets=10)


if __name__=='__main__':print(json.dumps(validate()))

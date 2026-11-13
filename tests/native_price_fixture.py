"""Offline native service doubles for retained journal/queue regression suites.

Tick formulas are fixtures, never a production fallback or approval artifact.
The end-to-end 001d-03 suite executes the shipped JavaScript separately.
"""
import itertools
from copy import deepcopy
from datetime import datetime, timezone
from fc_access.production_v1.prices import PriceService, CardKey
from fc_access.production_v1.contracts import command, empty_result


class FixturePriceAdapter:
    source = 'fixture'
    def __init__(self, definition_id=123, minimum=150, maximum=20000):
        self.definition_id, self.minimum, self.maximum = definition_id, minimum, maximum
        self.context = dict(account='a'*32, persona='b'*32, game='fc27', platform='pc', identity_namespace='c'*32)
        self.fences = dict(owner='d'*32, epoch=1, host_epoch='e'*32, worker_epoch='f'*32, document='1'*32)
        self.now = lambda: datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.searches = []

    def envelope(self, command_id, operation, params):
        return command(dict(schema=2, id=command_id, operation=operation, params=params,
                            context=deepcopy(self.context), fences=deepcopy(self.fences)))

    def search(self, command_id, query):
        self.searches.append(query.params())
        prices = [12000, 12250, 12500, 12750, 13000]
        rows = [auction(self.definition_id, price, i+100) for i, price in enumerate(prices)
                if query.max_buy is None or price <= query.max_buy]
        return search_response(self, command_id, query, rows)

    def price_helpers(self, command_id, probes=()):
        tiers = [(100000,1000),(50000,500),(10000,250),(1000,100),(150,50),(0,150)]
        rows=[]
        for p in probes:
            value=p['value']; above=p['direction']=='above'
            if value==0 and not above: price=0
            else:
                _,step=next(t for t in tiers if value>=t[0] if above or value>t[0])
                raw=value+step if above else value-step
                price=min(15000000,(raw+step//2)//step*step) if above else max(0,(raw+step//2)//step*step)
            rows.append(dict(p,price=price))
        return dict(result=dict(probes=rows))

    def caps(self, command_id, definition_id):
        if definition_id!=self.definition_id: raise ValueError('rules_identity_mismatch')
        return dict(command_id=command_id,result=dict(caps=dict(definition_id=definition_id,minimum=self.minimum,maximum=self.maximum)))


def native_rules(definition_id=123, minimum=150, maximum=20000):
    adapter=FixturePriceAdapter(definition_id,minimum,maximum)
    ids=itertools.count(10000)
    service=PriceService(adapter,lambda:f'{next(ids):032x}')
    return service.load(key=CardKey(definition_id)),service


def auction(definition_id=123, price=1500, n=100):
    return dict(trade_id=f'trade:{n:024x}', item=dict(item_id=f'item:{n:024x}',
                definition_id=definition_id, untradeable=False, last_sale_price=0),
                starting_bid=150, current_bid=0, buy_now_price=price, expires=300,
                trade_state='active', bid_state='none', native_is_won=False)


def search_response(adapter, command_id, query, rows):
    r = empty_result(None)
    r.update(success=True, status=200, cache_invalidated=True, auctions=deepcopy(rows))
    wire = dict(start=0, num=21, definitionId=query.definition_id)
    if query.max_buy is not None: wire['maxb'] = query.max_buy
    r['network'] = [dict(host='utas.test.ea.com', method='GET', path='/ut/game/fc27/transfermarket',
                         query=wire, status=200, session_header_present=True)]
    at = adapter.now().isoformat()
    return dict(schema=2, command_id=command_id, operation='search', context=deepcopy(adapter.context),
                fences=deepcopy(adapter.fences), result=r, freshness=dict(observed_at=at, network_at=at,
                request_count=1, read_id=command_id, source=adapter.source),
                coverage=dict(complete=False, has_more=True), timing=dict(native_service_ms=1))


def completed_quote(prices, path):
    from fc_access.production_v1.pricing import PricingService
    from fc_access.production_v1.price_cache import QuoteCache
    cache = QuoteCache(path)
    try:
        ids = itertools.count(20000)
        service = PricingService(prices.service.adapter, lambda:f'{next(ids):032x}', cache)
        return service.quote(auction(prices.key.definition_id, n=1), prices)
    finally:
        cache.close()

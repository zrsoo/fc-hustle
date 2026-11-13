"""In-process protocol-2 EA double. No sockets or real account operations."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from native_price_fixture import FixturePriceAdapter, auction
from fc_access.production_v1.contracts import ROUTES, empty_result
from fc_access.production_v1.foundation import Foundation, JournalAuthority
from fc_access.production_v1.store import Store

CONTEXT = dict(account='a'*32, persona='b'*32, game='fc27', platform='pc', identity_namespace='c'*32)


class Clock:
    def __init__(self):
        self.wall = datetime.now(timezone.utc)
        self.elapsed = 0
    def now(self):
        from datetime import timedelta
        return self.wall+timedelta(seconds=self.elapsed)
    def monotonic(self): return self.elapsed
    def sleep(self, seconds): self.elapsed += seconds


class Page:
    def __init__(self, directory, clock, *, crash=None):
        self.directory, self.clock, self.crash = Path(directory), clock, crash
        self.store = Store(self.directory/'transport.sqlite3', authorize_bid=JournalAuthority(self.directory/'journal.sqlite3'),
                           source='fixture', now=clock.now)
        self.calls, self.bid_calls, self.real_account_writes = [], 0, 0
        self.helper = FixturePriceAdapter()
        self.candidate = auction(123, 15000, 1)
        self.candidate['starting_bid'] = 2500
        self.watched = [self.candidate]
        self.credits = 90000
        self.failure = None
        self.on_bid = lambda c: None

    def ownership_epoch(self, context):
        owner = self.store.owner()
        return owner['epoch'] if owner else 0

    def attach(self, context, owner, epoch):
        self.store.activate(dict(context=context, owner=owner, epoch=epoch))
        self.peer = dict(context=deepcopy(context), fences=dict(owner=owner, epoch=epoch,
            host_epoch=self.store.host_epoch, worker_epoch='e'*32, document='f'*32))
        return deepcopy(self.peer['fences'])

    def execute(self, c):
        self.calls.append(deepcopy(c))
        op = c['operation']
        if op != 'price_helpers':
            self.store.enqueue(c, self.peer)
            assert self.store.claim(self.peer) == c
        if op == 'bid':
            self.bid_calls += 1
            self.on_bid(c)
            if self.crash == 'claimed':
                (self.directory/'native-called.json').write_text(json.dumps({'command_id': c['id']}))
                os._exit(19)
            if self.failure:
                self.store.uncertain(c['id'])
                raise self.failure
        r = empty_result(None)
        r.update(success=True, status=200, cache_invalidated=op in {'search', 'watched'})
        query = {}
        if op == 'search':
            p = c['params']
            query = dict(start=0, num=21, definitionId=p['definition_id'])
            for field, wire in [('max_bid','macr'),('min_buy','minb'),('max_buy','maxb')]:
                if field in p: query[wire] = p[field]
            r['auctions'] = [deepcopy(self.candidate)] if p['purpose'] == 'discovery' else [auction(123, 12000, 100)]
        elif op == 'watched': r['auctions'] = deepcopy(self.watched)
        elif op == 'balance': r['credits'] = self.credits
        elif op == 'caps':
            r['caps'] = dict(definition_id=c['params']['definition_id'], minimum=150, maximum=50000)
            query = dict(defId=c['params']['definition_id'])
        at = self.clock.now().isoformat()
        f = dict(observed_at=at, network_at=at, request_count=1, read_id=c['id'], source='fixture')
        if op == 'price_helpers':
            r = dict(success=True,error=None,version=1,above_available=True,below_available=True,
                     probes=self.helper.price_helpers(c['id'], c['params']['probes'])['result']['probes'],network=[])
            f.update(network_at=None, request_count=0)
        else:
            method, route = ROUTES[op]
            r['network'] = [dict(host='utas.test.ea.com',method=method,path=route,query=query,
                                 status=200,session_header_present=True)]
        value = dict(schema=2, command_id=c['id'], operation=op, context=deepcopy(c['context']),
            fences=deepcopy(c['fences']), result=r, freshness=f,
            coverage=dict(complete=False,has_more=None if op=='price_helpers' else False), timing=dict(native_service_ms=1))
        self.clock.sleep(.005)
        if op != 'price_helpers': self.store.finish(self.peer, c['id'], value)
        return value

    def close(self): self.store.db.close()


def create(directory, *, crash=None, interval=0):
    clock = Clock()
    page = Page(directory, clock, crash=crash)
    f = Foundation(page, context=CONTEXT, journal_path=Path(directory)/'journal.sqlite3',
        fixture=True, now=clock.now, clock=clock.monotonic, sleep=clock.sleep, interval=interval)
    return f, page, clock


def admitted(f, page):
    from fc_access.production_v1.contracts import Search
    discovery = f.read('search', Search.discovery(123).params())
    watched = f.read('watched')
    funds = f.read('balance')
    result = f.admit(watched, page.candidate['trade_id'], funds)
    return result, watched, funds


if __name__ == '__main__':
    directory, mode = sys.argv[1:]
    f, page, clock = create(directory, crash=mode)
    try:
        decision, _, _ = admitted(f, page)
        if mode == 'intent':
            f.journal.dispatch = lambda *args: os._exit(19)
        result = f.bid(page.candidate['trade_id'], command_id='9'*32)
        print(json.dumps(dict(schema=1, decision=decision, result=result, registry=f.registry.current(),
                              native_fixture_bid_calls=page.bid_calls, real_account_writes=page.real_account_writes)))
    finally:
        f.close(); page.close()

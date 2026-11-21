"""Synthetic EA boundary for the complete shipped controller, not a policy model.

Uses real schema parsers, native pricing, SQLite admission/claim and tombstones.
All requests terminate here, without any socket, browser or production state.
"""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timedelta, timezone
import itertools
import json
from pathlib import Path
import sqlite3

from fc_access.controller_v1.adapter import ControllerAdapter
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller, identity
from fc_access.controller_v1.executor import SerializedExecutor
from fc_access.controller_v1.protocol import delivery_command
from fc_access.controller_v1.store import ControllerStore
from fc_access.production_v1.contracts import empty_result
from fc_access.production_v1.price_cache import QuoteCache
from native_price_fixture import auction, FixturePriceAdapter


class Clock:
    def __init__(self):self.value=0.;self.sleeps=[]
    def clock(self):return self.value
    def now(self):return datetime(2030,1,1,tzinfo=timezone.utc)+timedelta(seconds=self.value)
    def sleep(self,n):
        assert n>=0;self.sleeps.append(n);self.value+=n


class SyntheticEA:
    def __init__(self, store, clock, count):
        self.store,self.clock=store,clock
        self.context=FixturePriceAdapter().context
        self.fences=dict(FixturePriceAdapter().fences,host_epoch=store.host_epoch)
        self.rows=[auction(123,15000,n+1) for n in range(count)]
        self.offers=[auction(123,12000,1000),auction(123,12500,1001)]
        self.discovery=None;self.inventory=[];self.manual=[];self.owned=[]
        self.credits=50000;self.balance_fail=False;self.inventory_complete=True;self.watched_fail=False
        self.watch_capacity=50
        self.lost_mode='ok'
        self.search_throttle=False
        self.bid_modes={};self.missing=set();self.unmapped=set();self.full={};self.calls=[];self.phase=None
        self.duration=.01;self.on_request=None;self.active=0;self.max_active=0
        self.native=FixturePriceAdapter()

    def attach(self,context,owner,epoch):
        assert context==self.context and owner==self.fences['owner'] and epoch==self.fences['epoch']
        self.store.attach(dict(context=context,fences=self.fences))
        return deepcopy(self.fences)

    def execute(self,c):
        delivery_command(c)
        self.active+=1;self.max_active=max(self.max_active,self.active)
        try:
            assert self.active==1
            self.store.enqueue(c,self.store.peer)
            assert self.store.claim(self.store.peer)==c
            # Durability/lock contract: a second writer can commit during I/O.
            with closing(sqlite3.connect(self.store.path,timeout=.1)) as db,db:
                db.execute("INSERT INTO c4_events(kind,body) VALUES ('IO_WRITER','{}')")
            phase=self.phase() if self.phase else None
            self.calls.append(dict(command=deepcopy(c),at=self.clock.value,phase=phase))
            if self.on_request:self.on_request(c)
            at=self.clock.now().isoformat()
            self.clock.value+=self.duration
            v=self.shared(c,at) if c['schema']==2 else self.controller(c,at)
            self.store.finish(self.store.peer,c['id'],v)
            return v
        except Exception:
            self.store.uncertain(c['id']);raise
        finally:self.active-=1

    def shared(self,c,at):
        op=c['operation'];p=c['params'];r=empty_result(None)
        r.update(success=True,error=None,status=200)
        coverage=dict(complete=False,has_more=None)
        wire={};path={'search':'transfermarket','watched':'watchlist','transfer_list':'tradepile',
            'caps':'marketdata/pricelimits','owned_item':'item','unassigned':'purchased/items'}.get(op)
        if op=='price_helpers':
            r=dict(success=True,error=None,version=1,above_available=True,below_available=True,
                probes=self.native.price_helpers(c['id'],p['probes'])['result']['probes'],network=[])
        elif op=='caps':r['caps']=dict(definition_id=p['definition_id'],minimum=150,maximum=20000);wire={'defId':p['definition_id']}
        elif op=='search':
            rows=self.rows if self.discovery is None else self.discovery
            if p['purpose']=='discovery' and getattr(self,'pages',None) is not None:rows=self.pages.get(p.get('page',1),[])
            if p['purpose']=='pricing':rows=self.offers
            rows=[r for r in rows if r['item']['definition_id']==p.get('definition_id',r['item']['definition_id']) and
                  ('max_buy' not in p or r['buy_now_price']<=p['max_buy'])]
            r.update(auctions=deepcopy(rows),cache_invalidated=True);wire=dict(start=(p.get('page',1)-1)*20,num=21)
            for key,w in [('definition_id','definitionId'),('max_buy','maxb'),('max_bid','macr'),('min_buy','minb')]:
                if key in p:wire[w]=p[key]
            for row in rows:self.full[row['trade_id']]=(c['id'],at,deepcopy(row))
        elif op=='watched':
            r.update(auctions=deepcopy(self.manual),cache_invalidated=True)
            count=len(self.manual)
            coverage['watch_list']=dict(capacity=self.watch_capacity,wire_count=count,callback_count=count,
                repository_count=count,repository_full=count>=self.watch_capacity)
            if self.watched_fail:raise TimeoutError('synthetic_watched_failure')
            for row in self.manual:self.full[row['trade_id']]=(c['id'],at,deepcopy(row))
        elif op=='transfer_list':
            r.update(auctions=deepcopy(self.inventory),cache_invalidated=True)
            n=len(self.inventory)
            coverage=dict(complete=self.inventory_complete,has_more=not self.inventory_complete,
                transfer_list=dict(reason='TRANSFER_LIST_COMPLETE' if self.inventory_complete else 'TRANSFER_LIST_UNKNOWN',
                    wire_count=n,callback_count=n,repository_count=n,repository_end_of_list=self.inventory_complete))
        elif op in {'owned_item','unassigned'}:
            r.update(items=deepcopy(self.owned),cache_invalidated=True)
            if op=='owned_item':wire={'item_id':p['item_id']};r['items']=[i for i in r['items'] if i['item_id']==p['item_id']]
        if op!='price_helpers':r['network']=[dict(method='GET',path='/ut/game/fc27/'+path,host='utas.test.ea.com',query=wire,status=200,session_header_present=True)]
        if op=='search' and self.search_throttle:
            # EA search throttle: native HTTP 429, page error service_failed.
            r.update(success=False,error='service_failed',status=429,auctions=None);r['network'][0]['status']=429
        return dict(schema=2,command_id=c['id'],operation=op,context=deepcopy(c['context']),fences=deepcopy(c['fences']),
            result=r,freshness=dict(observed_at=self.clock.now().isoformat(),network_at=None if op=='price_helpers' or op=='search' and self.search_throttle else at,
                request_count=len(r['network']),read_id=c['id'],source='fixture'),coverage=coverage,timing=dict(native_service_ms=0))

    def controller(self,c,at):
        op=c['operation'];p=c['params'];targets=p.get('targets',[p['target']] if 'target' in p else [])
        v=dict(schema=4,command_id=c['id'],operation=op,context=deepcopy(c['context']),fences=deepcopy(c['fences']),
            success=True,error=None,status=200,network=[dict(method='PUT' if op=='bid' else 'DELETE' if op=='clear_lost' else 'GET',
                path='/ut/game/fc27/'+{'bid':'trade/:trade/bid','balance':'user/credits','status_batch':'trade/status/lite','clear_lost':'watchlist'}[op],
                host='utas.test.ea.com',targets=deepcopy(targets),status=200,session_header_present=True)],
            background=[],auctions=[],links=[],missing=[],credits=None,receipt=None,
            observed_at=self.clock.now().isoformat(),network_at=at,designated_account_verified=True)
        if op=='clear_lost':
            targets=p['targets']
            if self.lost_mode!='no_effect':self.manual=[r for r in self.manual if identity(r) not in targets]
            if self.lost_mode=='lost_reply':raise TimeoutError('synthetic_lost_cleanup_reply')
        elif op=='balance':
            if self.balance_fail:v.update(success=False,error='ambiguous_network',credits=None,network=[],network_at=None)
            else:v['credits']=self.credits
        elif op=='status_batch' and any(t['trade_id'] in self.unmapped for t in targets):
            # The real page fails the whole read when any target has no native DTO.
            v.update(success=False,error='known_identity_unavailable',status=None,network=[],network_at=None)
        elif op=='status_batch':
            for t in targets:
                if t['trade_id'] in self.missing:v['missing'].append(deepcopy(t));continue
                row=next((r for r in self.rows+self.manual if identity(r)==t),None)
                if row is None:v['missing'].append(deepcopy(t));continue
                full_id,full_at,_=self.full[t['trade_id']]
                r=deepcopy(row);r['item']['definition_id']=0;v['auctions'].append(r)
                v['links'].append(dict(target=deepcopy(t),full_read_id=full_id,full_observed_at=full_at,
                    status_read_id=c['id'],version_observed=False,current_dto_matches=True))
        elif op=='bid':
            row=next(r for r in self.rows if identity(r)==p['target']);before=row['bid_state']
            mode=self.bid_modes.get(row['trade_id'],'accept')
            if mode=='timeout':raise TimeoutError('synthetic_lost_delivery')
            if mode=='denied':
                # Shape of the real stage18 EA permission denial: wire 461, service 403.
                v.update(success=False,error='ambiguous_network',status=403);v['network'][0]['status']=461
                v['receipt']=dict(schema=1,verdict='UNCONFIRMED',reason='EMPTY_NATIVE_ITEMS',
                    wire_trade_id=row['trade_id'],wire_amount=p['amount'],wire_identity_matches=True,wire_amount_matches=True,
                    wire_item_count=None,wire_error_code=None,native_success=False,native_error_code=461,
                    native_error_name=None,native_item_count=0,matching_item_count=0,input_stale=False,
                    before_bid_state=before,auction=None)
                return v
            if mode=='no_credit':
                # Shape of the live EA insufficient-coins answer: wire 470, service 403.
                v.update(success=False,error='ambiguous_network',status=403);v['network'][0]['status']=470
                v['receipt']=dict(schema=1,verdict='UNCONFIRMED',reason='EMPTY_NATIVE_ITEMS',
                    wire_trade_id=row['trade_id'],wire_amount=p['amount'],wire_identity_matches=True,wire_amount_matches=True,
                    wire_item_count=None,wire_error_code=None,native_success=False,native_error_code=470,
                    native_error_name='NOT_ENOUGH_CREDIT',native_item_count=0,matching_item_count=0,input_stale=False,
                    before_bid_state=before,auction=None)
                return v
            if mode in {'reject','funds','price_change'}:
                v.update(success=False,error='bid_rejected',status=403);v['network'][0]['status']=403
                v['receipt']=dict(schema=1,verdict='REJECTED',reason='EXPLICIT_NATIVE_REJECTION',
                    wire_trade_id=row['trade_id'],wire_amount=p['amount'],wire_identity_matches=True,wire_amount_matches=True,
                    wire_item_count=0,wire_error_code=402,native_success=False,native_error_code=402,
                    native_error_name='NOT_ENOUGH_CREDIT',native_item_count=0,matching_item_count=0,input_stale=False,
                    before_bid_state=before,auction=None)
            else:
                row.update(current_bid=p['amount'],bid_state='outbid' if mode=='outbid' else 'highest')
                v['receipt']=dict(schema=1,verdict='ACCEPTED',reason='MATCHING_NATIVE_PARTICIPATION',
                    wire_trade_id=row['trade_id'],wire_amount=p['amount'],wire_identity_matches=True,wire_amount_matches=True,
                    wire_item_count=1,wire_error_code=None,native_success=True,native_error_code=None,native_error_name=None,
                    native_item_count=1,matching_item_count=1,input_stale=False,before_bid_state=before,auction=deepcopy(row))
        return v


class Harness:
    def __init__(self,path,count=3,*,threshold=40000,spacing=2,win_handler=None,ea_factory=SyntheticEA):
        self.path=Path(path);self.clock=Clock()
        self.store=ControllerStore(self.path/'controller.sqlite',write_authority=True,now=self.clock.now)
        self.ea=ea_factory(self.store,self.clock,count)
        self.executor=SerializedExecutor(self.ea,spacing=spacing,clock=self.clock.clock,sleep=self.clock.sleep)
        self.executor.now=self.clock.now
        self.adapter=ControllerAdapter(self.executor,context=self.ea.context,owner=self.ea.fences['owner'],epoch=1,now=self.clock.now)
        self.adapter.native.source='fixture'
        self.cache=QuoteCache(self.path/'quotes.sqlite')
        seq=itertools.count(10000);self.ids=lambda:f'{next(seq):032x}'
        self.config=ControllerConfig(entry_threshold=threshold,request_spacing=spacing)
        self.controller=Controller(self.store,self.adapter,self.cache,config=self.config,ids=self.ids,
            clock=self.clock.clock,sleep=self.clock.sleep,win_handler=win_handler)
        self.controller.resume()
        self.ea.phase=lambda:self.controller.journal.state()['phase']

    def calls(self,op):return [v for v in self.ea.calls if v['command']['operation']==op]
    def metrics(self,kind):return [json.loads(r[0]) for r in self.store.db.execute('SELECT body FROM c4_metrics WHERE kind=?',(kind,))]
    def attempts(self):return [dict(id=r[0],state=r[1],body=json.loads(r[2])) for r in self.store.db.execute('SELECT id,state,body FROM c4_attempts')]
    def close(self):self.cache.close();self.store.close()

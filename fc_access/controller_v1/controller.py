"""Sequential ACQUIRING/MANAGING policy; explicit steps, no import-time work.

The hosting application supplies a single owned SerializedExecutor, an isolated
store and completed quote cache. Verified win handling is integrated. No actors or
timers are launched here. step() is finite; run() has no acquisition backoff.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import math
import json
import secrets
import time

from fc_access.production_v1.contracts import Search, stamp, parse_response
from fc_access.production_v1.prices import PriceService, CardKey
from fc_access.production_v1.pricing import PricingService
from .config import ControllerConfig
from .executor import SerializedExecutor
from .journal import BatchJournal


def identity(row):
    return dict(trade_id=row['trade_id'],item_id=row['item']['item_id'],definition_id=row['item']['definition_id'])


class Controller:
    def __init__(self, store, adapter, cache, *, config=None, ids=lambda:secrets.token_hex(16),
                 clock=time.monotonic, sleep=time.sleep, win_handler=None):
        self.store,self.adapter,self.native=store,adapter,adapter.native
        self.config=config or ControllerConfig()
        if not isinstance(adapter.executor,SerializedExecutor) or self.native.executor is not adapter.executor:
            raise ValueError('one_serialized_executor_required')
        if adapter.executor.spacing!=self.config.request_spacing:
            raise ValueError('pacing_config_mismatch')
        if store.peer!={'context':adapter.context,'fences':adapter.fences}:
            raise ValueError('attached_scope_required')
        store.check_peer({'context':adapter.context,'fences':adapter.fences})
        self.ids,self.clock,self.sleep,self.now=ids,clock,sleep,store.now
        self.prices=PriceService(self.native,ids)
        self.pricing=PricingService(self.native,ids,cache)
        self.lock=store.controller_lock
        if not self.lock.acquire(blocking=False):raise RuntimeError('controller_step_already_running')
        try:
            self.journal=BatchJournal(store)
            self.journal.recover()
        finally:self.lock.release()
        self.win_handler=win_handler
        adapter.executor.guard=store.dispatch_guard
        from .work import Work
        self.work=Work(self)
        self.last_cycle=None
        self.mapping_refresh_needed=any(
            json.loads(row[0])['peer']!=store.peer for m in self.journal.members()
            for row in store.db.execute('SELECT body FROM c4_batches WHERE id=?',(m['batch_id'],)))

    def status(self):
        work=getattr(self,'work',None)
        return dict(**self.journal.state(),members=self.journal.members(),**self.journal.uncertainty(),
            maintenance=work.status() if work else {})

    def stop(self):
        return self._control('STOPPED')

    def pause(self):
        return self._control('PAUSED')

    def resume(self):
        self.store.check_peer({'context':self.adapter.context,'fences':self.adapter.fences})
        self.journal.checkpoint(lifecycle='RUNNING',reason='OPERATOR_RUN')
        return self.status()

    def _control(self, state):
        self.store.check_peer({'context':self.adapter.context,'fences':self.adapter.fences})
        with self.store.lock,self.store.db:
            self.journal.checkpoint(lifecycle=state,reason='OPERATOR_'+state)
            self.store.db.execute("UPDATE c4_commands SET state='UNKNOWN' WHERE state='WAITING'")
        # Dispatch checks the durable lifecycle again after pacing. This lock
        # drains the sole in-flight call; no maintenance thread is launched.
        with self.adapter.executor.lock:pass
        return self.status()

    def _read(self, op, **params):
        return self.native.read(self.ids(),op,params)

    def step(self):
        if not self.lock.acquire(blocking=False):raise RuntimeError('controller_step_already_running')
        try:
            if self.journal.state()['lifecycle']!='RUNNING':return self.status()
            self.store.check_peer({'context':self.adapter.context,'fences':self.adapter.fences})
            if self.journal.state()['phase']=='MANAGING':
                self._manage()
                # Settled management hands directly to acquisition in this step.
                if self.journal.members():return self.status()
            if self.journal.state()['lifecycle']=='RUNNING':
                # Maintenance also runs while acquisition is capacity constrained.
                self.work.maintenance()
                if self.journal.state()['lifecycle']=='RUNNING':self._acquire()
            return self.status()
        finally:self.lock.release()

    def run(self, *, steps=None):
        self.resume()
        count=0
        while self.journal.state()['lifecycle']=='RUNNING' and (steps is None or count<steps):
            self.step();count+=1

    def _acquire(self):
        j=self.journal;bid=self.ids();start=self.clock()
        j.begin(bid,asdict(self.config),self.now().isoformat())
        burst=None;handoff=None;expiry_misses=0
        try:
            balance_id=self.ids()
            try:balance=self.adapter.read(balance_id,'balance')
            except Exception:
                j.update_batch(bid,state='READ_FAILED',reason='CREDITS_READ_FAILED');return
            if not balance['success']:
                j.update_batch(bid,state='READ_FAILED',reason='CREDITS_READ_FAILED');return
            j.update_batch(bid,balance_read_id=balance_id,credits=balance['credits'],credits_at=balance['network_at'])
            if balance['credits']<=self.config.entry_threshold:
                reason='ENTRY_CREDITS_AT_OR_BELOW_THRESHOLD'
                j.update_batch(bid,state='HALTED',reason=reason)
                j.checkpoint(lifecycle='HALTED',reason=reason);return
            discovery=self.native.search(self.ids(),Search.discovery())
            at=discovery['freshness']['network_at']
            j.update_batch(bid,discovery=discovery,discovery_at=at)
            # Price each exact version once; the imported service owns all cache,
            # exclusion, early rejection, tax and native flooring policy.
            quotes={};rules_by_version={};prepared=[];eligible=[];trades=set();items=set()
            existing={m['target']['trade_id'] for m in j.members()}
            for row in discovery['result']['auctions']:
                t=identity(row)
                if t['trade_id'] in trades or t['item_id'] in items:continue
                trades.add(t['trade_id']);items.add(t['item_id'])
                if t['trade_id'] in existing or j.attempted(t) or row['trade_state']!='active' or row['bid_state'] not in {'none','outbid'} or row['item']['untradeable'] is not False:continue
                if row['expires']-(self.now()-stamp(at)).total_seconds()<=60:
                    expiry_misses+=1;continue
                version=t['definition_id']
                if version not in rules_by_version:
                    try:
                        rules_by_version[version]=self.prices.load(key=CardKey(version))
                    except Exception:
                        rules_by_version[version]=None
                rules=rules_by_version[version]
                if not rules:continue
                try:minimum=self._minimum(row,rules)
                except Exception:continue
                if minimum is not None:prepared.append((row,minimum,rules))
            # An illegal/expensive first row must not poison its whole version.
            # Price the cheapest legal representative once. Subsequent calls use
            # completed hits and still apply candidate-specific exclusions.
            for row,minimum,rules in sorted(prepared,key=lambda v:v[1]):
                version=row['item']['definition_id']
                if version not in quotes:
                    quotes[version]=self.pricing.quote(row,rules,X=500)
            for row,minimum,rules in prepared:
                t=identity(row);quote=quotes[t['definition_id']]
                if not quote.completed:continue
                quote=self.pricing.quote(row,rules,X=500)
                if quote.status!='COMPLETE' or not quote.completed:continue
                if minimum is None or quote.max_affordable_bid is None or minimum>quote.max_affordable_bid or row['buy_now_price'] and minimum>=row['buy_now_price']:continue
                eligible.append(dict(target=t,row=row,read_id=discovery['command_id'],observed_at=at,
                    deadline=(stamp(at)+timedelta(seconds=row['expires'])).isoformat(),minimum=minimum,
                    cap=quote.max_affordable_bid,resale_price=quote.resale_price,quote=asdict(quote)))
            # Complete physical inventory plus all known participations. A failed
            # watch/inventory read is unknown authority, never an empty pipeline.
            watched=self._read('watched')
            inventory=self._read('transfer_list')
            ic=self.native.commands[inventory['command_id']]
            parse_response(inventory,ic,now=self.now(),source=self.native.source)
            if not inventory['coverage']['complete']:
                j.update_batch(bid,state='INVENTORY_UNKNOWN',reason='COMPLETE_INVENTORY_REQUIRED');return
            self.work.inventory=inventory
            physical={r['item']['item_id'] for r in inventory['result']['auctions']}
            pending={r['item']['item_id'] for r in watched['result']['auctions'] if
                r['trade_state']=='active' and r['bid_state'] in {'highest','outbid'} or
                r['trade_state']=='closed' and r['bid_state']=='highest'}
            pending.update(m['target']['item_id'] for m in j.members())
            known=len(physical|pending)
            inv_at=inventory['freshness']['network_at']
            j.update_batch(bid,inventory_at=inv_at,inventory_read_id=inventory['command_id'],
                physical_count=len(physical),known_pipeline=known,known_pending_items=sorted(pending-physical))
            if len(physical)>=50 or known>=50:
                j.update_batch(bid,state='CAPACITY_FULL');return
            self.store.admit_batch(bid,balance_read_id=balance_id,inventory_command=ic,
                                   inventory_response=inventory,threshold=self.config.entry_threshold)
            with self.store.lock,self.store.db:self.store.db.execute('UPDATE c4_inventory SET valid=1 WHERE singleton=1')
            selected=[]
            for candidate in eligible:
                age=(self.now()-stamp(at)).total_seconds()
                remaining=candidate['row']['expires']-age
                if remaining<=60:
                    expiry_misses+=1;continue
                if candidate['target']['item_id'] in physical|pending:continue
                c=deepcopy(candidate);c.update(selection_age=age,selection_remaining=remaining)
                selected.append(c)
                if len(selected)>=min(10,50-known):break
            j.select(bid,selected)
            j.update_batch(bid,selection_at=self.now().isoformat(),selected_count=len(selected))
            burst=self.clock();submitted=[]
            for c in selected:
                age=(self.now()-stamp(c['observed_at'])).total_seconds()
                inv_age=(self.now()-stamp(inv_at)).total_seconds()
                reason=None
                if self.now()>=stamp(c['deadline']):reason='EXPIRED';expiry_misses+=1
                elif not j.inventory_valid() or not 0<=inv_age<=self.config.inventory_max_age:reason='INVENTORY_INVALID'
                if reason:
                    j.metric(bid,'INITIAL_SKIPPED',target=c['target'],reason=reason,observation_age=age,inventory_age=inv_age);continue
                result=self._bid(bid,c,c['read_id'],c['row'],'initial')
                if result:submitted.append(result)
            handoff=self.clock()
            if submitted:
                status=self._status([c['target'] for c,_,_ in submitted],bid)
                if status:
                    self._apply(status,{c['target']['trade_id']:c for c,_,_ in submitted},bid,initial=True,
                                after={c['target']['trade_id']:at for c,_,at in submitted})
                for c,cid,_ in submitted:
                    established=self.store.db.execute('SELECT 1 FROM c4_members WHERE trade_id=?',(c['target']['trade_id'],)).fetchone()
                    if not established:j.abandon(cid)
            j.update_batch(bid,state='MANAGING' if j.members() else 'SETTLED')
            if j.members():j.checkpoint(phase='MANAGING',batch_id=bid)
        except Exception:
            # Only finite enumerated categories enter the audit. Commands already
            # intended remain consumed even if the surrounding batch fails.
            j.update_batch(bid,state='OPERATION_FAILED',reason='ACQUISITION_OPERATION_FAILED')
            for cid,body in self.store.db.execute("SELECT id,body FROM c4_attempts WHERE batch_id=? AND state='ACKNOWLEDGED'",(bid,)).fetchall():
                trade=json.loads(body)['candidate']['target']['trade_id']
                if not self.store.db.execute('SELECT 1 FROM c4_members WHERE trade_id=?',(trade,)).fetchone():j.abandon(cid)
        finally:
            if j.members() and j.state()['lifecycle']=='RUNNING' and j.state()['phase']=='ACQUIRING':
                j.checkpoint(phase='MANAGING',batch_id=bid)
            end=self.clock()
            j.metric(bid,'ACQUISITION',elapsed=end-start,burst_elapsed=(handoff or end)-burst if burst is not None else 0,
                     handoff_elapsed=end-handoff if handoff is not None else 0,expiry_misses=expiry_misses)

    def _minimum(self, row, rules):
        return rules.minimum_bid(definition_id=row['item']['definition_id'],platform=self.adapter.context['platform'],
                                 starting_bid=row['starting_bid'],current_bid=row['current_bid'])

    def _bid(self, bid, candidate, read_id, row, kind):
        j=self.journal
        try:
            rules=self.prices.latest.get(CardKey(candidate['target']['definition_id']))
            rules=self.prices.loaded[rules] if rules else self.prices.load(key=CardKey(candidate['target']['definition_id']))
            amount=self._minimum(row,rules)
            if amount is None or amount>candidate['cap'] or row['buy_now_price'] and amount>=row['buy_now_price']:return None
            if j.attempted(candidate['target'],kind,amount=amount,read_id=read_id):return None
            deadline=(stamp(self._observation_at(read_id))+timedelta(seconds=row['expires'])).isoformat()
            if stamp(deadline)<=self.now():
                j.metric(bid,'EXPIRY_MISS',target=candidate['target']);return None
            decision=self.ids();cid=self.ids()
            self.store.decide(decision,batch_id=bid,status_read_id=read_id,identity=candidate['target'],
                amount=amount,minimum=amount,cap=candidate['cap'],deadline=deadline,kind=kind)
            params=dict(target=candidate['target'],amount=amount,minimum=amount,cap=candidate['cap'],
                deadline=deadline,status_read_id=read_id,batch_id=bid,decision_id=decision)
            j.intend(cid,bid,candidate,kind,params)
        except Exception:
            j.metric(bid,'DECISION_SKIPPED',target=candidate['target'],reason='LOCAL_AUTHORITY_INVALID');return None
        returned=None
        try:result=self.adapter.deliver(cid,params)
        except Exception:result=dict(command_id=cid,outcome='UNKNOWN',reason='DELIVERY_UNCONFIRMED',receipt=None,independently_confirmed=False)
        finally:returned=self.now().isoformat()
        j.outcome(cid,result)
        j.metric(bid,'BID',command_id=cid,target=candidate['target'],amount=amount,cap=candidate['cap'],
                 observation_age=(stamp(returned)-stamp(self._observation_at(read_id))).total_seconds(),
                 returned_at=returned,outcome=result['outcome'])
        return candidate,cid,returned

    def _observation_at(self, cid):
        if cid in self.adapter.responses:return self.adapter.responses[cid]['network_at']
        return self.native.responses[cid]['freshness']['network_at']

    def _status(self, targets, bid):
        try:
            status=self.adapter.status_batch(self.ids(),targets)
            if status['success']:return status
        except Exception:pass
        self.journal.metric(bid,'STATUS_UNKNOWN',targets=targets)
        return None

    def _apply(self, status, candidates, bid, *, initial=False, after=None):
        j=self.journal
        for trade,c in candidates.items():
            if after and stamp(status['network_at'])<=stamp(after[trade]):
                j.metric(bid,'UNCORRELATED_READBACK',target=c['target']);continue
            try:row,_=self.store.linked_row(status['command_id'],c['target'])
            except ValueError:
                j.metric(bid,'MISSING_OR_INVALID_ROW',target=c['target']);continue
            if row['trade_state']=='active' and row['bid_state'] in {'highest','outbid'}:
                j.member(bid,c,proof=dict(read_id=status['command_id'],row=row,at=status['network_at']))
            elif row['trade_state']=='closed' and row['bid_state']=='outbid' and row['native_is_won'] is not True:
                if initial:j.member(bid,c,proof=dict(read_id=status['command_id'],row=row))
                j.settle(trade,'LOST',dict(read_id=status['command_id'],row=row))
            elif row['trade_state']=='closed' and row['bid_state']=='highest' and row['native_is_won'] is not False:
                j.member(bid,c,state='PENDING_WIN',proof=dict(read_id=status['command_id'],row=row,at=status['network_at']))
        # Missing rows and elapsed countdowns deliberately preserve membership.

    def _wins(self):
        j=self.journal
        for m in j.members():
            if m['state']!='PENDING_WIN':continue
            try:
                prior=self.store.db.execute("SELECT 1 FROM c4_work WHERE json_extract(body,'$.params.item_id')=?",(m['target']['item_id'],)).fetchone()
                if prior and not self.win_handler:
                    proof=dict(terminal=m['proof'],paid=m['proof']['row']['current_bid'],recovery=True)
                    if self.work.win(m,proof):
                        j.settle(m['target']['trade_id'],'WON_ACCOUNTED',proof);j.invalidate_inventory()
                    continue
                owned=self._read('owned_item',**m['target'])
                rows=owned['result']['items'];row=m['proof']['row'];paid=row['current_bid']
                attempts=self.store.db.execute('SELECT a.body FROM c4_attempts a JOIN c4_tombstones t ON t.command_id=a.id WHERE a.batch_id=?',(m['batch_id'],))
                amounts=[v['params']['amount'] for v in map(lambda r:json.loads(r[0]),attempts)
                         if v['candidate']['target']==m['target']]
                if len(rows)!=1 or rows[0]['item_id']!=m['target']['item_id'] or rows[0]['definition_id']!=m['target']['definition_id'] or rows[0]['untradeable'] is not False or rows[0]['last_sale_price']!=paid or paid<=0 or paid not in amounts:
                    continue
                if row['expires']>0 or row['native_is_won'] is not True:continue
                proof=dict(terminal=m['proof'],owned=owned,paid=paid)
                j.metric(m['batch_id'],'WIN_VERIFIED',target=m['target'],paid=paid,owned_read_id=owned['command_id'])
                # Required move/list work is accounted for only by the verified
                # resale integration. Missing integration keeps the win pending.
                if (self.win_handler(deepcopy(m),proof) if self.win_handler else self.work.win(m,proof)):
                    j.settle(m['target']['trade_id'],'WON_ACCOUNTED',proof)
                    j.invalidate_inventory()
            except Exception:
                j.metric(m['batch_id'],'WIN_PENDING',target=m['target'])

    def _manage(self):
        j=self.journal;members=j.members()
        if not members:
            j.checkpoint(phase='ACQUIRING');return
        if self.last_cycle is not None:
            delay=self.last_cycle+self.config.cycle_target-self.clock()
            if delay>0:self.sleep(delay)
        start=self.clock();self.last_cycle=start;bid=members[0]['batch_id']
        # Pending wins remain exact targets too: refresh their terminal proof
        # before physical ownership reads, without treating them as rebid work.
        active=members
        try:
            if self.mapping_refresh_needed:
                try:self._read('watched')
                except Exception:
                    j.metric(bid,'MAPPING_RECOVERY_PENDING');return
                self.mapping_refresh_needed=False
            status=self._status([m['target'] for m in active],bid) if active else None
            if status:
                self._apply(status,{m['target']['trade_id']:m for m in active},bid)
                actions=[]
                current={m['target']['trade_id'] for m in j.members() if m['state']=='ACTIVE'}
                for m in active:
                    if m['target']['trade_id'] not in current:continue
                    try:row,_=self.store.linked_row(status['command_id'],m['target'])
                    except ValueError:continue
                    deadline=stamp(status['network_at'])+timedelta(seconds=row['expires'])
                    if row['trade_state']=='active' and row['bid_state']=='outbid' and deadline>self.now():
                        actions.append((deadline,m,row))
                    else:j.metric(bid,'HOLD',target=m['target'],reason='HIGHEST_OR_NOT_ACTIONABLE')
                submitted=[]
                for _,m,row in sorted(actions,key=lambda a:(a[0],a[1]['target']['trade_id'])):
                    result=self._bid(bid,m,status['command_id'],row,'rebid')
                    if result:submitted.append(result)
                    else:j.metric(bid,'HOLD',target=m['target'],reason='CAP_OR_LOCAL_AUTHORITY')
                if submitted:
                    readback=self._status([m['target'] for m,_,_ in submitted],bid)
                    if readback:self._apply(readback,{m['target']['trade_id']:m for m,_,_ in submitted},bid,
                        after={m['target']['trade_id']:at for m,_,at in submitted})
                    for m,cid,_ in submitted:
                        if not readback or m['target'] in readback['missing']:j.abandon(cid)
            self.work.recover_bulk()
            self._wins()
            self.work.maintenance(scan=True)
            if not j.members():
                j.update_batch(bid,state='SETTLED');j.checkpoint(phase='ACQUIRING')
        finally:
            elapsed=self.clock()-start
            j.metric(bid,'CYCLE',elapsed=elapsed,target=self.config.cycle_target,
                     missed_targets=max(0,math.ceil(elapsed/self.config.cycle_target)-1))

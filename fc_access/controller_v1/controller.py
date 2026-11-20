"""Sequential ACQUIRING -> MANAGING -> MAINTENANCE policy; explicit steps.

Each phase owns its writes: initial bids in ACQUIRING, rebids in MANAGING and
every account maintenance write (won-item move/list, clear_sold, relist_all and
clear_lost when the watch list is at capacity) only in MAINTENANCE. After a
maintenance write no bid is sent for ``maintenance_gap`` seconds.

The hosting application supplies a single owned SerializedExecutor, an isolated
store and completed quote cache. Verified win handling is integrated. No actors or
timers are launched here. step() is finite; run() has no acquisition backoff.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import math
import json
import re
import secrets
import time

from fc_access.production_v1.contracts import Search, stamp, parse_response, fresh
from fc_access.production_v1.prices import PriceService, CardKey
from fc_access.production_v1.pricing import PricingService
from .config import ControllerConfig
from .executor import SerializedExecutor
from .journal import BatchJournal


SAFE_ERRORS = {'ValueError','TypeError','KeyError','RuntimeError','TimeoutError','OSError','IndexError',
               'AttributeError','LookupError','ConnectionError','PermissionError','SupervisionLost'}


def error_code(error):
    """Finite diagnostic for an exception: its type, plus its message only when the
    message is itself a code (lower_snake_case), never free text or values."""
    name=type(error).__name__
    name=name if name in SAFE_ERRORS else 'Exception'
    text=str(error)
    return f'{name}:{text}' if re.fullmatch(r'[a-z0-9_]{1,64}',text) else name


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
        # Dispatch-time listing authority (work.validate) reads the same markup.
        store.list_markup=self.config.list_markup
        from .work import Work
        self.work=Work(self)
        self.last_cycle=None
        # After a restart the page can map only auctions present in the fresh
        # watch list. Members whose auction left it (e.g. won and moved off it by
        # EA) cannot be status-read in this runtime; they stay members with an
        # unknown outcome and never block management of the others.
        self.unmapped=set()
        # Acquisition holds (monotonic deadlines): EA search throttle and 461 bursts.
        self.search_hold_until=0.
        self.denial_hold_until=0.
        self.band_index=0
        # Credit gate: armed by an EA 470 NOT_ENOUGH_CREDIT. Bids above the last
        # balance read (refreshed at most every 30 s) are held instead of sent.
        self.credit_gate=False
        self.credit_view=None
        self.low_credit_maintenance=None
        # Coin reservation: per-band smallest cap seen in its last search (expires),
        # and whether the last round found that no band fits the spendable coins.
        self.band_floor={}
        self.coins_short=False
        self.last_maintenance=None
        # Diagnostics that log only on change (per auction, per decision point).
        self.hold_reasons={}
        self.last_interleave_wait=None
        self.last_hold_handoff=None
        self.credit_held_now=None
        # 461 wave: rounds whose opening bids were all denied, since the last
        # accepted opening bid (None when no wave is under way).
        self.denial_wave=None
        # Auctions outbid beyond our cap: prices only rise, so we can never act on
        # them again. They are still read until settled, but neither hold the
        # interleave window shut nor reserve coins.
        self.priced_out=set()
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
        self.store.require_supervision()
        if not self.lock.acquire(blocking=False):raise RuntimeError('controller_step_already_running')
        try:
            if self.journal.state()['lifecycle']!='RUNNING':return self.status()
            self.store.check_peer({'context':self.adapter.context,'fences':self.adapter.fences})
            phase=self.journal.state()['phase']
            if phase=='MANAGING':self._manage()
            elif phase=='MAINTENANCE':self._maintain()
            elif self._window_closed():pass
            elif self._gap_wait():pass
            elif self._acquisition_hold():pass
            else:self._acquire()
            return self.status()
        finally:self.lock.release()

    def run(self, *, steps=None, progress=None):
        self.resume()
        count=0
        while self.journal.state()['lifecycle']=='RUNNING' and (steps is None or count<steps):
            if progress:progress(self.status())
            state=self.step();count+=1
            if progress:progress(state)

    def _acquire(self):
        j=self.journal;bid=self.ids();start=self.clock()
        j.begin(bid,asdict(self.config),self.now().isoformat())
        burst=None;handoff=None;expiry_misses=0;long_skips=0;retries={};denied=0;attempted=0;coin_skips=0;accepted=0
        found=None;n_eligible=None;n_selected=None;band=None;spendable=None;spendable_start=None;min_skipped=None
        interleaved=self.config.interleave and any(self._needs_status(m) for m in j.members())
        try:
            balance_id=self.ids()
            try:balance=self.adapter.read(balance_id,'balance')
            except Exception:
                j.update_batch(bid,state='READ_FAILED',reason='CREDITS_READ_FAILED');return
            if not balance['success']:
                j.update_batch(bid,state='READ_FAILED',reason='CREDITS_READ_FAILED');return
            j.update_batch(bid,balance_read_id=balance_id,credits=balance['credits'],credits_at=balance['network_at'])
            self.credit_view=(balance['credits'],self.clock())
            if balance['credits']<=self.config.entry_threshold and self.config.low_credit_hold:
                # Coins are tied up in listings and highest bids: wait for sales and
                # settlements instead of halting; members keep being managed.
                j.metric(bid,'LOW_CREDITS',credits=balance['credits'],threshold=self.config.entry_threshold)
                self.low_credit_maintenance=self.clock()  # maintenance follows this batch
                j.update_batch(bid,state='LOW_CREDITS',reason='ENTRY_CREDITS_AT_OR_BELOW_THRESHOLD');return
            if balance['credits']<=self.config.entry_threshold:
                reason='ENTRY_CREDITS_AT_OR_BELOW_THRESHOLD'
                j.update_batch(bid,state='HALTED',reason=reason)
                j.checkpoint(lifecycle='HALTED',reason=reason);return
            spendable=None
            if self.config.coin_reservation:
                reserved,claims=self._reserved(detail=True)
                spendable=spendable_start=balance['credits']-reserved
                j.update_batch(bid,reserved=reserved,spendable=spendable,claims=claims)
                band=self._fitting_band(spendable)
                if band is None:
                    # Nothing can be funded: wait for settlements and sales; members
                    # stay managed and maintenance keeps relisting.
                    self.coins_short=True
                    self.low_credit_maintenance=self.clock()
                    j.metric(bid,'COINS_RESERVED',credits=balance['credits'],reserved=reserved,spendable=spendable)
                    j.update_batch(bid,state='COINS_RESERVED',reason='NO_BAND_FITS');return
                self.coins_short=False
            else:
                band=self.config.bands[self.band_index%len(self.config.bands)]
                self.band_index+=1
            try:discovery=self.native.search(self.ids(),Search.discovery(max_bid=band[0],min_buy=band[1]))
            except ValueError as error:
                if str(error)!='service_failed':raise
                # EA refused the search (HTTP 429 throttle): no acquisition for a while;
                # managing and maintenance continue.
                self.search_hold_until=self.clock()+self.config.throttle_pause
                j.metric(bid,'SEARCH_THROTTLED',pause=self.config.throttle_pause,band=list(band))
                j.update_batch(bid,state='THROTTLED',reason='SEARCH_THROTTLED');return
            at=discovery['freshness']['network_at']
            found=len(discovery['result']['auctions'] or [])
            j.update_batch(bid,discovery=discovery,discovery_at=at,band=list(band))
            # Price each exact version once; the imported service owns all cache,
            # exclusion, early rejection, tax and native flooring policy.
            quotes={};rules_by_version={};prepared=[];eligible=[];trades=set();items=set()
            existing={m['target']['trade_id'] for m in j.members()}
            for row in discovery['result']['auctions']:
                t=identity(row)
                if t['trade_id'] in trades or t['item_id'] in items:continue
                trades.add(t['trade_id']);items.add(t['item_id'])
                if t['trade_id'] in existing or row['trade_state']!='active' or row['bid_state'] not in {'none','outbid'} or row['item']['untradeable'] is not False:continue
                retry=self._retry_of(t)
                if retry is False:continue
                if row['expires']-(self.now()-stamp(at)).total_seconds()<=60:
                    expiry_misses+=1;continue
                if self.config.max_auction_seconds and row['expires']-(self.now()-stamp(at)).total_seconds()>self.config.max_auction_seconds:
                    long_skips+=1;continue
                if retry is not None:retries[t['trade_id']]=retry
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
                    quotes[version]=self.pricing.quote(row,rules,X=self.config.margin)
            for row,minimum,rules in prepared:
                t=identity(row);quote=quotes[t['definition_id']]
                if not quote.completed:continue
                quote=self.pricing.quote(row,rules,X=self.config.margin)
                if quote.status!='COMPLETE' or not quote.completed:continue
                if minimum is None or quote.max_affordable_bid is None or minimum>quote.max_affordable_bid or row['buy_now_price'] and minimum>=row['buy_now_price']:continue
                eligible.append(dict(target=t,row=row,read_id=discovery['command_id'],observed_at=at,
                    deadline=(stamp(at)+timedelta(seconds=row['expires'])).isoformat(),minimum=minimum,
                    cap=quote.max_affordable_bid,resale_price=quote.resale_price,quote=asdict(quote)))
                if t['trade_id'] in retries:eligible[-1]['retry_of']=retries[t['trade_id']]
            n_eligible=len(eligible)
            if eligible:self.band_floor[tuple(band)]=(min(c['cap'] for c in eligible),self.clock())
            # Complete physical inventory plus all known participations. A failed
            # watch/inventory read is unknown authority, never an empty pipeline.
            # Lost targets are cleared only by MAINTENANCE at capacity; a full
            # list is an ordinary CAPACITY_FULL outcome here, never a write.
            watched=self._read('watched')
            from .watch_capacity import slots
            watch_slots=slots(watched)
            j.update_batch(bid,watch_read_id=watched['command_id'],watch_slots=watch_slots)
            if self.config.coin_reservation:self._orphans(bid,watched)
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
            if len(physical)>=50 or known>=50 or watch_slots==0:
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
                if spendable is not None:
                    if candidate['cap']>spendable:
                        coin_skips+=1;min_skipped=candidate['cap'] if min_skipped is None else min(min_skipped,candidate['cap']);continue
                    spendable-=candidate['cap']
                c=deepcopy(candidate);c.update(selection_age=age,selection_remaining=remaining)
                selected.append(c)
                if len(selected)>=min(10,50-known,watch_slots):break
            n_selected=len(selected)
            if selected:
                refreshed=self._refresh_selection(bid,selected)
                if refreshed is None:
                    j.update_batch(bid,state='READ_FAILED',reason='PRE_BURST_STATUS_REQUIRED');return
                selected=refreshed
            j.select(bid,selected)
            j.update_batch(bid,selection_at=self.now().isoformat(),selected_count=len(selected))
            burst=self.clock();submitted=[]
            for c in selected:
                age=(self.now()-stamp(c['observed_at'])).total_seconds()
                inv_age=(self.now()-stamp(inv_at)).total_seconds()
                reason=None
                if self.now()>=stamp(c['deadline']):reason='EXPIRED';expiry_misses+=1
                elif not j.inventory_valid() or not fresh(inv_age,self.config.inventory_max_age):reason='INVENTORY_INVALID'
                if reason:
                    j.metric(bid,'INITIAL_SKIPPED',target=c['target'],reason=reason,observation_age=age,inventory_age=inv_age);continue
                result=self._bid(bid,c,c['read_id'],c['row'],'initial')
                if result:
                    submitted.append(result);attempted+=1
                    state=self.store.db.execute('SELECT state FROM c4_attempts WHERE id=?',(result[1],)).fetchone()
                    denied+=bool(state) and state[0]=='DENIED'
                    accepted+=bool(state) and state[0]=='ACKNOWLEDGED'
                    if attempted==2 and denied==2 and self.config.denial_pause>0:
                        # A 461 burst denies whole batches and clears within minutes:
                        # keep the remaining candidates for a later batch.
                        self.denial_hold_until=self.clock()+self.config.denial_pause
                        j.metric(bid,'DENIAL_BURST',pause=self.config.denial_pause,skipped=len(selected)-2)
                        break
            handoff=self.clock()
            self._denial_wave(bid,denied,accepted)
            if submitted:
                status=self._status([c['target'] for c,_,_ in submitted],bid)
                if status:
                    self._apply(status,{c['target']['trade_id']:c for c,_,_ in submitted},bid,initial=True,
                                after={c['target']['trade_id']:at for c,_,at in submitted})
                for c,cid,_ in submitted:
                    established=self.store.db.execute('SELECT 1 FROM c4_members WHERE trade_id=?',(c['target']['trade_id'],)).fetchone()
                    if not established:j.abandon(cid)
            j.update_batch(bid,state='MANAGING' if j.members() else 'SETTLED')
            j.checkpoint(phase='MANAGING' if j.members() else 'MAINTENANCE',batch_id=bid)
        except Exception as error:
            # Only finite enumerated categories enter the audit. Commands already
            # intended remain consumed even if the surrounding batch fails.
            j.update_batch(bid,state='OPERATION_FAILED',reason='ACQUISITION_OPERATION_FAILED',error=error_code(error))
            for cid,body in self.store.db.execute("SELECT id,body FROM c4_attempts WHERE batch_id=? AND state='ACKNOWLEDGED'",(bid,)).fetchall():
                trade=json.loads(body)['candidate']['target']['trade_id']
                if not self.store.db.execute('SELECT 1 FROM c4_members WHERE trade_id=?',(trade,)).fetchone():j.abandon(cid)
        finally:
            if j.state()['lifecycle']=='RUNNING' and j.state()['phase']=='ACQUIRING':
                j.checkpoint(phase='MANAGING' if j.members() else 'MAINTENANCE',batch_id=bid)
            report=getattr(self.store,'semantic_report',None)
            if report:
                with self.store.lock:
                    confirmed=self.store.db.execute('SELECT count(*) FROM c4_members WHERE batch_id=?',(bid,)).fetchone()[0]
                    uncertain=self.store.db.execute("SELECT count(*) FROM c4_attempts WHERE batch_id=? AND state IN ('UNKNOWN','ACKNOWLEDGED','INTENT')",(bid,)).fetchone()[0]
                    batch_state=self.store.db.execute('SELECT state FROM c4_policy_batches WHERE id=?',(bid,)).fetchone()[0]
                report(batch_id=bid,state=batch_state,confirmed=confirmed,uncertain=uncertain)
            end=self.clock()
            j.metric(bid,'ACQUISITION',elapsed=end-start,burst_elapsed=(handoff or end)-burst if burst is not None else 0,
                     handoff_elapsed=end-handoff if handoff is not None else 0,expiry_misses=expiry_misses,
                     long_skips=long_skips,retries=len(retries),denied=denied,attempted=attempted,coin_skips=coin_skips,
                     band=list(band) if band else None,found=found,eligible=n_eligible,selected=n_selected,
                     spendable_start=spendable_start,spendable_end=spendable,min_skipped_cap=min_skipped,
                     searches_last_hour=self.searches_last_hour(),interleaved=interleaved,
                     state=self.store.db.execute('SELECT state FROM c4_policy_batches WHERE id=?',(bid,)).fetchone()[0])
            if interleaved:self._overrun_check(bid,'ACQUIRING',end-start)

    def _minimum(self, row, rules):
        return rules.minimum_bid(definition_id=row['item']['definition_id'],platform=self.adapter.context['platform'],
                                 starting_bid=row['starting_bid'],current_bid=row['current_bid'])

    def _refresh_selection(self, bid, candidates):
        """One exact batch read after pricing, before immutable selection/intents.

        The quote and full version provenance remain unchanged. Only current
        auction state, expiry and its minimum legal bid come from this new read.
        Missing or no-longer-profitable rows confer no write authority.
        """
        status=self._status([c['target'] for c in candidates],bid)
        if status is None:return None
        refreshed=[]
        for old in candidates:
            try:row,_=self.store.linked_row(status['command_id'],old['target'])
            except ValueError:
                self.journal.metric(bid,'INITIAL_SKIPPED',target=old['target'],reason='PRE_BURST_TARGET_MISSING');continue
            age=(self.now()-stamp(status['network_at'])).total_seconds()
            remaining=row['expires']-age
            rules=self.prices.loaded[self.prices.latest[CardKey(old['target']['definition_id'])]]
            minimum=self._minimum(row,rules)
            if row['trade_state']!='active' or row['bid_state'] not in {'none','outbid'} or row['item']['untradeable'] is not False or remaining<=60 or minimum is None or minimum>old['cap'] or row['buy_now_price'] and minimum>=row['buy_now_price']:
                self.journal.metric(bid,'INITIAL_SKIPPED',target=old['target'],reason='PRE_BURST_NOT_ELIGIBLE');continue
            candidate=deepcopy(old)
            candidate.update(row=row,read_id=status['command_id'],observed_at=status['network_at'],minimum=minimum,
                deadline=(stamp(status['network_at'])+timedelta(seconds=row['expires'])).isoformat(),
                selection_age=age,selection_remaining=remaining,discovery_read_id=old['read_id'],
                discovery_observed_at=old['observed_at'],discovery_selection_age=old['selection_age'])
            refreshed.append(candidate)
        self.journal.metric(bid,'PRE_BURST_STATUS',read_id=status['command_id'],requested=len(candidates),eligible=len(refreshed))
        return refreshed

    def _bid(self, bid, candidate, read_id, row, kind):
        self.store.require_supervision()
        j=self.journal;self.credit_held_now=None
        try:
            rules=self.prices.latest.get(CardKey(candidate['target']['definition_id']))
            rules=self.prices.loaded[rules] if rules else self.prices.load(key=CardKey(candidate['target']['definition_id']))
            amount=self._minimum(row,rules)
            if amount is None or amount>candidate['cap'] or row['buy_now_price'] and amount>=row['buy_now_price']:
                if kind=='rebid' and amount is not None:self._mark_priced_out(bid,candidate,row,amount)
                return None
            retry_of=candidate.get('retry_of') if kind=='initial' else None
            if j.attempted(candidate['target'],kind,amount=amount,read_id=read_id,retry_of=retry_of):return None
            if self.credit_gate:
                credits=self._credits()
                if credits is not None and amount>credits:
                    self._hold(bid,candidate['target'],'NOT_ENOUGH_CREDIT',amount=amount,credits=credits)
                    self.credit_held_now=candidate['target']['trade_id']
                    return None
            deadline=(stamp(self._observation_at(read_id))+timedelta(seconds=row['expires'])).isoformat()
            if stamp(deadline)<=self.now():
                j.metric(bid,'EXPIRY_MISS',target=candidate['target']);return None
            decision=self.ids();cid=self.ids()
            self.store.decide(decision,batch_id=bid,status_read_id=read_id,identity=candidate['target'],
                amount=amount,minimum=amount,cap=candidate['cap'],deadline=deadline,kind=kind,retry_of=retry_of)
            params=dict(target=candidate['target'],amount=amount,minimum=amount,cap=candidate['cap'],
                deadline=deadline,status_read_id=read_id,batch_id=bid,decision_id=decision)
            j.intend(cid,bid,candidate,kind,params)
        except Exception as error:
            j.metric(bid,'DECISION_SKIPPED',target=candidate['target'],reason='LOCAL_AUTHORITY_INVALID',bid_kind=kind,
                     error=error_code(error));return None
        returned=None
        try:result=self.adapter.deliver(cid,params)
        except Exception:result=dict(command_id=cid,outcome='UNKNOWN',reason='DELIVERY_UNCONFIRMED',receipt=None,independently_confirmed=False)
        finally:returned=self.now().isoformat()
        j.outcome(cid,result)
        if result['outcome']=='REJECTED' and result.get('reason')=='not_enough_credit':
            self.credit_gate=True;self.credit_view=None
        receipt=result.get('receipt') or {}
        j.metric(bid,'BID',command_id=cid,target=candidate['target'],amount=amount,cap=candidate['cap'],
                 observation_age=(stamp(returned)-stamp(self._observation_at(read_id))).total_seconds(),
                 returned_at=returned,outcome=result['outcome'],bid_kind=kind,reason=result.get('reason'),
                 native_error=receipt.get('native_error_name') or receipt.get('native_error_code'),
                 receipt_reason=receipt.get('reason'),retry_of=candidate.get('retry_of') if kind=='initial' else None)
        self.hold_reasons.pop(candidate['target']['trade_id'],None)
        return candidate,cid,returned

    def _observation_at(self, cid):
        if cid in self.adapter.responses:return self.adapter.responses[cid]['network_at']
        return self.native.responses[cid]['freshness']['network_at']

    def _status(self, targets, bid):
        cid=self.ids();failure=None
        try:
            status=self.adapter.status_batch(cid,targets)
            if status['success']:return status
        except Exception as error:
            failure=type(error).__name__ if type(error).__name__ in {'ValueError','TypeError','KeyError','RuntimeError','TimeoutError','OSError'} else 'LOCAL_EXCEPTION'
        # A pre-transport failure has no native result to correlate. Retain its
        # planned logical invocation and safe type, never the exception value.
        self.journal.metric(bid,'STATUS_UNKNOWN',targets=targets,read_id=cid,exception_type=failure)
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
                j.member(c.get('batch_id',bid),c,proof=dict(read_id=status['command_id'],row=row,at=status['network_at']))
            elif row['trade_state']=='closed' and row['bid_state']=='outbid' and row['native_is_won'] is not True:
                if initial:j.member(c.get('batch_id',bid),c,proof=dict(read_id=status['command_id'],row=row))
                j.settle(trade,'LOST',dict(read_id=status['command_id'],row=row))
                self._closed(bid,c,row,'LOST')
            elif row['trade_state']=='closed' and row['bid_state']=='highest' and row['native_is_won'] is not False:
                before=self.store.db.execute('SELECT state FROM c4_members WHERE trade_id=?',(trade,)).fetchone()
                j.member(c.get('batch_id',bid),c,state='PENDING_WIN',proof=dict(read_id=status['command_id'],row=row,at=status['network_at']))
                if not before or before[0]!='PENDING_WIN':self._closed(bid,c,row,'WON')
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
                j.metric(m['batch_id'],'WIN_VERIFIED',target=m['target'],paid=paid,cap=m.get('cap'),owned_read_id=owned['command_id'])
                # Required move/list work is accounted for only by the verified
                # resale integration. Missing integration keeps the win pending.
                if (self.win_handler(deepcopy(m),proof) if self.win_handler else self.work.win(m,proof)):
                    j.settle(m['target']['trade_id'],'WON_ACCOUNTED',proof)
                    j.invalidate_inventory()
            except Exception:
                j.metric(m['batch_id'],'WIN_PENDING',target=m['target'])

    def _retry_of(self, target):
        """None: never tried. A command id: every earlier initial bid on this auction
        was 461-denied (no effect) and a retry is still allowed. False: not eligible."""
        history=self.journal.initial_history(target)
        if not history:return None
        if any(state!='DENIED' for _,state in history) or len(history)>self.config.denial_retries:return False
        return history[-1][0]

    def _credits(self):
        """Spendable coins from a balance read at most 30 s old, or None."""
        if self.credit_view is None or self.clock()-self.credit_view[1]>30:
            try:balance=self.adapter.read(self.ids(),'balance')
            except Exception:return None
            if not balance['success']:return None
            self.credit_view=(balance['credits'],self.clock())
            self._balance_metric(self.journal.state()['batch_id'],balance['credits'],'CREDIT_CHECK')
        return self.credit_view[0]

    def _denial_wave(self, bid, denied, accepted):
        """Wait out a 461 wave in-process. A round whose opening bids were all
        denied extends the acquisition pause (doubling, capped); the first
        accepted opening bid ends the wave. Rebids and management continue."""
        if accepted:
            if self.denial_wave:
                w=self.denial_wave
                self.journal.metric(bid,'DENIAL_WAVE',state='ENDED',rounds=w['rounds'],denials=w['denials'],
                                    started_at=w['started_at'],seconds=self.clock()-w['started'])
            self.denial_wave=None;return
        if not denied:return
        w=self.denial_wave or dict(rounds=0,denials=0,started=self.clock(),started_at=self.now().isoformat())
        w['rounds']+=1;w['denials']+=denied;self.denial_wave=w
        pause=min(self.config.denial_pause*2**(w['rounds']-1),self.config.denial_pause_max) if self.config.denial_pause>0 else 0
        if pause:self.denial_hold_until=max(self.denial_hold_until,self.clock()+pause)
        self.journal.metric(bid,'DENIAL_WAVE',state='ONGOING',rounds=w['rounds'],denials=w['denials'],pause=pause,
                            started_at=w['started_at'],seconds=self.clock()-w['started'])

    def _balance_metric(self, bid, credits, source):
        values=dict(credits=credits,source=source)
        if self.config.coin_reservation:
            reserved=self._reserved();values.update(reserved=reserved,spendable=credits-reserved)
        self.journal.metric(bid,'BALANCE_READ',**values)

    def _hold(self, bid, target, reason, **values):
        """Per-auction hold, logged only when its reason (or held amount) changes."""
        key=(reason,values.get('amount'))
        if self.hold_reasons.get(target['trade_id'])==key:return
        self.hold_reasons[target['trade_id']]=key
        self.journal.metric(bid,'HOLD',target=target,reason=reason,**values)

    def _closed(self, bid, member, row, outcome):
        """One record per auction outcome: final price against our cap and bids."""
        trade=member['target']['trade_id']
        bids=[(json.loads(b)['params']['amount'],s) for b,s in self.store.db.execute(
            "SELECT body,state FROM c4_attempts WHERE json_extract(body,'$.params.target.trade_id')=?",(trade,))]
        accepted=[a for a,s in bids if s=='ACKNOWLEDGED']
        self.journal.metric(bid,'AUCTION_CLOSED',target=member['target'],outcome=outcome,cap=member.get('cap'),
            final_price=row.get('current_bid'),above_cap=(row.get('current_bid') or 0)>(member.get('cap') or 0),
            our_last_bid=max(accepted) if accepted else None,bids=len(bids),
            unconfirmed=sum(1 for _,s in bids if s=='UNKNOWN'),
            credit_held=self.hold_reasons.get(trade,(None,))[0]=='NOT_ENOUGH_CREDIT')
        self.hold_reasons.pop(trade,None)

    def _overrun_check(self, bid, step, elapsed):
        """Interleave safety: a step taken in a quiet window must finish before the
        soonest live auction ends; otherwise that auction went unwatched."""
        soonest=self._soonest_end()
        self.journal.metric(bid,'INTERLEAVE_STEP',step=step,elapsed=elapsed,soonest_end_after=soonest)
        if soonest is not None and soonest<0:
            self.journal.metric(bid,'INTERLEAVE_OVERRUN',step=step,elapsed=elapsed,soonest_end_after=soonest)

    def _reserved(self, *, detail=False):
        """Coins live tracked auctions may still claim: cap minus our standing top bid
        (EA already deducted that from the free balance); an outbid auction may claim
        its whole cap again. Won (PENDING_WIN) auctions are paid; unmapped and
        untracked auctions are never rebid, so they claim nothing further."""
        total=0;claims=[]
        for m in self.journal.members():
            if m['state']!='ACTIVE' or m['target']['trade_id'] in self.unmapped:continue
            if self._is_priced_out(m):continue
            row=(m.get('proof') or {}).get('row') or {}
            top=(row.get('current_bid') or 0) if row.get('bid_state')=='highest' else 0
            claim=max(0,m['cap']-top);total+=claim
            claims.append([m['target']['trade_id'],m['cap'],top,claim])
        return (total,claims) if detail else total

    def _fitting_band(self, spendable, *, peek=False):
        """Next band in rotation whose cheapest recently seen cap fits; None if none."""
        n=len(self.config.bands)
        if spendable is None or spendable<=0:return None
        for k in range(n):
            band=self.config.bands[(self.band_index+k)%n]
            floor=self.band_floor.get(tuple(band))
            if floor and self.clock()-floor[1]<=900 and spendable<floor[0]:
                if not peek:self.journal.metric(self.journal.state()['batch_id'],'BAND_SKIPPED',band=list(band),
                                                cheapest_cap=floor[0],spendable=spendable)
                continue
            if not peek:self.band_index+=k+1
            return band
        return None

    def _orphans(self, bid, watched):
        """Watch-list participations the controller does not track (diagnostic)."""
        known={r[0] for r in self.store.db.execute('SELECT trade_id FROM c4_members')}
        orphans=[r['trade_id'] for r in watched['result']['auctions'] if r['trade_state']=='active'
                 and r['bid_state'] in {'highest','outbid'} and r['trade_id'] not in known]
        if orphans:self.journal.metric(bid,'ORPHAN_PARTICIPATION',count=len(orphans),trades=orphans[:10])

    def _mark_priced_out(self, bid, member, row, amount):
        trade=member['target']['trade_id']
        if trade in self.priced_out:return
        self.priced_out.add(trade)
        self.journal.metric(bid,'PRICED_OUT',target=member['target'],cap=member['cap'],
                            current_bid=row.get('current_bid'),next_bid=amount)

    def _is_priced_out(self, m):
        """Outbid beyond our cap (also after a restart, from the last status row)."""
        if m['target']['trade_id'] in self.priced_out:return True
        row=(m.get('proof') or {}).get('row') or {}
        return (m['state']=='ACTIVE' and row.get('bid_state')=='outbid' and
                type(row.get('current_bid')) is int and row['current_bid']>=m['cap'])

    def _soonest_end(self):
        """Seconds until the soonest live tracked auction we can still act on ends
        (None if none). Auctions priced out of our cap do not count."""
        ends=[]
        for m in self.journal.members():
            if not self._needs_status(m) or self._is_priced_out(m):continue
            proof=m.get('proof') or {};row=proof.get('row') or {}
            if proof.get('at') and row.get('expires') is not None:
                ends.append((stamp(proof['at'])+timedelta(seconds=row['expires'])-self.now()).total_seconds())
            else:ends.append(0.)
        return min(ends) if ends else None

    def _maintenance_due(self):
        if any(m['state']=='PENDING_WIN' and not self._needs_status(m) for m in self.journal.members()):return True
        return self.last_maintenance is None or self.clock()-self.last_maintenance>=self.config.maintenance_interval

    def _acquisition_blocked(self):
        """Interleave hand-off check: the acquisition hold that would apply now, or None."""
        now=self.clock()
        if now<self.search_hold_until:return 'SEARCH_THROTTLED'
        if now<self.denial_hold_until:return 'DENIAL_BURST'
        if self.config.search_budget and self.searches_last_hour()>=self.config.search_budget:return 'SEARCH_BUDGET'
        if self.config.low_credit_hold and self.credit_view is not None and self.credit_view[0]<=self.config.entry_threshold:
            credits=self._credits()
            if credits is None or credits<=self.config.entry_threshold:return 'LOW_CREDITS'
        if self.config.coin_reservation and self.coins_short:
            credits=self._credits()
            if credits is None or self._fitting_band(credits-self._reserved(),peek=True) is None:return 'COINS_RESERVED'
            self.coins_short=False
        return None

    def _window_closed(self):
        """Interleave: acquisition waits (managing resumes) unless the soonest live
        auction ends more than interleave_window seconds from now."""
        if not self.config.interleave:return False
        soonest=self._soonest_end()
        if soonest is None or soonest>self.config.interleave_window:return False
        self.journal.checkpoint(phase='MANAGING');return True

    def searches_last_hour(self):
        now=self.adapter.executor.clock()
        return sum(1 for m in self.adapter.executor.metrics if m['operation']=='search' and now-m['started']<=3600)

    def _acquisition_hold(self):
        """True while acquisition waits on the search throttle, a 461 burst or
        the hourly search budget. Members keep being managed meanwhile."""
        j=self.journal;bid=j.state()['batch_id'];now=self.clock()
        reasons=[]
        if now<self.search_hold_until:reasons.append(('SEARCH_THROTTLED',self.search_hold_until-now))
        if now<self.denial_hold_until:reasons.append(('DENIAL_BURST',self.denial_hold_until-now))
        if self.config.search_budget and self.searches_last_hour()>=self.config.search_budget:reasons.append(('SEARCH_BUDGET',60.))
        if (not reasons and self.config.low_credit_hold and self.credit_view is not None and
                self.credit_view[0]<=self.config.entry_threshold):
            credits=self._credits()
            if credits is not None and credits<=self.config.entry_threshold:reasons.append(('LOW_CREDITS',30.))
        if not reasons and self.config.coin_reservation and self.coins_short:
            credits=self._credits()
            if credits is not None and self._fitting_band(credits-self._reserved(),peek=True) is None:
                reasons.append(('COINS_RESERVED',30.))
            elif credits is not None:self.coins_short=False
        if not reasons:return False
        reason,remaining=max(reasons,key=lambda r:r[1])
        if any(self._needs_status(m) for m in j.members()):
            if self.last_hold_handoff!=reason:
                self.last_hold_handoff=reason
                j.metric(bid,'ACQUISITION_HOLD',reason=reason,remaining=remaining,managing=True)
            j.checkpoint(phase='MANAGING');return True
        self.last_hold_handoff=None
        if reason in {'LOW_CREDITS','COINS_RESERVED'} and (self.low_credit_maintenance is None or self.clock()-self.low_credit_maintenance>=300):
            # Coins come back only through sales: keep relisting expired listings
            # and clearing sold ones while acquisition waits.
            self.low_credit_maintenance=self.clock()
            j.checkpoint(phase='MAINTENANCE');return True
        j.metric(bid,'ACQUISITION_HOLD',reason=reason,remaining=remaining)
        end=self.clock()+min(remaining,30)
        while self.clock()<end:
            self.store.require_supervision();self.sleep(min(1,max(0,end-self.clock())))
        try:
            balance=self.adapter.read(self.ids(),'balance')
            if balance['success']:
                self.credit_view=(balance['credits'],self.clock())
                self._balance_metric(bid,balance['credits'],'HOLD')
            else:j.metric(bid,'ACQUISITION_HOLD_READ_FAILED',error=balance.get('error'))
        except Exception as error:j.metric(bid,'ACQUISITION_HOLD_READ_FAILED',error=error_code(error))
        return True

    def _gap_wait(self):
        """True while bids are held after a maintenance write.

        Waits at most 30s per step in one-second supervised slices, then one
        balance read keeps native freshness. Reads never write or bid.
        """
        remaining=self.gap_remaining()
        if remaining<=0:return False
        bid=self.journal.state()['batch_id']
        self.journal.metric(bid,'MAINTENANCE_GAP',remaining=remaining,gap=self.config.maintenance_gap)
        end=self.clock()+min(remaining,30)
        while self.clock()<end:
            self.store.require_supervision();self.sleep(min(1,max(0,end-self.clock())))
        try:self.adapter.read(self.ids(),'balance')
        except Exception:self.journal.metric(bid,'MAINTENANCE_GAP_READ_FAILED')
        return True

    def gap_remaining(self):
        if self.config.maintenance_gap<=0:return 0
        row=self.store.db.execute("SELECT max(coalesce(completed_at,dispatched_at)) FROM c4_work WHERE dispatched_at IS NOT NULL").fetchone()
        if not row or not row[0]:return 0
        return max(0.,self.config.maintenance_gap-(self.now()-stamp(row[0])).total_seconds())

    def _maintain(self):
        """One maintenance pass: each check writes only when it has work."""
        j=self.journal;bid=j.state()['batch_id']
        self.last_maintenance=start=self.clock()
        interleaved=self.config.interleave and any(self._needs_status(m) for m in j.members())
        mark=self.store.db.execute('SELECT coalesce(max(rowid),0) FROM c4_work').fetchone()[0]
        wins=sum(1 for m in j.members() if m['state']=='PENDING_WIN')
        error=None
        try:
            self.work.recover_bulk()
            # A verified win is moved, then listed, within the same pass.
            for _ in range(2):
                if not any(m['state']=='PENDING_WIN' for m in j.members()):break
                self._wins()
            self.work.maintenance(scan=True)
            self.work.lost_at_capacity()
        except Exception as e:
            error=error_code(e)
            j.metric(bid,'MAINTENANCE_UNKNOWN',reason='MAINTENANCE_PASS_INCOMPLETE',error=error)
        finally:
            writes=[dict(op=json.loads(a)[1],state=s) for a,s in self.store.db.execute(
                'SELECT action,state FROM c4_work WHERE rowid>?',(mark,))]
            j.metric(bid,'MAINTENANCE_PASS',elapsed=self.clock()-start,interleaved=interleaved,wins_before=wins,
                     wins_after=sum(1 for m in j.members() if m['state']=='PENDING_WIN'),writes=writes,error=error)
            if interleaved:self._overrun_check(bid,'MAINTENANCE',self.clock()-start)
            if j.state()['lifecycle']=='RUNNING' and j.state()['phase']=='MAINTENANCE':
                j.checkpoint(phase='ACQUIRING',batch_id=bid)

    def _needs_status(self, m):
        """Active auctions, and wins whose terminal proof is not yet complete."""
        if m['target']['trade_id'] in self.unmapped:return False
        if m['state']=='ACTIVE':return True
        if m['state']!='PENDING_WIN' or self.work.moved(m):return False
        row=(m.get('proof') or {}).get('row') or {}
        return not (row.get('expires',1)<=0 and row.get('native_is_won') is True)

    def _remap(self, members):
        """After a restart, map members from one fresh watch-list read.

        Members absent from it cannot be status-read in this runtime (the page
        has no native DTO for them); they are excluded until a later re-map
        finds them again. Returns False while the read itself is unavailable.
        """
        j=self.journal;bid=members[0]['batch_id']
        try:refreshed=self._read('watched')
        except Exception:
            j.metric(bid,'MAPPING_RECOVERY_PENDING');return False
        if refreshed.get('result',{}).get('success') is not True:
            j.metric(bid,'MAPPING_RECOVERY_PENDING');return False
        self.mapping_refresh_needed=False
        present={r['trade_id'] for r in refreshed['result']['auctions']}
        self.unmapped-=present
        for m in members:
            trade=m['target']['trade_id']
            if trade not in present and trade not in self.unmapped and not self.work.moved(m):
                self.unmapped.add(trade)
                j.metric(m['batch_id'],'MAPPING_LOST',target=m['target'],state=m['state'])
        return True

    def _manage(self):
        j=self.journal;members=j.members()
        if members and self.mapping_refresh_needed and not self._remap(members):return
        if not any(self._needs_status(m) for m in members):
            # Won items and every other account write belong to MAINTENANCE.
            j.checkpoint(phase='MAINTENANCE');return
        if self.last_cycle is not None:
            delay=self.last_cycle+self.config.cycle_target-self.clock()
            if delay>0:self.sleep(delay)
        start=self.clock();self.last_cycle=start;bid=members[0]['batch_id']
        # A claimed auction can disappear from watched/status. Its independently
        # confirmed move retains terminal/paid provenance; listing still requires
        # a new exact physical inventory and current caps in this runtime.
        active=[m for m in members if m['state']!='PENDING_WIN' or not self.work.moved(m)]
        try:
            active=[m for m in active if m['target']['trade_id'] not in self.unmapped]
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
                    else:self._hold(bid,m['target'],'HIGHEST_OR_NOT_ACTIONABLE',bid_state=row['bid_state'],trade_state=row['trade_state'])
                submitted=[]
                for _,m,row in sorted(actions,key=lambda a:(a[0],a[1]['target']['trade_id'])):
                    # Members can come from different batches once an unresolved
                    # win or unmapped auction outlives its batch; each keeps its own.
                    result=self._bid(m['batch_id'],m,status['command_id'],row,'rebid')
                    if result:submitted.append(result)
                    elif self.credit_held_now!=m['target']['trade_id']:
                        self._hold(bid,m['target'],'CAP_OR_LOCAL_AUTHORITY',current_bid=row['current_bid'],cap=m['cap'])
                if submitted:
                    readback=self._status([m['target'] for m,_,_ in submitted],bid)
                    if readback:self._apply(readback,{m['target']['trade_id']:m for m,_,_ in submitted},bid,
                        after={m['target']['trade_id']:at for m,_,at in submitted})
                    for m,cid,_ in submitted:
                        if not readback or m['target'] in readback['missing']:j.abandon(cid)
                if self.config.interleave:
                    soonest=self._soonest_end()
                    # Only a rebid actually sent is a live bidding war. An auction
                    # outbid beyond our cap cannot be rebid and must not block.
                    if submitted:wait='REBID_CYCLE'
                    elif soonest is None:wait=None
                    elif soonest>self.config.maintenance_window and self._maintenance_due():
                        self.last_interleave_wait=None
                        j.metric(bid,'INTERLEAVE',step='MAINTENANCE',soonest_end=soonest)
                        j.checkpoint(phase='MAINTENANCE');return
                    elif soonest<=self.config.interleave_window:wait='WINDOW'
                    else:
                        blocked=self._acquisition_blocked()
                        if blocked is None:
                            self.last_interleave_wait=None
                            j.metric(bid,'INTERLEAVE',step='ACQUIRING',soonest_end=soonest)
                            j.checkpoint(phase='ACQUIRING');return
                        wait='ACQUISITION_HELD:'+blocked
                    if wait and wait!=self.last_interleave_wait:
                        j.metric(bid,'INTERLEAVE_WAIT',reason=wait,soonest_end=soonest)
                    self.last_interleave_wait=wait
            if not j.members():j.update_batch(bid,state='SETTLED')
            if not any(self._needs_status(m) for m in j.members()):j.checkpoint(phase='MAINTENANCE')
        finally:
            elapsed=self.clock()-start
            j.metric(bid,'CYCLE',elapsed=elapsed,target=self.config.cycle_target,
                     missed_targets=max(0,math.ceil(elapsed/self.config.cycle_target)-1))

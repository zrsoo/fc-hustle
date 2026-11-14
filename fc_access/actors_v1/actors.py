"""Finite cycles and explicit independent process loops. No import-time work."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import time

from fc_access.bidding_v1.contracts import Balance, Coverage, Snapshot, State
from fc_access.bidding_v1.core import AuctionQueue, decide
from fc_access.production_v1.contracts import Search, parse_response, stamp
from fc_access.production_v1.foundation import Foundation, freshness, status_from
from fc_access.production_v1.prices import CardKey
from fc_access.production_v1.pricing import Quote
from .config import Config
from .locking import process_lock
from .occupancy import read as read_occupancy
from .enrollment import check as check_capacity


def connect(executor):
    r = executor.mailbox.runtime()
    return Foundation(executor, context=r['context'], owner=r['fences']['owner'], join_epoch=r['fences']['epoch'],
        journal_path=r['journal'], cache_path=r['cache'], reserve=r['config']['min_available_coins'], fixture=r['source']=='fixture')


class Actor:
    role = None

    def __init__(self, foundation, config=None, *, clock=time.monotonic, sleep=time.sleep):
        self.f = foundation
        self.config = config or Config()
        self.clock, self.sleep = clock, sleep

    def reload(self):
        f = self.f
        f.registry.check()
        f.queue = AuctionQueue(journal=f.journal, scope=f.registry.scope,
            reserve=self.config.min_available_coins, capacity=self.config.max_enrolled_auctions,
            pipeline_capacity=self.config.max_total_pipeline_slots)

    def record(self, reason, *, trade=None, **values):
        # Callers provide enumerated reasons and known typed values only.
        self.f.registry._append(dict(kind='ACTOR', actor=self.role, reason=reason,
            epoch=self.f.registry.epoch, **values), trade)

    def decision(self, status, action, reason, *, quote=None, cap=None, amount=None):
        return self.f.registry.decision(status, action, reason, quote=quote, cap=cap, amount=amount)

    def policy(self, trade):
        rows = [e for e in self.f.registry.events(trade) if e['kind']=='ENROLLMENT']
        return deepcopy(rows[0]) if rows else None

    def pending(self):
        return self.f.registry.current()['unresolved']

    def run(self, *, cycles=None, stop=lambda: False):
        interval = self.config.search_interval_seconds if self.role=='acquirer' else self.config.target_check_interval_seconds
        with process_lock(self.f.journal_path.with_suffix('.'+self.role+'.lock')):
            # Restart preserves the previous cycle's cadence; no catch-up burst.
            previous = [e for e in self.f.registry.events() if e['kind']=='ACTOR' and
                e.get('actor')==self.role and e['reason']=='CYCLE_STARTED']
            delay = max(0, interval-(self.f.now()-stamp(previous[-1]['at'])).total_seconds()) if previous else 0
            due = self.clock()+delay
            count = 0
            while not stop() and (cycles is None or count < cycles):
                if self.clock() < due:
                    self.sleep(min(.25, due-self.clock())); continue
                start = self.clock()
                self.record('CYCLE_STARTED')
                try:
                    self.cycle()
                except Exception:
                    self.record('CYCLE_BLOCKED')
                    raise  # Fail closed; supervisor/operator may inspect and resume.
                elapsed = self.clock()-start
                self.record('CYCLE_FINISHED', elapsed_seconds=elapsed, missed_target=elapsed>interval)
                due = max(start+interval, self.clock()+(.001 if elapsed>=interval else 0))
                count += 1


class Acquirer(Actor):
    role = 'acquirer'

    def discover(self):
        f, config = self.f, self.config
        found, poisoned, items = {}, set(), {}
        for page in range(1, config.discovery_max_pages+1):
            params = Search.discovery(page=page, max_bid=config.max_search_bid, min_buy=config.min_search_buy_now).params()
            response = f.read('search', params)
            rows = response['result']['auctions']
            for row in rows:
                trade, item = row['trade_id'], row['item']['item_id']
                if trade in found:
                    old = found[trade][0]
                    if old != row: poisoned.add(trade)
                else: found[trade] = (row, response, page)
                if item in items and items[item] != trade: poisoned.update((trade, items[item]))
                items[item] = trade
            if response['coverage']['has_more'] is False or len(rows)<21: break
        # Native wire macr/maxBid means current bid, using starting bid if unbid;
        # native minb/minBuy means BIN floor. Check returned values too, never
        # confuse either with the independent profitability cap.
        valid = []
        for trade, (row, response, page) in found.items():
            if trade in poisoned:
                self.record('DUPLICATE_CONFLICT', trade=trade); continue
            if not self.matches(row):
                self.record('FILTER_OR_AVAILABILITY_REJECTED', trade=trade); continue
            valid.append((row, response, page))
        return sorted(valid, key=lambda v:(v[0]['expires'], v[0]['trade_id']))

    def matches(self, row):
        return (row['trade_state']=='active' and row['bid_state'] in {'none','outbid'} and
            row['native_is_won'] is not True and row['item']['untradeable'] is False and row['expires']>0 and
            0<(row['current_bid'] or row['starting_bid'])<=self.config.max_search_bid and
            row['buy_now_price']>=self.config.min_search_buy_now)

    def cycle(self):
        self.reload()
        funds = self.f.read('balance')
        balance = Balance(funds['result']['credits'], None, freshness(funds))
        self.f.registry.credits(balance)
        coin_reason = self.f.queue.reserve_check(balance, now=self.f.now(), new_cycle=True)
        occupancy = read_occupancy(self.f, limit=self.config.max_transfer_list_occupied)
        capacity_reason = check_capacity(self, occupancy)
        if coin_reason:
            self.record(coin_reason, action='HOLD', capacity_reason=capacity_reason); return
        if self.pending(): self.record('RECONCILIATION_REQUIRED'); return
        if capacity_reason:
            self.record(capacity_reason, action='HOLD', occupancy=occupancy); return
        for candidate, discovery, page in self.discover():
            trade = candidate['trade_id']
            if trade in self.f.queue.entries or self.policy(trade):
                self.record('DUPLICATE_SUPPRESSED', trade=trade); continue
            prices = self.f.prices.load(key=CardKey(candidate['item']['definition_id']))
            quote = self.f.pricing.quote(candidate, prices, X=self.config.min_profit_coins)
            if quote.status != 'COMPLETE':
                self.decision(status_from(candidate, discovery), 'REJECT', 'QUOTE_REJECTED', quote=quote); continue
            # No lock over pricing; each helper/search yields to urgent native work.
            with process_lock(self.f.journal_path.with_suffix('.bid.lock'),wait_seconds=35):
                self.reload()
                if trade in self.f.queue.entries or self.policy(trade) or self.pending():
                    self.record('DUPLICATE_OR_PENDING', trade=trade); continue
                params = Search.discovery(candidate['item']['definition_id'], page=page,
                    max_bid=self.config.max_search_bid, min_buy=self.config.min_search_buy_now).params()
                fresh = self.f.read('search', params)
                rows = [r for r in fresh['result']['auctions'] if r['trade_id']==trade and
                    (r['item']['item_id'],r['item']['definition_id'])==
                    (candidate['item']['item_id'],candidate['item']['definition_id'])]
                if len(rows)!=1 or not self.matches(rows[0]):
                    self.record('STALE_CANDIDATE', trade=trade); continue
                status = status_from(rows[0], fresh)
                funds = self.f.read('balance')
                balance = Balance(funds['result']['credits'], None, freshness(funds))
                self.f.registry.credits(balance)
                d = decide(status, balance, prices, quote.max_affordable_bid, now=self.f.now())
                # Reserve policy takes precedence even when the same observation
                # also blocks capacity. Existing Bidder work never uses this gate.
                coin_reason = self.f.queue.reserve_check(balance, now=self.f.now(), amount=d.amount or 0)
                occupancy = read_occupancy(self.f, limit=self.config.max_transfer_list_occupied)
                capacity_reason = check_capacity(self, occupancy)
                if coin_reason:
                    self.decision(status, 'HOLD', coin_reason, quote=quote, cap=quote.max_affordable_bid); return
                if d.amount is None:
                    self.decision(status, 'HOLD', d.reason, quote=quote, cap=quote.max_affordable_bid); continue
                self.record(occupancy['reason'], trade=trade, occupancy=occupancy,
                    action='CONTINUE' if occupancy['enrollment_allowed'] else 'HOLD')
                if capacity_reason:
                    self.decision(status, 'HOLD', capacity_reason, quote=quote, cap=quote.max_affordable_bid)
                    return
                reason = self.f.queue.admit(status, balance, d.amount, now=self.f.now())
                if reason!='ENROLLED':
                    self.decision(status, 'HOLD', reason, quote=quote, cap=quote.max_affordable_bid); continue
                self.f.registry._append(dict(kind='ENROLLMENT', identity=asdict(status.identity),
                    quote=asdict(quote), epoch=self.f.registry.epoch), trade)
                self.f.admissions[trade] = (status,balance,prices,quote,d.amount)
                self.decision(status, 'BID', 'ELIGIBLE', quote=quote, cap=quote.max_affordable_bid, amount=d.amount)
                self.f.bid(trade)
            # ACK/unknown waits for Bidder's independent readback before any new write.
            break


class Bidder(Actor):
    role = 'bidder'

    def cycle(self):
        self.reload()
        f = self.f
        if not f.queue.entries and not self.pending():
            from fc_access.production_v1.resale import Resale
            Resale(f).cycle()
            self.record('IDLE'); return
        watched, funds = f.read('watched'), f.read('balance')
        balance = Balance(funds['result']['credits'], None, freshness(funds))
        f.registry.credits(balance)
        groups = {r['trade_id']:r for r in watched['result']['auctions']}
        for trade in list(f.queue.entries):
            if not freshness(watched).fresh(f.now()) or not balance.freshness.fresh(f.now()):
                self.record('STALE_STATUS',trade=trade);continue
            row = groups.get(trade)
            if row is None or status_from(row, watched).identity != f.queue.identities[trade]:
                self.record('MISSING_OR_STALE_IDENTITY', trade=trade); continue
            status = status_from(row, watched)
            if status.state==State.PENDING:
                if not (row['trade_state']=='closed' and row['expires']<=0 and row['bid_state']=='highest'):
                    self.decision(status,'HOLD','PENDING');continue
                owned = f.read('unassigned')
                if not status.freshness.fresh(f.now()) or not balance.freshness.fresh(f.now()):
                    self.record('STALE_STATUS',trade=trade);continue
                from fc_access.production_v1.resale import verify_win
                try:
                    status = verify_win(f, status, watched, owned)
                except ValueError:
                    self.decision(status,'HOLD','PENDING'); continue
                self.record('OWNED_WIN_VERIFIED', trade=trade, paid=status.paid,
                    identity=asdict(status.identity), owned_read_id=owned['command_id'], win_read_id=watched['command_id'])
            pending = [p for p in self.pending() if p['trade_id']==trade]
            for p in pending:
                try:
                    f.journal.reconcile(p['command_id'], scope=f.registry.scope, owner=f.registry.owner, epoch=f.registry.epoch,
                        status=status, balance=balance)
                except ValueError:
                    self.record('OUTCOME_STILL_UNKNOWN', trade=trade)
            f.queue.refresh(Snapshot((status,),freshness(watched),Coverage(False,None)), now=f.now(),reset_draining=False)
            policy = self.policy(trade)
            cap = policy['quote']['max_affordable_bid'] if policy else None
            if status.state in {State.WON,State.LOST}:
                self.decision(status,'HOLD','SKIP',cap=cap); continue
            if status.state==State.LEADING:
                self.decision(status,'HOLD','LEADING',cap=cap); continue
            if status.state!=State.OUTBID or self.pending() or policy is None:
                self.decision(status,'UNKNOWN','UNKNOWN',cap=cap); continue
            prices = f.prices.load(key=CardKey(status.identity.definition_id))
            d = decide(status,balance,prices,cap,now=f.now())
            if d.amount is None:
                self.decision(status,'HOLD',d.reason,cap=cap); continue
            # A fresh balance already excludes EA escrow. Never add our prior bid
            # to it. Pending local writes are globally gated until reconciliation.
            with process_lock(f.journal_path.with_suffix('.bid.lock'),wait_seconds=35):
                if self.pending(): self.record('RECONCILIATION_REQUIRED',trade=trade); continue
                # Another actor may have spent coins while we waited for the
                # write lock. Obtain both snapshots again under that lock.
                fresh = f.read('watched')
                matches = [r for r in fresh['result']['auctions'] if r['trade_id']==trade]
                if len(matches)!=1:
                    self.record('MISSING_OR_STALE_IDENTITY',trade=trade);continue
                latest = status_from(matches[0],fresh)
                if latest.identity!=status.identity:
                    self.record('MISSING_OR_STALE_IDENTITY',trade=trade);continue
                if latest.state!=State.OUTBID:
                    self.decision(latest,'HOLD' if latest.state==State.LEADING else 'UNKNOWN',
                        'LEADING' if latest.state==State.LEADING else 'UNKNOWN',cap=cap);continue
                latest_funds = f.read('balance')
                balance = Balance(latest_funds['result']['credits'],None,freshness(latest_funds))
                f.registry.credits(balance)
                status = latest
                d = decide(status,balance,prices,cap,now=f.now())
                if d.amount is None:
                    self.decision(status,'HOLD',d.reason,cap=cap);continue
                quote = Quote(**policy['quote'])
                f.admissions[trade] = (status,balance,prices,quote,d.amount)
                self.decision(status,'BID','ELIGIBLE',cap=cap,amount=d.amount)
                f.bid(trade)
                break
        from fc_access.production_v1.resale import Resale
        Resale(f).cycle()

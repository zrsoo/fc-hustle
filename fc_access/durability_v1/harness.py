"""Bounded integration actions, never an actor service or retry mechanism.

An instance requires an explicit existing adapter and independent readback
functions. Default limits authorize no writes. Reservations survive crashes,
timeouts and ownership changes; exposure is gross, never assumed refunded.
"""
from dataclasses import dataclass
from datetime import datetime
import sqlite3

from fc_access.bidding_v1.contracts import Freshness, Identity, Outcome, State, instant, token, integer
from fc_access.bidding_v1.core import decide


@dataclass(frozen=True)
class OwnedProof:
    identity: Identity
    paid: int
    tradeable: bool
    freshness: Freshness


class BoundedHarness:
    def __init__(self,path,adapter,*,seconds=600,mutations=0,exposure=0,now=None):
        if type(seconds) is not int or not 1<=seconds<=900 or type(mutations) is not int or not 0<=mutations<=3:
            raise ValueError('invalid_window_limit')
        if type(exposure) is not int or not 0<=exposure<=10000:
            raise ValueError('invalid_exposure')
        self.adapter=adapter; self.now=now or adapter.now
        self.db=sqlite3.connect(path,timeout=5,isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS window(scope TEXT, deadline REAL, mutations INTEGER, exposure INTEGER, stopped INTEGER, last_at REAL);
          CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, kind TEXT, amount INTEGER, state TEXT, trade_id TEXT);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, at REAL, id TEXT, reason TEXT);
          CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;
        ''')
        t=instant(self.now()).timestamp()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT scope FROM window').fetchone()
            if row is None:
                self.db.execute('INSERT INTO window VALUES(?,?,?,?,0,?)',(adapter.scope,t+seconds,mutations,exposure,t))
            elif row!=(adapter.scope,):
                raise ValueError('scope_changed')
            if self.db.execute("SELECT 1 FROM actions WHERE state!='VERIFIED'").fetchone():
                self.db.execute('UPDATE window SET stopped=1')
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def stop(self,cid,reason='UNCERTAIN'):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('UPDATE window SET stopped=1')
            self.db.execute('INSERT INTO events(at,id,reason) VALUES(?,?,?)',(instant(self.now()).timestamp(),cid,reason))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def _owner(self):
        a=self.adapter
        a.journal._owner(a.scope,a.owner,a.epoch)

    def _reserve(self,cid,kind,amount,identity):
        token(cid); integer(amount); self._owner()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            scope,deadline,maximum,exposure,stopped,last=self.db.execute('SELECT * FROM window').fetchone()
            t=instant(self.now()).timestamp()
            count,spent=self.db.execute('SELECT COUNT(*),COALESCE(SUM(amount),0) FROM actions').fetchone()
            if stopped or not last<=t<deadline or count>=maximum or spent+amount>exposure:
                raise ValueError('window_mutation_exposure_or_time_limit')
            self.db.execute("INSERT INTO actions VALUES(?,?,?,'UNKNOWN',?)",(cid,kind,amount,identity.trade_id))
            self.db.execute('UPDATE window SET last_at=?',(t,))
            self.db.execute('INSERT INTO events(at,id,reason) VALUES(?,?,?)',(t,cid,'RESERVED_BEFORE_SEND'))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def _verified(self,cid):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("UPDATE actions SET state='VERIFIED' WHERE id=?",(cid,))
            self.db.execute('INSERT INTO events(at,id,reason) VALUES(?,?,?)',(instant(self.now()).timestamp(),cid,'INDEPENDENTLY_VERIFIED'))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def bid_once(self,intent,status,balance,rules,*,observations,readback):
        a=self.adapter
        if (intent.scope,intent.owner,intent.epoch)!=(a.scope,a.owner,a.epoch):
            raise ValueError('unowned_intent')
        if status.freshness.read_id==balance.freshness.read_id:
            raise ValueError('independent_preconditions_required')
        if decide(status,balance,rules,intent.cap,now=self.now()).amount!=intent.amount:
            raise ValueError('fresh_minimum_bid_preconditions_required')
        if not a.fixture and any(f.source!='native' for f in (status.freshness,balance.freshness)):
            raise ValueError('native_preconditions_required')
        self._reserve(intent.command_id,'bid',intent.amount,intent.identity)
        try:
            result=a.bid_once(intent,status,balance,rules,observations=observations)
            # UNKNOWN always ends this window; no automatic retry or continuation.
            if result.outcome!=Outcome.ACKNOWLEDGED:
                raise ValueError('uncertain_acknowledgment')
            self._owner()
            after,funds=readback(intent.command_id)
            if after.freshness.read_id==funds.freshness.read_id:
                raise ValueError('independent_readbacks_required')
            if not a.fixture and any(f.source!='native' for f in (after.freshness,funds.freshness)):
                raise ValueError('native_readbacks_required')
            a.reconcile(intent.command_id,after,funds)
            self._verified(intent.command_id)
            return after
        except BaseException:
            self.stop(intent.command_id)
            raise

    def won_action_once(self,cid,kind,status,proof,*,send,readback,rules=None,price=None):
        if kind not in ('transfer','list') or not isinstance(proof,OwnedProof):
            raise ValueError('invalid_won_action')
        a=self.adapter
        # Closed/highest alone is PENDING in the native adapter and cannot enter.
        if (status.state!=State.WON or status.identity!=proof.identity or status.owned_item_id!=proof.identity.item_id
            or status.paid!=proof.paid or proof.tradeable is not True or proof.freshness.read_id==status.freshness.read_id
            or not status.freshness.fresh(self.now()) or not proof.freshness.fresh(self.now())):
            raise ValueError('conclusive_owned_physical_item_required')
        integer(proof.paid,1)
        if not a.fixture and (status.freshness.source!='native' or proof.freshness.source!='native'):
            raise ValueError('native_ownership_required')
        if kind=='list':
            from fc_access.pricing import MarketKey
            prices=a.provider.validate(rules,key=MarketKey(proof.identity.definition_id,'pc'),now=self.now())
            if not a.fixture and rules.provenance.classification!='LIVE_VERIFIED':
                raise ValueError('live_listing_rules_required')
            integer(price,1)
            from fc_access.pricing import floor_price
            if price<prices.minimum or price>prices.maximum or floor_price(price,prices)!=price:
                raise ValueError('invalid_listing_price')
        self._reserve(cid,kind,0,proof.identity)
        before=instant(self.now())
        try:
            # Ownership takeover cannot interleave between the last check and
            # synchronous send. A crash leaves the separate reservation UNKNOWN.
            with a.journal.transaction():
                self._owner()
                if send() is not True: raise ValueError('uncertain_acknowledgment')
            self._owner()
            verified,fresh=readback()
            if (verified is not True or not isinstance(fresh,Freshness) or not fresh.fresh(self.now())
                or fresh.read_id in (cid,status.freshness.read_id,proof.freshness.read_id)
                or fresh.network_at<before or not a.fixture and fresh.source!='native'):
                raise ValueError('independent_action_readback_required')
            self._verified(cid)
        except BaseException:
            self.stop(cid);raise

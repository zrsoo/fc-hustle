"""One explicitly authorized finite bid-receipt experiment. No workers/jobs/retry.

Uses the actual Acquirer/Foundation pipeline; stops after its first bid and fresh
readback. An exclusive durable ledger consumes the attempt before any EA work.
Interrupted reserved operations are never replayed or given a replacement budget.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import time

from fc_access.production_v1.contracts import LOCAL_OPERATIONS, MUTATIONS, parse_response


class Attempt:
    def __init__(self,path,*,source='native'):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.value=dict(schema=1,attempt_id='bid-receipt-v1-01',source=source,status='RUNNING',
            started_at=datetime.now(timezone.utc).isoformat(),ea_limit=16,bid_limit=1,helper_limit=64,
            ea_consumed=0,ea_reserved=0,bids_consumed=0,helpers_consumed=0,operations=[])
        with self.path.open('x',encoding='utf-8') as f:
            json.dump(self.value,f);f.flush();os.fsync(f.fileno())

    def save(self):
        temp=self.path.with_suffix('.tmp')
        with temp.open('w',encoding='utf-8') as f:
            json.dump(self.value,f,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
        temp.replace(self.path)

    def stop(self,status,reason):
        self.value.update(status=status,reason=reason,finished_at=datetime.now(timezone.utc).isoformat())
        self.save()


class BoundedExecutor:
    def __init__(self,executor,attempt,*,now=lambda:datetime.now(timezone.utc)):
        self.executor,self.attempt,self.now=executor,attempt,now
    def ownership_epoch(self,context):return self.executor.ownership_epoch(context)
    def attach(self,*args):return self.executor.attach(*args)
    @property
    def last_sqlite_ms(self):return getattr(self.executor,'last_sqlite_ms',None)
    def execute(self,c):
        a=self.attempt;v=a.value;op=c['operation']
        if v['status']!='RUNNING':raise ValueError('attempt_stopped_no_retry')
        if v['ea_reserved']:raise ValueError('interrupted_operation_no_replay')
        if any(row['command']['id']==c['id'] for row in v['operations']):raise ValueError('duplicate_operation_no_replay')
        if op in MUTATIONS and op!='bid':raise ValueError('only_one_bid_authorized')
        reserve=0 if op in LOCAL_OPERATIONS else 2 if op=='search' else 1
        if v['ea_consumed']+reserve>v['ea_limit']:raise ValueError('ea_budget_exhausted')
        if op=='bid' and v['bids_consumed']>=v['bid_limit']:raise ValueError('bid_budget_exhausted')
        if op in LOCAL_OPERATIONS and v['helpers_consumed']>=v['helper_limit']:raise ValueError('helper_budget_exhausted')
        v['ea_reserved']=reserve
        if op=='bid':v['bids_consumed']+=1
        if op in LOCAL_OPERATIONS:v['helpers_consumed']+=1
        row=dict(command=c,state='CLAIMED_NO_REPLAY',reserved=reserve)
        v['operations'].append(row);a.save() # Before native delivery, including bid.
        started=time.monotonic()
        try:
            result=parse_response(self.executor.execute(c),c,now=self.now(),source=v['source'],require_bid_receipt=True,
                pricing_rows=op=='search' and c['params']['purpose']=='pricing')
            count=result['freshness']['request_count']
            row.update(state='RETURNED',response=result,elapsed_seconds=time.monotonic()-started)
            v['ea_consumed']+=count;v['ea_reserved']=0
            if count>reserve:raise ValueError('unexpected_native_fanout')
            return result
        except Exception as error:
            from fc_access.production_v1.diagnostics import safe_reason
            row['failure']=safe_reason(error)
            a.stop('FAILURE/BLOCKED','unexpected_native_fanout' if type(error) is ValueError and str(error)=='unexpected_native_fanout' else 'native_delivery_or_contract_failure')
            raise
        finally:
            row['elapsed_seconds']=time.monotonic()-started;a.save()


def verify(f,attempt):
    from fc_access.actors_v1.actors import Acquirer
    from fc_access.bidding_v1.contracts import Balance,State
    from fc_access.production_v1.foundation import freshness
    from fc_access.production_v1.known_status import observe
    if f.registry.current()['unresolved'] or f.queue.entries:
        raise ValueError('prior_commitments_must_be_resolved')
    Acquirer(f).cycle() # Standard filters, all admission checks; one opening bid.
    commands=f.journal.db.execute('SELECT id,trade_id,state FROM commands WHERE scope=? ORDER BY rowid DESC',
                                 (f.registry.scope,)).fetchall()
    bids=[r for r in commands if any(x['command']['id']==r[0] and x['command']['operation']=='bid' for x in attempt.value['operations'])]
    if len(bids)!=1:raise ValueError('no_unique_eligible_bid_dispatched')
    cid,trade,state=bids[0]
    watched=f.read('watched');funds=f.read('balance')
    status,source,row=observe(f,f.queue.identities[trade],watched)
    balance=Balance(funds['result']['credits'],None,freshness(funds))
    attempt.value['readback']=dict(command_id=cid,status_read_id=source['command_id'],balance_read_id=funds['command_id'],
        identity=vars(status.identity),state=status.state.value,current_bid=status.current_bid,
        bid_state=row['bid_state'],spendable=balance.spendable)
    attempt.save()
    if state!='ACKNOWLEDGED' or status.state not in {State.LEADING,State.OUTBID}:
        raise ValueError('accepted_receipt_and_independent_participation_required')
    f.journal.reconcile(cid,scope=f.registry.scope,owner=f.registry.owner,epoch=f.registry.epoch,status=status,balance=balance)
    attempt.value['reconciled']=True
    attempt.stop('PASS' if attempt.value['source']=='native' else 'OFFLINE_PASS','accepted_receipt_and_fresh_account_readback')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context',required=True);p.add_argument('--journal',required=True)
    p.add_argument('--checkpoint',required=True);p.add_argument('--execute-authorized',action='store_true')
    args=p.parse_args()
    if not args.execute_authorized:p.error('--execute-authorized required; one new attempt only')
    from fc_access.production_v1.contracts import context
    from fc_access.production_v1.executor import EdgeExecutor
    from fc_access.production_v1.foundation import Foundation
    from fc_access.production_v1.gate_00203 import desktop_preflight
    from fc_access.actors_v1.locking import process_lock
    from fc_access.continuous_v1.runtime import account_locks,DEFAULT_STATE,ROOT,require_service
    value=context(json.loads(Path(args.context).read_text(encoding='utf-8')))
    journal=Path(args.journal).resolve()
    if not journal.is_file():raise ValueError('existing_journal_required')
    with ExitStack() as stack:
        for lock in [*account_locks(value),DEFAULT_STATE/'supervisor.lock',
            ROOT/'private-captures/production-v1/actors-executor-8784.lock',
            journal.with_suffix('.continuous.owner.lock'),journal.with_suffix('.continuous.executor.lock'),
            DEFAULT_STATE/'native.executor.lock',DEFAULT_STATE/'native.sqlite3.executor.lock']:
            stack.enter_context(process_lock(lock))
        desktop=desktop_preflight();attempt=Attempt(args.checkpoint)
        attempt.value['desktop']=desktop;attempt.save()
        f=None
        try:
            edge=EdgeExecutor();bounded=BoundedExecutor(edge,attempt)
            f=Foundation(bounded,context=value,journal_path=journal,interval=2)
            require_service(edge.request('/health'),value,f.adapter.fences,journal)
            verify(f,attempt)
        except Exception as e:
            # Enumerated local reasons only; never arbitrary native error text.
            safe={'prior_commitments_must_be_resolved','no_unique_eligible_bid_dispatched',
                  'accepted_receipt_and_independent_participation_required','ea_budget_exhausted',
                  'bid_budget_exhausted','helper_budget_exhausted','unexpected_native_fanout'}
            if attempt.value['status']=='RUNNING':
                attempt.stop('FAILURE/BLOCKED',str(e) if type(e) is ValueError and str(e) in safe else type(e).__name__)
        finally:
            if f:f.close()
        print(json.dumps({k:attempt.value[k] for k in ('attempt_id','status','reason','ea_consumed','ea_reserved','bids_consumed')}))
        return 0 if attempt.value['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())

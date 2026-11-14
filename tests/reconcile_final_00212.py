"""One explicit read-only EA reconciliation; never redispatches a mutation."""
import argparse
import json
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.final_run import Evidence
from fc_access.production_v1.executor import EdgeExecutor
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.foundation import status_from,freshness
from fc_access.production_v1.resale import verify_win,Resale,pending as pending_resale
from fc_access.production_v1.bulk import BulkTransfer,pending as pending_bulk
from fc_access.bidding_v1.contracts import Balance,State,Snapshot,Coverage
from dataclasses import asdict


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',required=True)
    p.add_argument('--predecessor',default='docs/research/002/002-12/remediation-01/live-02');args=p.parse_args()
    e=Evidence(args.evidence);f=None;ok=False
    try:
        executor=EdgeExecutor();health=executor.request('/health')
        e.append('READ_ONLY_RECONCILIATION_OPENED',context=health['owner']['context'],
            native_mutations=0,predecessor=args.predecessor)
        f=Foundation(executor,context=health['owner']['context'],
            journal_path=ROOT/'private-captures/final-remediation/foundation.sqlite3',
            cache_path=ROOT/'private-captures/final-remediation/completed-quotes.sqlite3',interval=2)
        def read(op,params=None):
            from fc_access.production_v1.contracts import MUTATIONS
            if op in MUTATIONS:raise ValueError('read_only_reconciliation')
            cid=secrets.token_hex(16);c=f.adapter.envelope(cid,op,params or {})
            e.append('READ_INTENT',command=c)
            v=f.adapter.read(cid,op,params or {});e.append('NATIVE_READ',command=c,response=v);return v
        pending=f.registry.current()['unresolved']
        e.append('PENDING_BEFORE',intents=pending)
        watched,funds=read('watched'),read('balance')
        balance=Balance(funds['result']['credits'],None,freshness(funds));f.registry.credits(balance)
        for row in watched['result']['auctions']:
            trade=row['trade_id']
            if trade not in f.queue.entries:continue
            status=status_from(row,watched);owned=None
            if status.state==State.PENDING and row['native_is_won'] is True:
                owned=read('unassigned')
                if not owned['result']['items']:
                    owned=read('owned_item',dict(trade_id=trade,item_id=row['item']['item_id'],definition_id=row['item']['definition_id']))
                try:
                    status=verify_win(f,status,watched,owned)
                    f.registry._append(dict(kind='ACTOR',actor='reconciliation',reason='OWNED_WIN_VERIFIED',
                        epoch=f.registry.epoch,paid=status.paid,identity=asdict(status.identity),
                        owned_read_id=owned['command_id'],win_read_id=watched['command_id']),trade)
                    e.append('INDEPENDENT_WIN_PROOF',trade_id=trade,paid=status.paid,
                        identity=asdict(status.identity),owned_read_id=owned['command_id'],win_read_id=watched['command_id'])
                except ValueError:
                    e.append('OWNERSHIP_STILL_UNPROVEN',trade_id=trade)
            for intent in [i for i in pending if i['trade_id']==trade]:
                try:
                    f.journal.reconcile(intent['command_id'],scope=f.registry.scope,owner=f.registry.owner,
                        epoch=f.registry.epoch,status=status,balance=balance)
                    e.append('RECONCILED',command_id=intent['command_id'],status_read_id=watched['command_id'],
                        balance_read_id=funds['command_id'],state=status.state.value)
                except ValueError:e.append('RECONCILIATION_UNRESOLVED',command_id=intent['command_id'])
            f.queue.refresh(Snapshot((status,),freshness(watched),Coverage(False,None)),now=f.now(),reset_draining=False)
        f.read=read
        resale=Resale(f)
        for intent in pending_resale(f.journal,f.registry.scope):
            verified=resale.reconcile(intent['command_id'])
            e.append('RESALE_READBACK',command_id=intent['command_id'],operation=intent['operation'],verified=verified)
        bulk=BulkTransfer(f)
        for intent in pending_bulk(f.journal,f.registry.scope):
            verified=bulk.reconcile(intent['command_id'])
            e.append('BULK_READBACK',command_id=intent['command_id'],operation=intent['operation'],verified=verified)
        remaining=f.registry.current()['unresolved']+pending_resale(f.journal,f.registry.scope)+pending_bulk(f.journal,f.registry.scope);ok=not remaining
        e.append('PENDING_AFTER',intents=remaining)
    except (ValueError,TimeoutError):
        e.append('READ_ONLY_RECONCILIATION_STOP',reason='NATIVE_READ_OR_ATTACHMENT_FAILED')
    finally:
        if f:f.close()
        e.append('RUN_STOPPED',remaining_processes=[],verified_process_exit=True,native_mutations=0)
        e.close()
    print(json.dumps(dict(status='RECONCILED' if ok else 'UNRESOLVED',evidence=args.evidence)))
    return 0 if ok else 1


if __name__=='__main__':raise SystemExit(main())

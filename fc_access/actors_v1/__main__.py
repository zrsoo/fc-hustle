"""Operator tools and explicit entry points; help/status never start actors."""
import argparse
import json
from pathlib import Path

from .config import Config
from .operator import inspect, retain


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir',default='private-captures/actors-v1')
    sub = p.add_subparsers(dest='operation',required=True)
    config = sub.add_parser('config')
    config.add_argument('--file')
    executor = sub.add_parser('executor')
    executor.add_argument('--context',required=True)
    executor.add_argument('--config')
    executor.add_argument('--port',type=int,default=8784)
    for role in ('acquirer','bidder','maintenance'):
        actor = sub.add_parser(role)
        actor.add_argument('--cycles',type=int,help='Optional bounded number of cycles; absent means explicit sustained run')
    relist = sub.add_parser('bulk-relist', help='Explicit bounded maintenance; live launch deferred to item 12')
    relist.add_argument('--ticks', type=int, required=True)
    for view in ('status','timeline','decisions','blocked','export'):
        s = sub.add_parser(view)
        s.add_argument('--trade-id')
        s.add_argument('--since'); s.add_argument('--until')
        if view=='export': s.add_argument('--output')
    retention = sub.add_parser('retain')
    retention.add_argument('destination')
    args = p.parse_args()
    root = Path(args.state_dir).resolve()
    mailbox_path = root/'native.sqlite3'
    if args.operation=='config':
        result = Config(**json.loads(Path(args.file).read_text())).export() if args.file else (
            inspect(mailbox_path,'config') if mailbox_path.exists() else Config().export())
    elif args.operation=='retain': result = retain(mailbox_path,args.destination)
    elif args.operation=='executor':
        from .locking import process_lock
        from .native import Broker,Mailbox
        from fc_access.production_v1.foundation import Foundation
        from fc_access.production_v1.executor import EdgeExecutor
        root.mkdir(parents=True,exist_ok=True)
        # Lock before creating a session/attaching; a second executor cannot fence
        # out a running owner. All actors use this one state directory.
        transport_lock = Path(__file__).resolve().parents[2]/f'private-captures/production-v1/actors-executor-{args.port}.lock'
        with process_lock(transport_lock), process_lock(mailbox_path.with_suffix('.executor.lock')):
            config = Config(**json.loads(Path(args.config).read_text())) if args.config else Config()
            f = Foundation(EdgeExecutor(args.port),context=json.loads(Path(args.context).read_text()),
                journal_path=root/'journal.sqlite3',cache_path=root/'completed-quotes.sqlite3')
            box = Mailbox(mailbox_path)
            try: Broker(box,f,config).run(locked=True)
            finally: box.close();f.close()
        result = dict(stopped=True)
    elif args.operation=='bulk-relist':
        from .native import QueueExecutor
        from .actors import connect
        from .relist import BulkRelistScheduler
        if args.ticks < 1: p.error('--ticks must be positive')
        executor = QueueExecutor(mailbox_path,'maintenance')
        f = connect(executor)
        try:
            result = BulkRelistScheduler(f,Config(**executor.mailbox.runtime()['config'])).run(ticks=args.ticks)
        finally: f.close();executor.close()
    elif args.operation in {'acquirer','bidder','maintenance'}:
        from .native import QueueExecutor
        from .actors import Acquirer,Bidder,connect
        from .maintenance import TransferMaintenance
        if args.cycles is not None and args.cycles<1: p.error('--cycles must be positive')
        executor = QueueExecutor(mailbox_path,args.operation)
        f = connect(executor)
        try:
            config = Config(**executor.mailbox.runtime()['config'])
            {'acquirer': Acquirer, 'bidder': Bidder, 'maintenance': TransferMaintenance}[args.operation](f,config).run(cycles=args.cycles)
        finally: f.close();executor.close()
        result = dict(stopped=True,actor=args.operation)
    else:
        result = inspect(mailbox_path,args.operation,trade=args.trade_id,since=args.since,until=args.until)
        if args.operation=='export' and args.output:
            # Exclusive output avoids overwriting a prior evidence capture.
            with Path(args.output).open('x',encoding='utf8') as handle: json.dump(result,handle,indent=2)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__': main()

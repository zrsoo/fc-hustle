"""Fresh read-only reconciliation of existing commitments; never starts actors.

Each output directory is single-use. Uses the production recovery function, so
an independently proven win may require additional owned-item reads. No bid,
move, listing, bulk mutation or consumed experiment replay is permitted.
"""
from contextlib import ExitStack
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.continuous_v1.recovery import reconcile
from fc_access.continuous_v1.runtime import account_locks,DEFAULT_JOURNAL,DEFAULT_STATE
from fc_access.production_v1.executor import EdgeExecutor
from fc_access.production_v1.foundation import Foundation


def probe(output,context):
    output=Path(output);output.mkdir()
    def record(kind,**body):
        with (output/'native.jsonl').open('a',encoding='utf8') as f:
            f.write(json.dumps(dict(kind=kind,at=datetime.now(timezone.utc).isoformat(),**body))+'\n')
    edge=EdgeExecutor()
    class ReadOnly:
        def ownership_epoch(self,value):return edge.ownership_epoch(value)
        def attach(self,value,owner,epoch):return edge.attach(value,owner,epoch)
        def execute(self,command):
            if command['operation'] not in {'watched','balance','transfer_list','status','owned_item','unassigned','caps'}:
                raise ValueError('read_only_prelaunch_operation_required')
            record('READ_INTENT',command=command)
            response=edge.execute(command);record('NATIVE_READ',command=command,response=response)
            return response
    result=dict(status='STOPPED',actors_started=0,account_mutations=0)
    try:
        with ExitStack() as stack:
            for path in [*account_locks(context),DEFAULT_STATE/'supervisor.lock',
                    ROOT/'private-captures/production-v1/actors-executor-8784.lock',
                    DEFAULT_JOURNAL.with_suffix('.continuous.owner.lock'),
                    DEFAULT_JOURNAL.with_suffix('.continuous.executor.lock'),
                    DEFAULT_JOURNAL.with_suffix('.bid.lock'),DEFAULT_STATE/'native.executor.lock']:
                stack.enter_context(process_lock(path))
            h=edge.request('/health')
            if h['service']!='fc-production-v1' or h['mutations_enabled'] or not h['attached'] or h['owner']['context']!=context:
                raise ValueError('attached_read_only_service_required')
            f=Foundation(ReadOnly(),context=context,journal_path=DEFAULT_JOURNAL,interval=2);stack.callback(f.close)
            record('STARTUP_BEFORE',registry=f.registry.current())
            proof=reconcile(f);view=f.registry.current()
            if view['unresolved'] or not view['credits']['fresh'] or not view['capacity']['fresh']:
                raise ValueError('fresh_reconciliation_required')
            record('STARTUP_AFTER',registry=view,recovery=proof)
            result.update(status='PASS',epoch=f.registry.epoch,context=context,recovery=proof,
                          credits=view['credits']['available_coins'],capacity=view['capacity'])
    except Exception as error:
        result.update(error_type=type(error).__name__,reason=str(error) if type(error) is ValueError and
                      str(error).replace('_','').isalnum() else type(error).__name__)
        record('PRELAUNCH_STOPPED',**result)
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--context',required=True);args=parser.parse_args()
    result=probe(args.output,json.loads(Path(args.context).read_text()))
    print(json.dumps(result));raise SystemExit(0 if result['status']=='PASS' else 1)

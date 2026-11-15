"""Explicit finite read-only startup probe; never starts a controller or actor.

Run only after the certified local withdrawal. Three newly identified native
operations are allowed: watched, balance, and complete Transfer List, in order.
The output directory must be new. This is not a replay of a historical window.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.continuous_v1.recovery import reconcile
from fc_access.continuous_v1.runtime import DEFAULT_JOURNAL, DEFAULT_STATE, account_locks
from fc_access.continuous_v1.withdrawal import certificate, need
from fc_access.production_v1.executor import EdgeExecutor
from fc_access.production_v1.foundation import Foundation


def probe(output):
    output = Path(output)
    output.mkdir()  # Never reuse a completed or failed evidence window.
    events = output/'native.jsonl'
    def record(kind, **body):
        with events.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), kind=kind, **body),
                                    sort_keys=True, allow_nan=False)+'\n')
    gate = certificate(ROOT/'docs/research/002/002-03/attempts/20261114-adapter-repair-gate-06/gate.json')
    context = gate['context']
    class ReadOnly:
        def __init__(self):
            self.edge, self.commands, self.responses = EdgeExecutor(), [], []
        def ownership_epoch(self, value): return self.edge.ownership_epoch(value)
        def attach(self, value, owner, epoch): return self.edge.attach(value, owner, epoch)
        def execute(self, command):
            expected = ['watched','balance','transfer_list']
            need(len(self.commands) < 3 and command['operation'] == expected[len(self.commands)],
                 'bounded_read_only_probe_operations_exhausted')
            self.commands.append(command)
            record('READ_INTENT', command=command)
            result = self.edge.execute(command)
            self.responses.append(result)
            record('NATIVE_READ', command=command, response=result)
            return result
    result = dict(status='BLOCKED', mode='LIVE_READ_ONLY', actors_started=0,
                  account_mutations=0, operation_budget=3)
    native = ReadOnly()
    try:
        with ExitStack() as stack:
            for path in [*account_locks(context), DEFAULT_STATE/'supervisor.lock',
                    ROOT/'private-captures/production-v1/actors-executor-8784.lock',
                    DEFAULT_JOURNAL.with_suffix('.continuous.owner.lock'),
                    DEFAULT_JOURNAL.with_suffix('.continuous.executor.lock'),
                    DEFAULT_JOURNAL.with_suffix('.bid.lock'), DEFAULT_STATE/'native.executor.lock']:
                stack.enter_context(process_lock(path))
            health = native.edge.request('/health')
            need(health['service'] == 'fc-production-v1' and health['schema'] == 2 and
                 health['attached'] is True and health['mutations_enabled'] is False and
                 health['owner']['context'] == context, 'authenticated_read_only_service_required')
            record('SERVICE_AUTHORITY', service=health['service'], attached=True, mutations_enabled=False,
                   context=context)
            f = Foundation(native, context=context, journal_path=DEFAULT_JOURNAL, interval=2)
            stack.callback(f.close)
            proof = f.journal.db.execute('SELECT proof FROM admission_withdrawals_v1 WHERE scope=? AND trade_id=?',
                (f.registry.scope, gate['decision']['identity']['trade_id'])).fetchone()
            need(proof is not None, 'local_admission_withdrawal_required')
            record('STARTUP_BEFORE', registry=f.registry.current())
            recovery = reconcile(f)  # The actual production startup integration.
            need(len(native.commands) == len(native.responses) == 3, 'complete_three_read_probe_required')
            requests = [n for r in native.responses for n in r['result']['network']]
            need(len(requests) == 3 and all(n['method'] == 'GET' and n['status'] == 200 for n in requests),
                 'three_genuine_successful_EA_GETs_required')
            view = f.registry.current()
            need(not view['queued'] and not view['unresolved'] and view['capacity']['unresolved'] == 0,
                 'startup_still_has_unresolved_commitments')
            need(view['credits']['fresh'] is True and view['capacity']['fresh'] is True,
                 'fresh_credits_and_complete_inventory_required')
            record('STARTUP_AFTER', registry=view, recovery=recovery)
            result.update(status='PASS', recovery=recovery, native_requests=3,
                          scope=f.registry.scope, epoch=f.registry.epoch, unresolved=0,
                          credits=view['credits']['available_coins'], capacity=view['capacity'])
    except Exception as error:
        reason = str(error) if type(error) is ValueError and str(error).replace('_','').isalnum() else type(error).__name__
        result.update(reason=reason)
        record('PROBE_STOPPED', reason=reason)
    finally:
        result.update(command_attempts=len(native.commands), responses=len(native.responses))
        (output/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = probe(args.output)
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)

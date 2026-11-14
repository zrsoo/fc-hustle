"""Final integrated experiment: sealed captures, fail-closed budgets and assessment.

Nothing launches on import. Captures contain protocol projections, never browser
storage, credentials or arbitrary exception bodies. Missing natural events fail
full acceptance even when the bounded procedure itself stopped correctly.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

from fc_access.production_v1.contracts import LOCAL_OPERATIONS, MUTATIONS, command, parse_response, stamp
from .native import Broker


def utc():
    return datetime.now(timezone.utc).isoformat()


def seal(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class Evidence:
    """Exclusive run creation and hash-chained, fsynced immutable experiment rows."""
    def __init__(self, path):
        self.path = Path(path)
        self.handle = self.path.open('x', encoding='utf8')
        self.previous = None
        self.count = 0

    def append(self, kind, **values):
        row = dict(seq=self.count + 1, at=utc(), kind=kind, previous=self.previous, **values)
        row['evidence_sha256'] = seal(row)
        self.handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.previous = row['evidence_sha256']
        self.count += 1
        return row

    def close(self):
        self.handle.close()


def load_evidence(path):
    rows, previous = [], None
    for line in Path(path).read_text(encoding='utf8').splitlines():
        row = json.loads(line)
        digest = row.pop('evidence_sha256')
        if row['seq'] != len(rows) + 1 or row['previous'] != previous or seal(row) != digest:
            raise ValueError('captured_evidence_integrity_failure')
        row['evidence_sha256'] = digest
        rows.append(row)
        previous = digest
    if not rows:
        raise ValueError('empty_evidence')
    return rows


def preflight(executor, evidence, *, sleep=time.sleep, operations=('balance', 'watched', 'transfer_list')):
    """Three paced authenticated native reads, without takeover or any mutation."""
    health = executor.request('/health')
    evidence.append('SERVICE', service=health.get('service'), schema=health.get('schema'),
                    attached=health.get('attached'), mutations_enabled=health.get('mutations_enabled'))
    if health.get('service') != 'fc-production-v1' or health.get('schema') != 2 or not health.get('attached'):
        evidence.append('PREFLIGHT_STOP', reason='OFFICIAL_PRODUCTION_ATTACHMENT_REQUIRED')
        return False
    peer = health['peer']
    for operation in operations:
        c = command(dict(schema=2, id=secrets.token_hex(16), operation=operation, params={}, **deepcopy(peer)))
        evidence.append('READ_INTENT', command=c)
        try:
            response = parse_response(executor.execute(c), c, source='native', now=datetime.now(timezone.utc))
        except (ValueError, TimeoutError):
            evidence.append('PREFLIGHT_STOP', reason='NATIVE_READ_FAILED', operation=operation)
            return False
        evidence.append('NATIVE_READ', command=c, response=response)
        if not response['result']['success']:
            evidence.append('PREFLIGHT_STOP', reason=response['result']['error'], operation=operation)
            return False
        # Watched coverage is intentionally conservative in protocol 2. Match
        # enrolled identities individually; an empty watchlist is never evidence
        # of loss. Only the complete Transfer List authorizes capacity/bulk work.
        if operation == 'transfer_list' and not response['coverage']['complete']:
            evidence.append('PREFLIGHT_STOP', reason='INCOMPLETE_NATIVE_INVENTORY', operation=operation)
            return False
        if operation == 'transfer_list':
            from fc_access.production_v1.bulk import classify
            try:
                groups = classify(response)
            except ValueError:
                # Complete physical coverage authorizes capacity accounting.
                # Unsupported bulk predicates block maintenance dispatch in its
                # own unchanged classifier; resale must still list owned cards.
                from .occupancy import assess as occupancy_assess
                physical=occupancy_assess(response,c,now=datetime.now(timezone.utc),source='native')
                if physical['occupied'] is None:
                    evidence.append('PREFLIGHT_STOP',reason='INCOMPLETE_NATIVE_INVENTORY')
                    return False
                groups=None
                evidence.append('BULK_BLOCKED_UNTIL_CLASSIFIED',reason='CURRENT_BULK_CONTRACT_UNPROVEN')
            evidence.append('INVENTORY', groups=groups, occupied=len(response['result']['auctions']))
        sleep(2)
    evidence.append('PREFLIGHT_READY', context=peer['context'], fences=peer['fences'])
    return True


class BoundedBroker(Broker):
    """A stop fences dispatch itself, including internal native request fanout.

    A conservative 16-request allowance is reserved before each native command;
    actual counts replace it only after a parsed response. Unknown writes and
    unsuccessful responses halt the entire experiment; nothing is resubmitted.
    """
    def __init__(self, *args, wall_seconds=7200, request_threshold=1800,
                 max_enrollments=12, evidence=None, extra_requests=0, **kwargs):
        super().__init__(*args, **kwargs)
        if type(wall_seconds) is not int or not 0 < wall_seconds <= 7200:
            raise ValueError('invalid_wall_bound')
        if type(request_threshold) is not int or not 16 <= request_threshold <= 1800:
            raise ValueError('invalid_request_bound')
        if type(max_enrollments) is not int or not 1 <= max_enrollments <= 12:
            raise ValueError('invalid_enrollment_bound')
        self.end = self.clock() + wall_seconds
        self.threshold, self.max_enrollments = request_threshold, max_enrollments
        if type(extra_requests) is not int or extra_requests < 0:
            raise ValueError('invalid_prior_request_count')
        # Reconnect preserves consumed work and conservative ambiguous fanout.
        self.requests = extra_requests
        for encoded, response, started, state in self.mailbox.db.execute(
                'SELECT command,response,started,state FROM work'):
            if response:
                self.requests += json.loads(response)['freshness']['request_count']
            elif started and state in {'CLAIMED','UNKNOWN'} and json.loads(encoded)['operation'] not in LOCAL_OPERATIONS:
                self.requests += 16
        self.stopped_reason = None
        self.evidence = evidence

    def halt(self, reason):
        if self.stopped_reason is None:
            self.stopped_reason = reason
            if self.evidence:
                self.evidence.append('DISPATCH_STOP', reason=reason, requests=self.requests)

    def run_one(self):
        if self.stopped_reason:
            return None
        if self.clock() >= self.end:
            self.halt('WALL_DEADLINE')
            return None
        if self.requests + 16 > self.threshold:
            self.halt('REQUEST_THRESHOLD')
            return None
        enrolled = self.mailbox.db.execute("SELECT count(*) FROM work WHERE role='acquirer' "
            "AND json_extract(command,'$.operation')='bid' AND state IN ('DONE','UNKNOWN','CLAIMED')").fetchone()[0]
        if enrolled >= self.max_enrollments:
            self.halt('ENROLLMENT_BOUND')
            return None
        result = super().run_one()
        if result is None:
            return None
        c, encoded, state = self.mailbox.db.execute(
            'SELECT command,response,state FROM work WHERE id=?', (result['command_id'],)).fetchone()
        c, response = json.loads(c), json.loads(encoded) if encoded else None
        count = response['freshness']['request_count'] if response else (0 if c['operation'] in LOCAL_OPERATIONS else 16)
        self.requests += count
        if self.evidence:
            role, priority = self.mailbox.db.execute('SELECT role,priority FROM work WHERE id=?',
                (result['command_id'],)).fetchone()
            self.evidence.append('DISPATCH_RESULT', command=c, response=response, state=state,
                                 measured=result, counted_requests=count, role=role, priority=priority)
        if state == 'UNKNOWN':
            self.halt('UNKNOWN_WRITE' if c['operation'] in MUTATIONS else 'UNKNOWN_READ')
        elif not response['result']['success']:
            self.halt('NATIVE_SERVICE_FAILURE')
        elif count > 16:
            self.halt('NATIVE_FANOUT_CONTRACT_CHANGE')
        return result


# Each named proof has a separate full-acceptance requirement. Offline coverage
# can explain behavior, but cannot turn a missing native branch into a live pass.
REQUIRED = {
    0: ('prerequisites', 'concurrent_python_actors', 'production_native', 'durable_state', 'single_priority_executor'),
    1: ('discovery_filters', 'fresh_valuation', 'cached_valuation', 'spendable_funds', 'minimum_initial_bid',
        'leading_hold', 'active_outbid', 'minimum_rebid', 'cap_stop', 'terminal_won', 'terminal_lost', 'exact_owned_paid'),
    2: ('stored_price_listing_3600', 'expired_one_call_relist', 'unchanged_relist_prices_duration',
        'sold_one_call_clear', 'independent_maintenance_readbacks'),
    3: ('capacity_accounting', 'capacity_pause_resume', 'sticky_draining', 'whole_queue_intervals',
        'native_fanout_deadline_misses', 'priority_under_load', 'restart_reconnect', 'unknown_reconciliation',
        'attributable_realized_profit'),
    4: ('enrolled_status_coverage', 'natural_expiry_observations', 'natural_funds_observations'),
    5: ('offline_regressions', 'all_transaction_and_maintenance_branches'),
    6: ('honest_missing_evidence',),
    7: ('final_item_order', 'append_only_evidence', 'failure_reported', 'all_run_processes_stopped'),
}


def assess(path):
    """Native capture assessment defaults to no proof. No declarative PASS input.

    Explicitly reports unimplemented/absent evidence analyses as LIVE-UNVERIFIED.
    A report, HTTP 200, fixture, or historical component test cannot supply them.
    """
    if (Path(path).parent/'supervisor.jsonl').exists():
        from .final_assessment import audit
        return audit(Path(path).parent)
    rows = load_evidence(path)
    observed = {}
    for row in rows:
        if row['kind'] in {'NATIVE_READ', 'DISPATCH_RESULT'} and row.get('response'):
            c, r = row['command'], row['response']
            parse_response(r, c, source='native', now=stamp(r['freshness']['observed_at']))
            if r['result']['success'] and c['context']['platform'] == 'pc':
                observed.setdefault('production_native', []).append(row['seq'])
        if row['kind'] == 'RUN_STOPPED' and row.get('remaining_processes') == [] and row.get('verified_process_exit') is True:
            observed.setdefault('all_run_processes_stopped', []).append(row['seq'])
    # Integrity is measured over the captured experiment, never mutable source.
    observed['append_only_evidence'] = [rows[-1]['seq']]
    criteria = []
    for index, requirements in REQUIRED.items():
        missing = [name for name in requirements if name not in observed]
        criteria.append(dict(index=index, status='PASS' if not missing else 'LIVE-UNVERIFIED',
                             missing=missing, evidence={k:observed[k] for k in requirements if k in observed}))
    return dict(task='002-12', status='FULL PASS' if all(c['status']=='PASS' for c in criteria) else 'PARTIAL/NOT FULL PASS',
                criteria=criteria, captured_rows=len(rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    f = sub.add_parser('preflight'); f.add_argument('--evidence', required=True)
    f.add_argument('--inventory-only', action='store_true')
    a = sub.add_parser('assess'); a.add_argument('--evidence', required=True)
    args = p.parse_args()
    if args.action == 'preflight':
        from fc_access.production_v1.executor import EdgeExecutor
        e = Evidence(args.evidence)
        try:
            e.append('WINDOW_OPENED', task='002-12', mode='READ_ONLY_PREFLIGHT', actor_launches=0)
            ready = preflight(EdgeExecutor(), e, operations=('transfer_list',) if args.inventory_only else ('balance', 'watched', 'transfer_list'))
            e.append('RUN_STOPPED', remaining_processes=[], verified_process_exit=True, actor_launches=0)
        finally:
            e.close()
        print(json.dumps(dict(status='READY' if ready else 'NOT_READY', evidence=args.evidence)))
        return 0 if ready else 1
    report = assess(args.evidence)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'FULL PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())

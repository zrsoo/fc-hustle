"""Bounded semantic fault policy. No sockets, account actions, retries or restarts."""
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class SemanticLimits:
    auth_failures: int = 2
    read_failures: int = 3
    write_failures: int = 3
    unconfirmed_attempts: int = 3
    missing_statuses: int = 3
    batch_failures: int = 3
    native_freshness: float = 90


def native_summary(command, response=None):
    """Copy only typed, public diagnostics from the existing delivery boundary."""
    value = response if type(response) is dict else {}
    result = value if command['schema'] == 4 else value.get('result', {})
    if type(result) is not dict: result = {}
    correlated = (value.get('command_id') == command['id'] and
                  all(value.get(k) == command[k] for k in ('schema', 'operation', 'context', 'fences')))
    network = result.get('network', [])
    if type(network) is not list: network = []
    network = [n for n in network if type(n) is dict]
    receipt = result.get('receipt') if command['schema'] == 4 else result.get('bid_receipt')
    receipt = receipt if type(receipt) is dict else {}
    error = result.get('error')
    from .protocol import READS, SHARED_READS
    from fc_access.production_v1.contracts import ERRORS
    allowed = ERRORS | {'invalid_command','bridge_busy','interrupted','internal_error'}
    status = result.get('status')
    statuses = [n['status'] for n in network if type(n.get('status')) is int and 100 <= n['status'] <= 599]
    local = command['operation'] == 'price_helpers'
    return dict(operation=command['operation'], command_id=command['id'],
        local=local, read=command['operation'] in READS | SHARED_READS and not local,
        success=correlated and result.get('success') is True and bool(network) and
                all(n.get('session_header_present') is True and n.get('status') == 200 for n in network),
        error=error if type(error) is str and error in allowed else None,
        service_status=status if type(status) is int and 100 <= status <= 599 else None,
        wire_statuses=statuses, receipt_verdict=receipt.get('verdict') if receipt.get('verdict') in {'ACCEPTED','REJECTED','UNCONFIRMED'} else None,
        requested=len(command['params'].get('targets', [])),
        returned=len(result['auctions']) if type(result.get('auctions')) is list else 0)


class SemanticHealth:
    def __init__(self, limits=SemanticLimits(), *, clock=time.monotonic):
        self.limits, self.clock = limits, clock
        self.started = clock()
        self.last_native_success = None
        self.read_failures = self.write_failures = self.auth_failures = 0
        self.missing_statuses = self.unconfirmed_attempts = 0
        self.native_successes = self.confirmed = self.batches = 0
        self.read_streaks = {}
        self.write_streaks = {}
        self.batch_failures = 0
        self.reason = None

    def observe(self, message):
        if self.reason: return
        if message['kind'] == 'native_result':
            if message['local']: return
            success = message['success']
            if success:
                self.last_native_success = self.clock()
                self.native_successes += 1
                self.auth_failures = 0
            elif 401 in message['wire_statuses'] or message['service_status'] == 401 or message['error'] in {'unauthenticated', 'persona_unverified'}:
                self.auth_failures += 1
            if message['read']:
                op=message['operation']
                self.read_streaks[op] = 0 if success else self.read_streaks.get(op,0)+1
                self.read_failures = max(self.read_streaks.values())
                if message['operation'] == 'status_batch':
                    self.missing_statuses = self.missing_statuses + 1 if success and message['requested'] and not message['returned'] else 0
            elif message['receipt_verdict'] != 'REJECTED':
                # An ordinary proven rejection is an account outcome. Other
                # failed writes remain unknown; no effect or refund is inferred.
                op=message['operation']
                self.write_streaks[op] = 0 if success else self.write_streaks.get(op,0)+1
                self.write_failures = max(self.write_streaks.values())
        elif message['kind'] == 'batch_result':
            self.batches += 1
            self.batch_failures = self.batch_failures+1 if message.get('state') in {'READ_FAILED','OPERATION_FAILED','INVENTORY_UNKNOWN'} else 0
            if message['confirmed']:
                self.confirmed += message['confirmed']
                self.unconfirmed_attempts = 0
            else:
                self.unconfirmed_attempts += message['uncertain']
        self.check()

    def check(self):
        if self.reason: return self.reason
        for observed, threshold, reason in (
            (self.auth_failures, self.limits.auth_failures, 'PERSISTENT_AUTH_FAILURE'),
            (self.read_failures, self.limits.read_failures, 'PERSISTENT_READ_FAILURE'),
            (self.write_failures, self.limits.write_failures, 'PERSISTENT_WRITE_FAILURE'),
            (self.missing_statuses, self.limits.missing_statuses, 'PERSISTENT_EMPTY_MANAGED_STATUS'),
            (self.batch_failures, self.limits.batch_failures, 'PERSISTENT_ACQUISITION_FAILURE'),
            (self.unconfirmed_attempts, self.limits.unconfirmed_attempts, 'PERSISTENT_UNCONFIRMED_ACQUISITION')):
            if observed >= threshold:
                self.reason = reason; return reason
        age = self.clock() - (self.last_native_success if self.last_native_success is not None else self.started)
        if not math.isfinite(age) or not 0 <= age <= self.limits.native_freshness:
            self.reason = 'NO_FRESH_NATIVE_SUCCESS'
        return self.reason

    def snapshot(self):
        return dict(reason=self.check(), native_successes=self.native_successes,
                    native_success_age=None if self.last_native_success is None else self.clock()-self.last_native_success,
                    read_failures=self.read_failures, write_failures=self.write_failures,
                    auth_failures=self.auth_failures, missing_statuses=self.missing_statuses,
                    batch_failures=self.batch_failures,
                    unconfirmed_attempts=self.unconfirmed_attempts, confirmed=self.confirmed, batches=self.batches)

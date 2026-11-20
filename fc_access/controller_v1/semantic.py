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
    helper_failures: int = 3
    diagnostic_failures: int = 3
    native_freshness: float = 90
    # Tolerant mode only: stop when bids keep being denied with none accepted.
    denial_window: float = 600


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
    # A coherent native 200 can report that a competitor overtook this bid.
    # It grants no acknowledgement or membership, but is not a transport fault.
    row = receipt.get('auction')
    target = command['params'].get('target', {})
    amount = command['params'].get('amount')
    market_race = (correlated and command['schema'] == 4 and command['operation'] == 'bid' and
        result.get('success') is False and error == 'bid_unconfirmed' and status == 200 and
        len(network) == 1 and network[0].get('status') == 200 and
        network[0].get('session_header_present') is True and receipt.get('verdict') == 'UNCONFIRMED' and
        receipt.get('native_success') is True and receipt.get('native_error_code') is None and
        receipt.get('wire_error_code') is None and receipt.get('wire_identity_matches') is True and
        receipt.get('wire_amount_matches') is True and type(amount) is int and
        receipt.get('wire_trade_id') == target.get('trade_id') and
        receipt.get('wire_amount') == amount and receipt.get('wire_item_count') == 1 and
        receipt.get('native_item_count') == 1 and receipt.get('matching_item_count') == 1 and
        receipt.get('input_stale') is False and type(row) is dict and
        row.get('trade_id') == target.get('trade_id') and type(row.get('item')) is dict and
        row['item'].get('item_id') == target.get('item_id') and
        row['item'].get('definition_id') in (None, 0, target.get('definition_id')) and
        row.get('trade_state') == 'active' and row.get('bid_state') == 'outbid' and
        type(row.get('current_bid')) is int and row['current_bid'] > amount)
    # EA 470 NOT_ENOUGH_CREDIT on this exact bid: an account outcome (no coins),
    # not a transport or write fault.
    no_credit = (correlated and command['schema'] == 4 and command['operation'] == 'bid' and
        result.get('success') is False and status == 403 and len(network) == 1 and
        network[0].get('status') == 470 and receipt.get('verdict') == 'UNCONFIRMED' and
        receipt.get('native_error_code') == 470 and receipt.get('native_error_name') == 'NOT_ENOUGH_CREDIT' and
        receipt.get('native_item_count') == 0 and receipt.get('wire_identity_matches') is True and
        receipt.get('wire_amount_matches') is True)
    return dict(operation=command['operation'], command_id=command['id'],
        local=local, read=command['operation'] in READS | SHARED_READS and not local,
        market_race=market_race, no_credit=no_credit,
        success=correlated and result.get('success') is True and
                (local and not network or not local and bool(network) and result.get('status') == 200 and
                 all(n.get('session_header_present') is True and n.get('status') == 200 for n in network)),
        error=error if type(error) is str and error in allowed else None,
        service_status=status if type(status) is int and 100 <= status <= 599 else None,
        wire_statuses=statuses, receipt_verdict=receipt.get('verdict') if type(receipt.get('verdict')) is str and receipt['verdict'] in {'ACCEPTED','REJECTED','UNCONFIRMED'} else None,
        requested=len(command['params'].get('targets', [])),
        returned=len(result['auctions']) if type(result.get('auctions')) is list else 0)


class SemanticHealth:
    def __init__(self, limits=SemanticLimits(), *, clock=time.monotonic, tolerate_denials=False):
        self.limits, self.clock = limits, clock
        # With tolerate_denials, a 461/403 bid denial is an ordinary no-effect
        # outcome; only a denial run without any accepted bid for
        # limits.denial_window seconds stops the runtime.
        self.tolerate_denials = tolerate_denials
        self.denied_bids = 0
        self.denial_since = None
        self.started = clock()
        self.last_native_success = None
        self.read_failures = self.write_failures = self.auth_failures = 0
        self.missing_statuses = self.unconfirmed_attempts = 0
        self.native_successes = self.confirmed = self.batches = 0
        self.read_streaks = {}
        self.write_streaks = {}
        self.batch_failures = 0
        self.helper_failures = 0
        self.diagnostic_failures = 0
        # Consecutive bids the server denied with native 461 / service 403 while
        # reads kept working. Evidence pairs this signature with a stale official
        # document that a normal reload/sign-in restored; the stop reason itself
        # stays PERSISTENT_WRITE_FAILURE and no bid outcome is inferred.
        self.denial_streak = 0
        # Transfer-market searches EA refused with HTTP 429. The controller pauses
        # acquisition; a throttle is neither a read failure nor progress.
        self.search_throttles = 0
        self.credit_rejections = 0
        self.reason = None

    def observe(self, message):
        if self.reason: return
        if message['kind'] == 'native_result':
            if message.get('diagnostic_records') is not None:
                count=message['diagnostic_records']
                self.diagnostic_failures = 0 if type(count) is int and count>0 else self.diagnostic_failures+1
            if message['local']:
                self.helper_failures = 0 if message['success'] else self.helper_failures+1
                self.check()
                return
            success = message['success']
            if success:
                self.last_native_success = self.clock()
                self.native_successes += 1
                self.auth_failures = 0
            elif 401 in message['wire_statuses'] or message['service_status'] == 401 or message['error'] in {'unauthenticated', 'persona_unverified'}:
                self.auth_failures += 1
            if message['read'] and not success and message['operation'] == 'search' and 429 in message['wire_statuses']:
                self.search_throttles += 1
            elif message['read']:
                op=message['operation']
                self.read_streaks[op] = 0 if success else self.read_streaks.get(op,0)+1
                self.read_failures = max(self.read_streaks.values())
                if message['operation'] == 'status_batch':
                    self.missing_statuses = self.missing_statuses + 1 if success and message['requested'] and not message['returned'] else 0
            elif message.get('no_credit') is True:
                self.credit_rejections += 1
            elif message['receipt_verdict'] != 'REJECTED' and message.get('market_race') is not True:
                # An ordinary proven rejection is an account outcome. Other
                # failed writes remain unknown; no effect or refund is inferred.
                op=message['operation']
                self.write_streaks[op] = 0 if success else self.write_streaks.get(op,0)+1
                self.write_failures = max(self.write_streaks.values())
                denied = (not success and op == 'bid' and message['wire_statuses'] == [461] and
                          message['service_status'] == 403 and message['receipt_verdict'] in (None, 'UNCONFIRMED'))
                self.denial_streak = self.denial_streak+1 if denied else 0
                if denied:
                    self.denied_bids += 1
                    if self.denial_since is None: self.denial_since = self.clock()
                    if self.tolerate_denials:
                        # Not a write failure in this mode; undo its streak count.
                        self.write_streaks[op] -= 1
                        self.write_failures = max(self.write_streaks.values())
                elif success and op == 'bid':
                    self.denial_since = None
        elif message['kind'] == 'batch_result' and message.get('state') == 'MAINTENANCE_FAILED':
            # Unconfirmed capacity cleanup; acquisition only sees CAPACITY_FULL.
            self.batch_failures += 1
        elif message['kind'] == 'batch_result':
            self.batches += 1
            state = message.get('state')
            # A full watch list neither proves progress nor is itself a fault:
            # it leaves the failure streak unchanged until MAINTENANCE acts.
            if state not in {'CAPACITY_FULL', 'THROTTLED', 'LOW_CREDITS', 'COINS_RESERVED'}:
                self.batch_failures = self.batch_failures+1 if state in {'READ_FAILED','OPERATION_FAILED','INVENTORY_UNKNOWN'} else 0
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
            (self.helper_failures, self.limits.helper_failures, 'PERSISTENT_HELPER_FAILURE'),
            (self.diagnostic_failures, self.limits.diagnostic_failures, 'PERSISTENT_MISSING_DIAGNOSTICS'),
            (self.unconfirmed_attempts, self.limits.unconfirmed_attempts, 'PERSISTENT_UNCONFIRMED_ACQUISITION')):
            if observed >= threshold:
                self.reason = reason; return reason
        if (self.tolerate_denials and self.denial_since is not None and
                not 0 <= self.clock()-self.denial_since < self.limits.denial_window):
            self.reason = 'PERSISTENT_BID_DENIAL'; return self.reason
        age = self.clock() - (self.last_native_success if self.last_native_success is not None else self.started)
        if not math.isfinite(age) or not 0 <= age <= self.limits.native_freshness:
            self.reason = 'NO_FRESH_NATIVE_SUCCESS'
        return self.reason

    def recoverable(self):
        """Only the evidenced stale-document signature, never other write faults."""
        if (self.check() == 'PERSISTENT_WRITE_FAILURE' and self.denial_streak >= self.limits.write_failures and
                self.read_failures == 0 and self.auth_failures == 0 and self.native_successes > 0):
            return 'STALE_DOCUMENT_WRITE_DENIAL'
        return None

    def snapshot(self):
        return dict(reason=self.check(),recoverable=self.recoverable(),denied_bids=self.denied_bids,
                    denial_seconds=None if self.denial_since is None else self.clock()-self.denial_since, native_successes=self.native_successes,
                    native_success_age=None if self.last_native_success is None else self.clock()-self.last_native_success,
                    read_failures=self.read_failures, write_failures=self.write_failures,
                    auth_failures=self.auth_failures, missing_statuses=self.missing_statuses,
                    batch_failures=self.batch_failures,
                    helper_failures=self.helper_failures,
                    diagnostic_failures=self.diagnostic_failures,
                    unconfirmed_attempts=self.unconfirmed_attempts, confirmed=self.confirmed, batches=self.batches,
                    search_throttles=self.search_throttles, credit_rejections=self.credit_rejections)

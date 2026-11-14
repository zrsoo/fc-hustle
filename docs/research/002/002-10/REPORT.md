# 002-10 — restart-safe bulk relist scheduling

Implemented and verified offline. Recurring live execution and integrated EA
evidence remain deferred to item 12. No official Web App session or completed
research window was used for this task.

`fc_access.actors_v1.relist.BulkRelistScheduler` provides one-step due checking
and an explicit bounded runner. The CLI is `python -m fc_access.actors_v1
--state-dir <existing-executor-state> bulk-relist --ticks <positive-count>`.
This documents the later launch interface; it was exercised only with the
synthetic native broker. No actor or executor starts this job automatically.

The locked settings are 3660 seconds between tick starts, preserve prior
prices, and observed relist duration 3600 seconds. The account-scoped SQLite
deadline and RUNNING tick commit together with an append-only TICK_STARTED
event before any inventory request. Restart preserves the deadline, early
calls do no account work, and missed windows collapse to one current tick.
The OS process lock prevents concurrent scheduling of the same window.
Interrupted ticks recover through fresh inventory and read-only reconciliation;
they never resume dispatch, even if the crash preceded the native intent.

Every due tick delegates to the existing durable BulkTransfer operation.
Fresh complete Transfer List evidence is required before dispatch or NOOP;
pending bulk intents instead obtain fresh independent reconciliation reads.
An empty eligible set records both EMPTY_SKIP and a scheduler NOOP with the
read ID, including a sold-only pile. Invalid, truncated, stale, failed or
unowned inventory fails closed. The existing item-9 safety boundary remains:
inactive/unclassified inventory and a mixed sold/expired relist mutation are
unsupported; the scheduler never clears sold cards to force a relist through.

Eligible expired cards, including manual cards without actor enrollment, form
one account-wide immutable intent. One native relist-all mutation follows its
separately committed consumed claim. Production scheduling requires the
maintenance QueueExecutor, priority 0, through the sole Broker. Urgent Bidder
commands preempt at command boundaries. Native calls already in flight cannot
be preempted.

The independent Transfer List readback must conserve all physical items, map
every target to a unique new trade, retain every starting bid and BIN, and
observe expiry exactly 3600 for every target. Existing active items remain
unchanged except normal expiry countdown. Relisting neither reprices nor frees
occupied capacity. A changed price or duration is sticky incompatibility;
partial/no-effect outcomes and missing acknowledgements cannot grant retries.
Lost acknowledgements can confirm only through complete independent evidence.

Run these independent behavioral validators from the workspace:

| Command | Acceptance criteria (zero-based) | Evidence |
| --- | --- | --- |
| `python tests/test_00210_relist.py` | 0, 1, 2, 3 | Fresh no-ops and invalid reads; exact account-wide targets/prices/duration/capacity; 3660s restart cadence and missed windows; persistence failures; real process deaths at seven boundaries; real mailbox priority and separate CLI/broker processes; ambiguity and no implicit live launch |
| `python tests/test_00209_bulk.py` | 1, 2, 3 | Durable native operation contracts, per-item identity/trade/price/duration negative cases, crash recovery, deployed JavaScript native API/worker behavior, sealed transaction evidence |
| `python tests/test_00204_actors.py` | 3 | Shared executor priority, request pacing, independent actors, journal replay and existing Bidder behavior |

Verification on 2026-11-14: all 17 scheduling tests, 20 bulk tests and 18 actor
tests passed. The 18-test resale regression suite also passed (73 Python tests
total). Bulk/resale validators include the native JavaScript checks. The tracked
workspace diff passed `git diff --check`.

Tests check behavior and contracts. They do not assert hashes or byte identity
of mutable implementation, tests, configuration or instructions. Existing sealed
transaction evidence retains its integrity validation.

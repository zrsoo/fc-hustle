# 002-04 independent actors

Implemented in `fc_access/actors_v1`. Importing modules, inspecting configuration
and running diagnostics do not attach to Edge or start workers. This task ran
only finite synthetic actors. No sustained live actor or EA mutation was launched.
The retained sixth 002-03 gate is the dependency: uncached valuation to fresh
eligible decision passed in 12.069805600 seconds. It was not repeated.

## Process model

`acquirer` and `bidder` are separate Python entry points. They join the same
account/persona/game/platform/identity-namespace session and epoch, SQLite
WAL/FULL journal, completed quote cache and `native.sqlite3` mailbox. Neither
actor activates a new browser owner. A single `executor` owns attachment and
native dispatch. OS locks exclude a second executor for the same transport port
and a second instance of either actor; a short account write lock serializes
final bid decisions. The existing HTTP service separately enforces the committed
intent and all identity fences. No HTTP boolean authorizes a bid.

Native priorities are reconciliation 100, Bidder/watched/status/bid 90,
Acquirer/pricing 10, maintenance 0, with deadline then FIFO ordering inside each
priority. Every native search/helper/read/write is a scheduling boundary.
An in-flight command finishes once; the next pricing/maintenance command yields
to already queued urgent work. The configurable default two-second native gap
does not charge zero-request native helpers. No parallel native call is allowed.

Defaults are in `defaults.json`: Acquirer 600 seconds, Bidder target 25 seconds,
discovery maxBid 1000/minBuy 11000, reserve 5000, unresolved limit 50 and X=500.
Intervals, filters, reserve, limit (1 through 50), page bound and X are configurable.
The established two page-1/count-21 pricing samples, 5% tax, native tick rules,
24-hour exact-version cache and outbid-only/minimum-bid policy stay fixed.
Discovery permits at most ten pages (default three); pricing permits only page 1.
Both Python and the actual page bridge validate wire `macr`, `minb`, `start` and
`num`, including changed filter settings. Returned candidate values are checked
again; conflicting duplicates and physical-item aliases are rejected. Full
market coverage is never inferred from a bounded search.

Acquirer uses the existing production `PricingService` and `NativePrices`, then
refreshes exact candidate identity and spendable credits under the write lock.
The tax/X ceiling rounds down through native helpers. Initial dispatch uses the
smallest legal bid, independent of the discovery threshold. Each acquisition
cycle dispatches at most one enrollment, leaving independent readback to Bidder
before another write. This conservative bound can reduce enrollment throughput.
Bidder persists explicit leading HOLD, uses stored resale/X/cap without repricing,
and refreshes outbid state and actual spendable credits again before writing.
The native next-tick result is an absolute amount. Existing escrow is never added
to spendable credits. Cap-exhausted, missing, stale and ambiguous auctions remain
tracked. LOST requires an exact fresh terminal outbid row. WON requires a closed
highest row, a fresh independent exact owned-item read and attributable bid price.
Native victory alone is PENDING. Acquisition Buy Now is outside the command schema.

## Persistence and recovery

The existing append-only journal commits intent and one-use dispatch claims
before sending. Queue enrollment, reservations, sticky DRAINING and terminal
settlement evidence replay from events. The enrollment event stores the original
quote/cap; later intents cannot increase it. Native enqueue, claim, response,
deadline and restart events are also transactional and append-only. Parameters
pass the production allowlist before retention; arbitrary native exception text,
headers and credential values never enter diagnostics. Failed intent or queue
journal persistence blocks dispatch.

Executor restart marks both waiting and claimed mailbox work UNKNOWN. A recovered
intent never regains local dispatch authority. Restart/reconnect takes a new
epoch, starts actors against that epoch and obtains fresh read-only watched and
credit observations before a new write. Missing/conflicting evidence keeps the
intent unresolved; neither ACK nor timeout causes a retry. New bids remain
account-wide blocked until ambiguous writes reconcile. Sticky coin DRAINING only
clears at a later acquisition cycle after all auctions are terminal and fresh
funds exceed the reserve. Prior-epoch observations are retained as history.

Actor loops use monotonic deadlines, skip missed cadence slots and preserve the
previous start time over process restart. Events record measured elapsed time
and missed targets. Executor events retain queue wait from UTC timestamps,
monotonic native roundtrip, native-service timing and request count; unknown
timings stay null. Per-actor Foundation metrics also include IPC/mailbox wait in
their delivery residual. The 25-second interval is a target, not a live SLA claim.

## Operator entry points

Read-only examples, run from the workspace:

```text
python -m fc_access.actors_v1 config
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 status
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 timeline --trade-id trade:000000000000000000000001
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 decisions --since 2026-11-14T00:00:00+00:00 --until 2026-11-15T00:00:00+00:00
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 blocked
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 export --output trace.json
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 retain private-captures/actor-backup
```

Status exposes actor heartbeats/freshness, coins after local reservations,
unresolved auction/intent state, draining, queue counts and latest decisions.
Timeline includes the bid journal and registry evidence. Export includes sanitized
native parameters/timing/epochs and accepts time windows. Existing export files
are never overwritten. Retention performs SQLite backups and prunes zero events:
unresolved intents and settlement/recovery evidence are always preserved. Stop
actors for a consistent cross-file restore point; transactional backups are per
file. A restore requires a new executor epoch and fresh reconciliation; runtime
metadata must point to the restored absolute journal/cache paths.

Future explicit execution entry points (not run by this task):

```text
python -m fc_access.production_v1.server --database private-captures/actors-v1/transport.sqlite3 --intent-database private-captures/actors-v1/journal.sqlite3
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 executor --context reviewed-context.json --config docs/research/002/002-04/defaults.json
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 acquirer --cycles 1
python -m fc_access.actors_v1 --state-dir private-captures/actors-v1 bidder --cycles 1
```

Omitting `--cycles` is an explicit sustained-run request. Keep these entry points
for later authorized integration: tasks 002-05 through 002-11 still own complete
Transfer List capacity, atomic combined reservations and sale/maintenance
integration. This task does not claim those later criteria or final live E2E.
The service remains read-only unless explicitly composed with the actor journal;
that composition still requires valid durable native bid intents.

## Repeatable acceptance

`python tests/test_00204_actors.py` covers all seven task criteria with behavioral
negative cases and real, bounded Python actor subprocesses against a synthetic
native page. `python tests/check_00204_artifacts.py` checks the operator/configuration
artifacts and actual CLI contracts. Neither compares implementation-file hashes.

| Criterion (zero based) | Checks |
| --- | --- |
| 0 | Exact defaults; changed settings; invalid settings; CLI help/config create no worker state |
| 1 | Separate actor processes join one epoch; urgent native order, pacing, helper yielding, OS exclusion |
| 2 | Actual bridge wire pagination/filter checks; duplicates; existing two-search pricing; minimum opening bid |
| 3 | HOLD; absolute native rebid; spendable limits; retained cap exhaustion; independent WON/LOST; Buy Now rejection |
| 4 | Independently readable intent/claim before send; disk failure; append-only journal/mailbox events; ambiguity/restart; timing/epoch data |
| 5 | Operator state, timelines, time-window decisions, blocked reasons, sanitized export; lossless retention/replay |
| 6 | Contention/scheduling, native rounding/equality, nonincreasing caps, reserve/escrow, stale identity, crash recovery and replay |

Additional existing regression commands are `tests/test_bidding_v1.py`,
`tests/test_001d02_contract.py`, `tests/test_001d03_native_prices.py`,
`tests/test_001d04_pricing.py` and `tests/test_001d06_foundation.py`.
Actual command exit codes, durations and individual stdout/stderr logs are
retained in `verification/results.json` and its referenced files. Reproduce the
offline verification with `python tests/record_00204_checks.py`.
All evidence here is offline verification of implementation. Real actor timing,
natural competitions, settlement and sustained operation remain later live work.

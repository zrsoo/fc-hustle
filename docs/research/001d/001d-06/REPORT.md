# 001d-06: finite production foundation

IMPLEMENTED / VERIFIED OFFLINE. No actors or real account writes were run. This
task does not claim live competitive bidding, ownership, listing or settlement.

The production entry point is `fc_access/production_v1/foundation.py:Foundation`.
Its version-1 registry and quote contracts compose the unchanged version-2 wire
contract in `fc_access/production_v1/contracts.py` and the version-1 bidding
journal. There is no external Codex supervisor dependency.

Exact call graph:

1. `Foundation.read` -> `fc_access/production_v1/adapter.py:NativeAdapter` ->
   `ScheduledExecutor` -> `fc_access/production_v1/executor.py:EdgeExecutor` ->
   localhost `/run` -> `fc_access/production_v1/store.py:Store.enqueue/claim` ->
   `browser/production-v1/worker.js` -> `browser/production-v1/page.js` -> EA native
   services. The worker returns one versioned response via `/result`.
2. `Foundation.admit` consumes adapter-retained exact search/watched and credits
   responses. `fc_access/production_v1/prices.py:PriceService` loads native caps
   and helpers; `fc_access/production_v1/pricing.py:PricingService.quote` performs
   the two-search quote or uses a completed 24-hour observation from
   `fc_access/production_v1/price_cache.py`. Quote evidence includes exact card,
   scope, independent comparable rows, read times, coverage and exclusions.
3. `fc_access/bidding_v1/core.py:decide/AuctionQueue.admit` checks freshness,
   legal minimum, profitable cap, deadline, spendable coins, reservations,
   reserve and capacity. Admission records ENROLLED and a reason-coded registry
   decision; it sends no bid. Valid profitable caps above 1000 remain supported.
   Discovery's maxBid=1000 filter is independent of this bid profitability cap.
4. An explicit `Foundation.bid(trade_id)` revalidates evidence through
   `NativeAdapter.dispatch_intent`. Its bridge maps the wire-2 command to
   `fc_access/bidding_v1/journal.py:Journal.intend/dispatch`: FULL synchronous
   INTENT_DURABLE before any send, then a committed PENDING single-dispatch claim,
   followed by the serialized executor and journal result. Native ACK is not a
   verified outcome. The scope remains fenced until independent reconciliation.
5. `Foundation.reconcile` accepts new adapter-owned watched/credits responses,
   validates context/identity/time and invokes `Journal.reconcile`. Missing rows
   stay UNKNOWN; closed/highest stays PENDING without independent ownership.
   `JournalAuthority.reconciled` lets the transport release a previous bid fence
   only when this journal records RECONCILED. It never resends the previous ID.

`fc_access/bidding_v1/scheduler.py:Scheduler` is reused with concurrency=1 and
configurable `interval` (default 0, no claimed EA-mandated 30-second delay).
Writes get priority +1; explicit higher priorities win, then earliest deadline,
then command ID. Only finite staged work drains. Expired work is skipped before
delivery. The journal also checks the deadline before dispatch; the transport and
page check again. A queued bid that becomes ambiguous remains UNKNOWN.
Local helper calls share the serialization lock but consume no EA request slot.
The caller owns a single Foundation per active account; a new journal session
fences a former owner. The transport additionally rejects concurrent native work.

Registry events retain separate `queue_ms`, `roundtrip_ms`, `delivery_ms`,
`native_service_ms`, `request_count` and `interval_seconds`. `delivery_ms` is an
estimate of total roundtrip minus the page's measured native service time;
`queue_ms` is the local admission-to-start delay. Delivery is never counted as
another native request. A dropped result has null native duration/request count
(unknown, not zero). Scheduler completion releases its local slot; durable
transport/journal uncertainty continues to fence writes. Scheduler's internal
legacy timing list measures occupied slot time; authoritative production native
duration is the separately persisted protocol timing above.

Registry ownership is keyed by a deterministic hash of validated
account/persona/game/platform/identity_namespace, plus exact auction/item/version.
Namespace changes produce a different scope and cannot recover a native ID.
`Registry.current()` exposes owner/epoch, durable queued identities, unresolved
commands, latest auction state, HOLD/REJECT/BID/UNKNOWN decisions with enumerated
reasons, available coins, freshness and available coins after local reservations.
`Registry.events(trade_id)` and `Journal.trace(scope=..., trade_id=...)` provide
ordered append-only per-auction history enforced by SQLite triggers. The latest
decision retains the complete quote and intent retains its digest, cap and tax.
Read API return values cannot mutate stored evidence. Restarted observations
become UNKNOWN; persisted coin observations expose their age-derived freshness.

The journal stores commands as UNKNOWN as soon as intent is durable. Crashes
before send or after the claim do not grant dispatch authority on restart.
Only a local one-use ticket can call dispatch; new epochs do not mint tickets for
old commands. Duplicate IDs fail; unresolved intents block new intents. Neither
an absent callback, timeout, service restart nor a missing watched row means
REJECT or unsent. NOT_DISPATCHED is possible only from positive same-process
deadline evidence before dispatch, never inferred from recovery. Service owner
epochs are read as public fencing metadata and the new journal epoch exceeds
both durable journal and service epochs after restart.

The production transport is the protocol-2 successor of
`fc_access/durability_v1/store.py`: it reuses the FULL-synchronous reservation,
claim-before-delivery, append-only audit, restart UNKNOWN and no-redelivery
design. The historical bounded store and captures are not migrated or rewritten;
its campaign budgets are absent from production. Production registry tables are
additive and do not change journal schema 1 or wire schema 2.

Files changed: `foundation.py`, `once.py`, `executor.py`, `store.py`,
`server.py` in `fc_access/production_v1`; `Journal.session` adds an optional
`after_epoch` fence floor without changing existing callers. Fixtures and
acceptance checks are `tests/foundation_fixture.py` and
`tests/test_001d06_foundation.py`.

Historical source audits use `tests/migration_001d06.py` and `migration.json`
here to compare their exact recorded source revision. `before/` snapshots match
the original entry or 001d-05 digest; the migration independently pins current
source hashes. `tests/migration_001d03.py` chains the foundation migration before
its existing pricing migration, and the 001d-05 evidence audit uses the same
strict reader. No sealed manifest, report or account capture is changed.
The 001d-02 import audit now permits exactly the four reused pure bidding
modules in foundation.py; experimental adapters and harnesses remain excluded.

Runtime files (never sealed research evidence):

- `private-captures/production-v1/foundation.sqlite3`: journal and registry.
- `private-captures/production-v1/completed-quotes.sqlite3`: complete quote cache.
- `private-captures/production-v1/transport.sqlite3`: localhost transport store.

The installed extension requires a **separately running localhost service** at
`127.0.0.1:8784`, plus its normal attached, authenticated official Web App tab:

```text
python -m fc_access.production_v1.server --database private-captures/production-v1/transport.sqlite3
python -m fc_access.production_v1.once --context public-context.json --definition-id 261855 --interval 0.2
```

The context file contains only the five public pseudonymous context labels.
The one-shot command performs finite read/quote/admission work and exits; it
never dispatches bids. The default service rejects all mutations. Future
Objective 002's application can explicitly compose
`Server(transport_path, intent_database=foundation_path)` and run that service
separately: this installs `JournalAuthority`, which matches a committed current
intent and dispatch claim against the exact context, amount, cap, identity,
deadline and independent read IDs. There is no HTTP write-enable flag. Transport
IDs still never replay. No service or browser recovery was started for this task.

Independent offline verification:

```text
python tests/test_001d06_foundation.py
python tests/test_bidding_v1.py
python tests/test_durability_v1.py
python tests/test_001d02_contract.py
python tests/test_001d03_native_prices.py
python tests/test_001d04_pricing.py
python tests/test_001d05_inventory.py
```

Acceptance checks execute the real adapter, native pricing service, admission,
scheduler, journal, production transport and authority with an in-process EA
fixture; sockets are forbidden during the main integration. Child Python
processes terminate abruptly before dispatch and inside native delivery, then
fresh processes inspect UNKNOWN replay and epoch fencing. Additional checks
cover dropped results, duplicate intents, stale reads, queue priority, cadence,
deadline skips, independent reconciliation, immutable event history and valid
2,500-coin fixture bids under a 10,750-coin profitable cap. Fixture subprocesses
exit and temporary local server objects are closed. No 600-second Acquirer,
25-second Bidder or persistent unattended process is started.

DEFERRED TO 002: actual actor ownership/periodic scheduling, sustained queue
coverage, real active-outbid rebids, won-item/paid-cost proof, listings and sale
settlement. These bounded fixtures establish integration and crash semantics,
not successful live account transactions.

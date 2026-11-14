# 002-11 — Automatic sold clearing and implementation regression

Implemented and verified with isolated native doubles, real SQLite journals,
independent processes and the deployed JavaScript contracts. No EA request,
browser recovery, historical experiment replay or live actor launch was used.
The final concurrent live run belongs to item 002-12.

`TransferMaintenance` is an explicit actor in
`fc_access/actors_v1/maintenance.py`. Its bounded CLI is:

```text
python -m fc_access.actors_v1 --state-dir <existing-state> maintenance --cycles <positive-count>
```

This command requires the existing shared broker. It polls every target
25 seconds, preserving the previous cycle's cadence across restart. Construction
and imports launch no work. Each cycle automatically checks for sold items before
consulting the existing durable 3660-second relist schedule. Do not launch a
second bulk-relist worker alongside this combined maintenance actor.

`SoldClear` obtains a fresh complete inventory under the existing account write
lock and cross-checks the native sold/expired/active predicates and ownership.
All sold items, including manually listed cards without actor enrollment, enter
one immutable bulk intent. Detection is logged before intent persistence; the
consumed claim commits separately before the native handoff. Production use
requires a maintenance QueueExecutor, priority 0, through the single Broker.
Urgent Bidder/reconciliation work takes precedence at command boundaries.

The actual mutation remains the previously integrated zero-argument
`services.Item.clearSoldItems()`, a single bodyless DELETE to
`/ut/game/fc27/trade/sold`. Its internal native refresh is counted as fanout,
not accepted as independent proof. A separate TRANSFER-dirty complete inventory
must prove every target absent and each expired/active survivor unchanged except
normal expiry countdown. An empty sold set records an empty skip. Incomplete,
stale, unowned, unclassified or contradictory inventories block dispatch. The
existing native contract intentionally fails closed on unsupported inactive
inventory; this task does not broaden historically verified bulk semantics.

Concurrent observers serialize around detection, intent and readback. A second
observer must obtain another inventory and cannot reuse the consumed snapshot.
After any uncertain outcome, restart, partial clear or no-effect acknowledgement,
the durable bulk record permits read-only reconciliation. It grants no blind
retry, replacement mutation or per-item fallback. A clear with missing or
incompatible readback blocks the cycle's relist work. Intent-only crashes remain
unresolved rather than guessing that dispatch was safe to repeat.

Capacity changes commit with proven readback. Native success, sold flags and
credits changes release no slots. After independent absence is confirmed,
OCCUPIED reservations become RELEASED and the next fresh Acquirer check may
resume enrollment. Pending resale/unresolved slots remain disjoint. Maintenance
does not change the coin ledger: sticky DRAINING still requires its existing
terminal-outcome and subsequent-cycle funds conditions.

Append-only SOLD_SETTLEMENT observations preserve exact physical item, sale
trade, observed gross price and read ID before deletion. Actual settled proceeds
and realized profit remain null with ACTUAL_SETTLED_PROCEEDS_UNPROVEN. A sold
currentBid, stored resale BIN, known acquisition cost, successful clear, 5% tax
projection or aggregate credits delta cannot establish an attributable net
receipt. The current native adapter exposes no per-sale receipt API; this task
does not invent one or report projected profit as realized. Tests include a known
actor-card cost/listing, a concurrent manual sale and unrelated balance changes.
Operator status now includes pending bulk and resale intents, and export/retain
preserve these events and unresolved records.

Behavioral coverage in `tests/test_00211_sold.py` includes automatic polling,
manual mixed inventories, durable native targets and independent survivors,
concurrent processes, missing acknowledgements, no-effect/partial clears,
incompatible readbacks, five real process-death boundaries, journal failures,
capacity pause/resume, sticky DRAINING, settlement non-attribution, operator
backup/export and actual CLI-to-broker execution. The broker test verifies
priority preemption and actual command-boundary pacing.

`tests/regression_00211.py` independently runs all current 001D and 002 item
1–11 Python suites plus bidding, bulk, watched, durability, diagnostics, market
pricing and integration regressions. It also runs the relevant native Node
contracts directly. `regressions.json` records every argv, exit status, elapsed
time and Python test count. This evidence is offline implementation verification,
not new live account proof.

Final verification on 2026-11-14 passed all 40 regression commands: 370 Python
tests across 27 independently executed suites and 13 direct Node checks. All
18 sold-maintenance tests and four artifact-check tests passed. The tracked
workspace diff passed `git diff --check`.

The initial broad run exposed older integration assumptions. The handoff test
now checks its historical route set against current routes while permitting
additive resale/bulk operations. The pricing timing test derives RTT from the
actual simulated network-command count, including the capacity inventory read.
Discovery tests accept supported configurable filters and still reject malformed
ones. The old consumed gate protocols retain their original runtime allowlists
and budgets: their unit tests isolate the later-added inventory dependency with
a separately captured, freshness-checked synthetic complete-pile prerequisite.
Current foundation/actor tests exercise the real inventory guard. No sealed
capture, consumed checkpoint or historical authorization was changed. The native
occupancy Node checker can also run without an optional evidence-output path.

`final-run-plan.json` prepares the item-12 procedure. It identifies the natural
rebid, leading/lost, win/list, status-gap, capacity, expiry, expired-relist,
sold-clear and attributable-settlement events; exact native APIs and routes;
one broker, priorities and request fanout; bounded worker cycles, a two-hour
watchdog and request ceiling/reserve; stop conditions; and sanitized evidence
collection. The operator must install deadline/request supervision before any
launch. Missing events remain LIVE-UNVERIFIED and require PARTIAL reporting.
The prepared procedure does not authorize or perform a live launch here.

Independent validators from the workspace:

| Command | Criteria (zero-based) |
| --- | --- |
| `python tests/test_00211_sold.py` | 0, 1, 2, 3 |
| `python tests/regression_00211.py` | 4 |
| `python tests/check_00211_artifacts.py` | 4, 5 |

The artifact checker validates the full recorded command inventory and bounded
plan against current runtime/native contracts. Negative cases reject missing
checks/events, failures, zero executed Python tests, live replay claims, excess
budgets, missing reserves, wrong routes/bulk arguments, priority drift, unbounded
launch commands and missing stop conditions. Mutable implementation files are
not pinned by hashes; sealed transaction evidence retains its integrity checks.

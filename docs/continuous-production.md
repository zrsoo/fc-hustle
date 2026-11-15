# Continuous FC27 PC production

Objective 003 uses `fc_access.continuous_v1`. This is a separate lifecycle over
the existing Acquirer, Bidder, TransferMaintenance, durable registry and shared
prioritized native broker. The finite `actors_v1.final_supervisor`, `final_series`
and consumed research checkpoints retain their original limits and counters.
Production has no wall lifetime, request-total, cycle-count or cumulative new
enrollment budget. The 50-slot safety limits continue to apply concurrently.

The locked production configuration is available without starting anything:

```powershell
python -m fc_access.continuous_v1 config
python -m fc_access.continuous_v1 status
```

The auction-only discovery filters are maxBid=1000 and minBuy=11000, with normal
three-page discovery and deduplication. Acquirer starts approximately every 600
seconds, Bidder every 25 seconds. Bidder/status work takes priority over discovery
and maintenance. Native operation slots are spaced by two seconds. Local native
helpers share serialization without spending an EA request slot. Native command
timeouts remain 30 seconds, bounded further by the actual auction expiry.

Exact-version pricing uses page 1/count 21, at most two searches and actual second
maxb=first_min. Default-template exclusions, no sorting/progressive probing or
undercut, X=500, 5% tax, legal native floored ceilings and smallest legal bids
remain. Completed quotes expire after 86400 seconds. Rebid only when genuinely
outbid. Keep the 5000-coin reserve and sticky DRAINING. Keep the separate unresolved
auction, complete occupied Transfer List and combined pipeline protections, each
50 slots, including manual, inactive, expired and sold-uncleared entries.

Ownership and actual paid-cost proof remain mandatory. Resale uses the stored
price, the native previous-tick starting bid and 3600-second listings. Account-wide
native bulk sold clear follows fresh detection, with an independent readback;
eligible expired bulk relist runs every 3660 seconds, preserving prices and
verifying actual duration. Independent readbacks include affected manual items.
Realized-profit accounting remains deferred.

## Launch and ownership

Complete offline validation, review, commit and push before live launch. Task
003-02 implements and tests this lifecycle only. Its results are OFFLINE; current
production live operation and stability remain LIVE-UNVERIFIED for 003-03/003-04.
The preserved baseline ghost reservation has no current identity mapping. Startup
must resolve it independently or remain gated; a missing watched row cannot be
converted to LOST and no guessed historical native ID may be used.

Keep the existing canonical journal `private-captures/final-remediation/foundation.sqlite3`
and its `completed-quotes.sqlite3` cache. Production supervision and its new native
mailbox live in `private-captures/continuous-production/`. Existing historical
mailboxes and request counters are never reset or reused as new production work.
Use the same context/account/persona/platform/namespace as the reviewed baseline.
The context file contains public local correlation labels only, never credentials.

Before changing runtime code or service ownership, issue stop, await every actor,
monitor and broker exit, inspect any in-flight intent, and preserve diagnostics.
Check the current process list and localhost service. An old read-only service
must be stopped and its exit awaited before starting its reviewed replacement
with the existing transport database and canonical journal authority:

```powershell
python -m fc_access.production_v1.server --database <existing-transport-database> --intent-database private-captures/final-remediation/foundation.sqlite3
python -m fc_access.continuous_v1 run --context <reviewed-public-context.json>
```

Run the supervisor as a persistent foreground process or a managed Windows service
with console windows hidden for background launch. Do not discard it when an AI
turn ends. The supervisor itself is persistent; no AI observer is its heartbeat.
Use the reviewed `browser/production-v1` Edge extension in the intended official
FC27 Web App. Reattach after a new owner epoch as required by the normal extension
UI. Ordinary saved-login recovery is authorized by AGENTS.md; CAPTCHA, two-factor
authentication, security challenges and missing credentials require the user.

After attachment, startup verifies that the service exposes the exact journal
authority and full peer fences. It issues paced fresh read-only reconciliation of
watched identities, balance, complete Transfer List and any required ownership or
pending-write readbacks. Only independently proven outcomes can settle old
intents. Existing reservations remain. Mutations are denied until READY.

`--state-dir`, `--journal`, `--cache` and `--port` support explicit isolated storage
or restoration. Recover must retain the prior durable paths and context; do not
select a new empty journal to evade commitments. OS locks protect the state
directory. An absent or unscoped journal is rejected before attachment or epoch
change. OS locks also protect the account across alternate paths/ports, canonical
journal, each actor and transport port. The port lock is shared with the finite
and standalone native executors. Before opening a replacement
run or epoch, recovery probes runtime locks and refuses while old owners remain.

## Status, stop and recovery

```powershell
python -m fc_access.continuous_v1 status
python -m fc_access.continuous_v1 stop
python -m fc_access.continuous_v1 recover --context <reviewed-public-context.json>
```

Use the same `--state-dir` before the action when selecting a nondefault runtime.
Status is read-only, does not attach Edge and creates no database. Stop appends an
operator request and gates new native dispatch. Allow up to 40 seconds for a finite
in-flight command and actor-side waits to settle; remaining owned children are then
terminated and their exits awaited. RUN_STOPPED includes verified child exits.
A forced exit preserves ambiguity; it does not cancel or retry an EA effect.
Readbacks requiring another native command wait for the next read-only recovery.
If a supervisor was killed, the watchdog and broker still gate its orphaned
children. Recover refuses while runtime locks remain held. Inspect retained gaps
and intents, await old exits, then use recover to create a new run and fenced epoch.
Repeated run against an existing production directory is rejected.

Recovery never requeues a CLAIMED or WAITING historical command. The shared broker
marks interrupted deliveries UNKNOWN and records the transition; only fresh,
independent reconciliation may settle effects. It never dispatches an old intent.
No automated restart/repair loop runs inside this lifecycle. Diagnose the incident,
fix and test code if needed, commit/push, and explicitly recover under the existing
authorization. Ordinary no-candidate/profit rejection, leading HOLD, cap stop,
terminal auction loss/expiry, legitimate reserve/capacity pause and empty
maintenance cycles are normal outcomes and do not request repair.

## Durable watchdog

`control.sqlite3` contains append-only run, heartbeat, intent/result, snapshot,
incident, stop and exit records. UPDATE and DELETE are rejected. Status projects
the latest records; previous segments and counters remain queryable by run ID.
SQLite uses WAL and FULL synchronous durability. Journal and native-mailbox rows
remain the independent write/response evidence. Source/test/configuration hashes
are never acceptance gates. Integrity checks on sealed native evidence remain.

The independent monitor reads local SQLite only, once per second. It tracks process
liveness, supervisor/monitor/executor and worker heartbeats, queue age/priority,
native responses and fanout, complete identity fences, freshness ages, coins,
all capacity components, DRAINING, reconciliation intents, actor progress,
maintenance and exceptions. This adds zero EA polls. Stale idle balance/capacity
observations are reported as stale; each actual strategy mutation still requires
fresh native reads at its existing authorization boundary.

Before each native dispatch, the broker checks the current run, stop state,
supervisor/monitor leases (10 seconds), context/fences, journal ownership and final
command deadline. The executor heartbeat can be occupied for the bounded native
timeout plus 10 seconds. Worker process heartbeats are distinct from cycle
progress, so a live heartbeat thread cannot conceal a stuck cycle. Restart cadence
waits are explicitly recorded as PROCESS_READY and do not create catch-up bursts.

Lost supervision records SUPERVISION_GAP and permanently gates that segment.
Healthy observed seconds include only adjacent successful monitor samples, at most
10 seconds apart, after READY; they are not wall time since launch. Recovery starts
a new healthy segment, preserving earlier uptime and request counts. An invariant,
schema failure, native timeout/unknown outcome, overdue reconciliation or process
exception requests a controlled stop with retained diagnostics. Exceptions retain
typed classifications, never arbitrary native exception bodies or authentication
data. Monitor exceptions also stop, and an independently stale monitor lease gates
the broker even if the monitor cannot write its own failure record.

Keep sufficient disk space for append-only records; no history pruning is performed.
After stopping all processes, retain consistent SQLite backups and the incident's
command, parsed response/readbacks, known/unknown effects, diagnosis, regression
results and new reconciliation. These records support later live assessment; an
offline double or old experiment cannot establish a new live outcome.

## Offline verification

```powershell
python tests/test_00302_continuous.py
python tests/run_00302_suites.py python
python tests/run_00302_suites.py node
python tests/run_00302_suites.py independent
python tests/check_00302_production.py
```

The first command uses accelerated clocks, native doubles, real SQLite, OS locks
and separate processes. It exceeds former execution ceilings, exercises owner
competition, both supervision deaths, ambiguous writes, deadlines, restart
reconciliation, stop/recover and normal outcomes. Existing pricing, admission,
capacity, resale and maintenance suites run in complete discovery. All Node
`*checks.cjs` suites exercise the shipped JavaScript, including unrelated browser
reads/telemetry, exact permitted post-list refresh and rejection of foreign writes.
The independent checker validates actual complete-suite outputs, criterion module
coverage, documentation, Git tracking and pushed ancestry. Use `--prepublication`
for review before commit; it explicitly reports PUBLICATION_PENDING.

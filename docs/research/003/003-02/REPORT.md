# 003-02 continuous production lifecycle review

The continuous lifecycle is implemented in `fc_access.continuous_v1`, using the
existing independent Acquirer, Bidder, maintenance and prioritized broker. This
review covers implementation and OFFLINE verification. Current live launch,
new strategy outcomes and healthy production hours remain LIVE-UNVERIFIED and
belong to subsequent Objective 003 work. No EA operation or browser recovery was
performed in this task. The existing read-only service remains the only live FC
service; the test processes use temporary SQLite and synthetic native pages.

The preserved Objective 002 verdict remains PARTIAL/NOT FULL PASS. Its consumed
windows, checkpoint budgets and counters are unchanged. The 003-01 ghost
reservation remains reserved: startup cannot enable production when fresh exact
identity mapping is unavailable. Missing watched coverage is not terminal proof.
There is no attempt to bypass that live prerequisite merely to test this task.

## Reviewed implementation

The research supervisor, bounded broker and finite series are retained. The new
production broker has no run wall deadline, request-total, cycle-count or new
enrollment budget. Its workers call the existing actor loops with no cycle limit.
Normal three-page discovery replaces the historical one-page run override only
in this new production lifecycle. The full production configuration is locked to
the established defaults, including every pricing, legality, reserve, capacity,
resale, maintenance, priority, pacing and timeout safeguard.

One foreground persistent supervisor starts a separate monitor, serialized broker
and three independent workers. Only the broker touches the native transport.
Journal, state-directory, actor and shared transport-port OS locks reject competing
owners before journal epoch changes. A recovery also probes existing runtime locks
before opening a replacement segment. Context, owner, epoch, host, document and
worker fences remain exact at enqueue and native dispatch. The shared broker now
also checks journal ownership and the command deadline immediately before send;
its optional dispatch gate leaves finite callers' lifecycle bounds unchanged.

Production defaults to the actual preserved journal at
`private-captures/final-remediation/foundation.sqlite3`, rather than the generic
Foundation default's absent path. Existing scoped context is required before
attachment; missing/empty replacements fail closed. Account-scoped locks also
exclude competitors using alternate journal/state paths and ports.

The service health response now reports its actual journal authority path, so
startup distinguishes extension attachment from a properly journal-backed service.
Fresh read-only startup independently reconciles commitments and pending effects;
no mutation can pass before READY. Unknown deliveries are never replayed. Stop
gates new dispatch, allows bounded in-flight work/actor waits to settle, then
terminates and awaits any remaining owned child. Recovery requires an explicit
action, retains the original durable paths/context and starts a new fenced segment.

The monitor reads SQLite only. It checks process liveness and heartbeats, queued
priorities/age, parsed native responses, source freshness, full identities,
coins/capacity, DRAINING, pending reconciliation, progress, maintenance and
exceptions. The broker independently requires fresh monitor/supervisor leases
before each dispatch. Supervision loss appends a gap and closes that segment;
observed healthy time counts only adjacent successful samples. Startup reads and
queued native work both contribute measured counters; unavailable responses stay
explicitly unknown. Typed/safe diagnostics exclude arbitrary native error bodies.

Control records reject UPDATE/DELETE. Existing mutable mailbox/journal projections
retain their immutable event trails, with no pruning or history reset. Lookup
indexes support ongoing control-record and priority-queue growth. No source, test
or configuration digest is enforced. Existing sealed native evidence integrity
checks remain in the complete regression suite and independent validators.

Review concentrated on startup/READY ordering, the final dispatch boundary,
supervision loss during an in-flight operation, competing ownership before attach,
restart reconciliation and scope preservation, command expiry, and normal outcomes.
The process regression found a restarted Acquirer cadence wait initially lacked
current-epoch progress evidence; PROCESS_READY now explicitly records that wait.
This correction was made offline before launch. Natural no-candidate/rejection,
HOLD, cap, loss, reserve/capacity pause and empty maintenance outcomes are data,
and never start an automatic repair loop. Faults require controlled stop and
reviewed recovery. Realized-profit accounting remains deferred.

## Verification and evidence

`python-suites.json`, `node-suites.json` and `independent-suites.json` retain exact
argv, exit codes, durations and output paths. The Python stdout/stderr includes
the complete discovered inventory and completion summary; every Node
`tests/*checks.cjs` suite has its own stdout/stderr. These are actual offline
execution receipts, not declarative proof of live behavior.

Initial prepublication verification passed **799 Python tests** in 320.636 seconds, **27 Node
suites**, and **five independent production/preservation validators**. The
independent prepublication assessment passed criteria 0–8 and explicitly reported
criterion 9 as PUBLICATION_PENDING. All fixture children exited. Publication is
verified separately against the actual remote branch after the commit and push.

The supervisor's subsequent recheck exposed a historical-review scope bug after
publication: the 003-01 validator applied its allowed paths through the current
HEAD, rejecting the legitimate 003-02 commit. See [repair-01](repair-01/REPORT.md)
and its retained failed outputs. Validation now checks the actual historical
review boundary and its ancestry, while retaining all historical evidence and
consumed-state protections. Four added regressions cover this post-commit case
and rejection cases. The current complete-suite receipts supersede the initial
verification above; no failure is promoted to PASS.

After repair, the supervisor's Python passed **803 tests** in 320.848 seconds,
all **27 Node suites**, and all **five independent validators**. The independent
prepublication assessment again passed criteria 0–8, with publication explicitly
pending. All fixture processes exited. The final assessment is rerun after the
repair commit is pushed, including the corrected historical baseline check.

The sustained clock test dispatches **2005** commands, over 8000 simulated seconds,
through the real production broker/mailbox. A separate test runs the real Acquirer
loop through that broker for **20** enrollments, each independently reconciled through Bidder, over
eleven thousand simulated seconds. Concurrent safety capacity remains 50.
The long clock workload uses NORMAL WAL in its temporary databases for speed;
production and the process/death tests retain FULL durability. Native effects
throughout these tests are synthetic and no result is presented as live proof.

Real subprocess checks exercise five separate owned children, competing starts,
durable operator stop, fresh fenced recover, cadence preservation, monitor death,
supervisor death and orphan exit. Clock and native doubles cover lease loss,
timeouts, malformed responses, expired commands, last-moment ownership changes,
missing identities, lost write responses, read-only startup, retained history,
normal outcomes, stale progress despite worker heartbeat and zero monitor EA polls.
The independent acceptance validator has negative tests for missing/failed/skipped
suites, absent behavioral modules, untracked/dirty implementation and unavailable
remote publication.

| Criterion | Behavioral/evidence coverage |
| --- | --- |
| 0 | Continuous broker sustained clock/requests; 20 Acquirer cycles/enrollments; bounded research negative cases; 003-01 unchanged history validator |
| 1 | Continuous production locked config/three-page deduplication/priority/spacing; existing 002-04 native actor contracts |
| 2 | 001d-04 pricing and 002-02 optimization: exact page/count/second maxb, exclusions, legal floor, cache TTL and negative requests |
| 3 | 002-04/05/06/07: minimum bids, native ticks/tax/X, true outbid, reserve/DRAINING, three independent slot limits/manual entries |
| 4 | 002-08/09/10/11: ownership/paid cost, stored price/previous tick, hour duration, account-wide clear/relist and independent readbacks |
| 5 | Continuous process locks/final send fences/deadlines/recovery; foundation and actor journal/transport tests |
| 6 | Continuous watchdog local metrics/leases/gaps/progress/identity/coin/capacity/intents and exception regressions |
| 7 | Clock and real process deaths, lost callbacks/restart reconciliation; Node bulk background and post-list refresh traffic contracts |
| 8 | Complete Python discovery; all 27 Node suites; five independent validators; offline/live vocabulary and receipt rejection checks |
| 9 | Operator guide, config/help/status/stop/recover tests; independent Git tracking and remote ancestry check after commit and push |

Independent production checks include the consumed sixth pricing gate/stop,
adapter-repair validator, bulk recovery validator and all six 003-01 preservation
criteria. They never rerun a live window. The original historical status remains
unchanged. Run `python tests/check_00302_production.py` for the independent current
acceptance assessment; `--prepublication` explicitly leaves publication pending.

## Operational handoff

See [continuous-production.md](../../../continuous-production.md) for configuration,
service authority/extension prerequisites, entry points, ownership, durable status,
stop, recovery and incident inspection. This task stops all fixture processes and
does not launch live production. Before live launch, the reviewed implementation,
tests, execution receipts and documentation must be committed and pushed; the final
validator checks the actual pushed Git ancestry, rather than trusting this report.
New production dispatch remains subject to current independent reconciliation of
the conservative ghost and any other fresh operational prerequisites.

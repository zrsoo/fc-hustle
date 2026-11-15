# Objective 003 — Continuous supervised production actors

## Authority and purpose

The user explicitly requests production-like continuous operation of the existing
FC27 PC Acquirer and Bidder: no artificial experiment time, request-count, cycle
or new-enrollment ceilings; monitor for issues; stop, diagnose, fix, test and
restart when issues occur; continue until the known operational conditions and
edge cases have genuine live coverage and the actors have run correctly for
several hours. Realized-profit tracking is explicitly deferred.

This objective implements and operates that instruction. Interpret “several
hours” as a minimum of **four consecutive healthy hours after the last runtime
fix**, not a maximum runtime or scheduled shutdown. No source/test/configuration
hash assertions are permitted. Behavioral tests and immutable native evidence
integrity checks remain required.

Repository/workspace: `C:\hustle\fc-hustle`, branch `main`.

This is a new operational authorization, not a replay or reset of an Objective
002 experiment. Keep `obj-29bea3b74eb3` / `002-12` BLOCKED with its historical
PARTIAL verdict. Do not recheck or run that objective concurrently. Objective
003 owns continued execution and does not depend on Objective 002 being marked
complete. Reuse its completed implementation, current durable state and verified
capabilities. Preserve all old windows, outcomes, consumed budgets and evidence.

Read `AGENTS.md`, Objective 002, the relevant production/actor modules, and these
handoff records before changes or live operation:

- `docs/research/002/002-12/review-05/REPORT.md` and `outcome.json`;
- `docs/research/002/002-12/series-selection.json`;
- `docs/research/002/002-12/blocker-repair-02/REPORT.md`;
- `docs/research/002-bulk-transfer-operations/REPORT.md`;
- `docs/research/002/002-03/attempts/20261114-adapter-repair-gate-06/REPORT.md`.

## Retained production rules

“No caps” removes the finite research harness's artificial execution ceilings.
It does not remove the strategy, account protections or per-command deadlines.
Keep the Objective 002 production configuration and behavior:

- Competitive auction acquisition only; no acquisition Buy Now.
- Discovery `maxBid=1000`, `minBuy=11000`; Acquirer cadence about 600 seconds;
  Bidder target about 25 seconds, with urgent Bidder work taking priority.
- Use normal production discovery pagination/deduplication. The implementation's
  production default is three discovery pages; do not inherit the last experiment's
  forced one-page override. Pricing remains a separate, strictly limited algorithm.
- Reuse production exact-version pricing: page 1/count 21, at most two pricing
  searches, actual second `maxb=first_min`, default-template exclusions, no
  sorting/progressive probes/undercut, completed cache TTL 86400 seconds.
- Keep estimated profitability controls: X=500 and the established 5% tax rule,
  native card limits/ticks, stored resale price and legal floored bid ceiling.
  Bid only the smallest legal amount; rebid only while genuinely outbid.
- Preserve the 5000-coin admission reserve/sticky DRAINING policy; do not lower
  it or spend deliberately to manufacture a DRAINING observation.
- Preserve all three 50-slot protections: unresolved queue, complete occupied
  Transfer List, and occupied + pending resale + unresolved reservations.
  Include manual, inactive, expired and sold-uncleared Transfer List entries.
- Keep exact physical-item ownership and paid-cost proof, stored-price resale,
  native previous-tick starting bid and 3600-second listings.
- Relist expired unsold items through one verified native bulk call every 3660
  seconds when eligible, preserving prices and verifying actual duration. Clear
  sold entries through one bulk call on fresh detection. Account-wide/manual-item
  effects and independent readbacks remain mandatory.
- One durable scoped registry/journal, one serialized prioritized native executor,
  existing production pacing (two seconds between native operation slots), full
  account/persona/platform/epoch fencing, fresh reads and no blind write retries.
- Keep per-command timeouts, expiry checks and failure handling. Open-ended actor
  lifetime does not permit an individual stuck request to run indefinitely.

Do not require net-sale receipts, realized-profit dashboards, settlement
accounting or realized-profit coverage for this objective. Preserve existing
transaction/cost records needed for ownership, reconciliation and evidence.
Never delete history or present projected profit as realized profit.

## Execution and monitoring contract

Create a production lifecycle separate from the consumed finite experiment
runner. Reuse actor/executor logic rather than copy a second trading engine.
Acquirer, Bidder and required maintenance must continue normal cycles with no
experiment-only wall deadline, native-request total, actor-cycle count or
12-new-enrollment ceiling. In particular, do not carry forward the old 1200-second
run limit, 2000-request research window or 7200-second cumulative experiment stop.
Old consumed counters remain intact; production counters continue truthfully in
new append-only records and are not reset to disguise previous use.

Require a persistent runtime monitor/watchdog, not occasional AI observation as
the only supervision. It must track process liveness, executor/monitor heartbeat,
queue age/priorities, native responses, freshness, exact identities, coin and
capacity invariants, intent/reconciliation state, maintenance outcomes and
unhandled exceptions. Monitoring itself must not add uncontrolled EA polling.
Record operator-visible status and supported stop/recovery controls.

Only one owner may run the actors. Use process locks and fenced epochs. Check for
existing processes before starting replacements; stop and await exits before
changing runtime code or executor ownership. Preserve current commitments through
restarts. If supervision cannot remain active, stop new live dispatch safely
rather than leave unmonitored account mutations running. Record the monitoring
gap; do not count it as healthy observed uptime.

Normal outcomes are not defects: no candidate, profit rejection, legal cap stop,
auction loss/expiry, legitimate capacity/reserve pause and empty maintenance
ticks should follow their intended behavior without a repair loop. An invariant
violation, unexpected request/schema behavior, broken scheduling, unhandled
exception, lost supervision or unresolved/ambiguous write requires a controlled
stop and retained diagnostics. Reconcile independently before any new mutation;
never replay a consumed or ambiguously executed command.

The user authorizes the stop–diagnose–fix–offline-test–restart loop for this new
objective. It does not require another permission request for each ordinary fix
or restart. Ordinary saved-login/browser/extension/service recovery follows
`AGENTS.md`, using the user's designated saved zzorniss account through normal
Edge UI. Do not read or export credentials or session data. CAPTCHA, 2FA, security
challenges and missing credentials remain human prerequisites. Do not bypass
restrictions or treat EA throttling as permission to evade pacing.

Every incident gets a unique record with the triggering command and evidence,
exact known/unknown account effects, root cause, fix, regression results and
restart reconciliation. Keep stopped segments sealed. Start a new healthy-uptime
segment after a runtime fix or supervision interruption; preserve all earlier
elapsed time, request counts and incidents. This uptime criterion is not a reset
of experiment budgets or historical outcomes.

## Ordered work

### 003-01 — Establish and preserve the current baseline

Verify there is no active competing actor/controller. Back up Git, working-tree
changes and consistent live SQLite state before modifications. The submission
handoff backup is `private-captures/003-handoff/20261115T151935Z/`; it includes a
Git bundle, binary tracked diff, untracked-file archive and five consistent
database backups. Inspect its manifest rather than assuming Git alone contains
all current work.

There are pending Objective 002 implementation/evidence changes from the last
orchestrator turn. Preserve them, establish provenance, independently rerun
relevant checks and commit/push that reviewed baseline separately before new
runtime changes. Do not discard, overwrite or silently include unrelated work.
Do not rewrite sealed reports to PASS. Reconcile current account state through
fresh official native reads before enabling mutations; yesterday's inventory,
balance, watched mappings and cache freshness are not current proof.

Acceptance: backed-up and reviewed baseline; exact context and current inventory/
commitments known; no duplicate processes or unresolved mutation bypass; all
pre-existing evidence preserved and provenance recorded.

### 003-02 — Implement the continuous lifecycle and deterministic watchdog

Replace experiment-only lifecycle limits for this new mode, retaining finite
research runners and their consumed checkpoints unchanged. Run the real independent
actors, shared prioritized executor and maintenance continuously. Implement
operator-visible status and stop controls, durable monitoring and safe recovery.

Add behavioral regressions for the absence of artificial lifetime/cycle/enrollment
ceilings, retained production limits, single ownership, watchdog failure, native
timeouts, ambiguous outcomes, restart reconciliation and background UI traffic.
Use offline clocks/doubles for long-duration and fault tests; never label them
live proof or introduce source-file hash gates. Run the complete Python suite,
all Node suites and appropriate independent production validators.

Acceptance: working continuous lifecycle; no inherited experiment ceiling; tested
watchdog and stop/recovery semantics; all applicable checks pass; documented
production configuration and entry points. Commit/push before live launch.

### 003-03 — Prepare the live evidence matrix and monitoring handoff

Create a finite, explicit matrix of known operational cases from Objective 002,
the production state machines and newly found defects. Include discovery and
pagination, fresh and cached pricing, native legality/admission, minimum initial
bids, leading HOLD, natural outbid/minimum rebid, cap stop, WON/LOST, physical
ownership, stored-price listing, sold clear, expired relist, occupancy/reservations,
capacity pause/resume, sticky DRAINING, priority/cadence, reconnect/restart,
uncertain-result reconciliation and unrelated browser activity.

Separate prior live proof, current revision behavioral checks and current run live
proof. Do not count old failed callbacks as new successful execution. Retain
unwitnessed cases as LIVE-UNVERIFIED. Realized-profit accounting is DEFERRED and
must not block this run.

Do not promise every possible unknown edge case can be proven by finite runtime.
Every newly discovered case joins the matrix and repair loop. Do not manufacture
wins, sales, outbids, reserve breaches or 50-slot saturation to fill the matrix.
Safe read-only lifecycle/reconnect checks may be performed at a quiescent point
after gating new writes and settling in-flight commands; they must preserve exact
native identity mappings and current commitments. No guessed historical native IDs.

Acceptance: auditable matrix, truthful status vocabulary, monitor/control handoff,
native evidence collection and independent assessment prepared before launch.

### 003-04 — Run, monitor, repair and continue

Start the actual production actors and required maintenance on authenticated
official FC27 PC under the reviewed production mode. Perform real strategy-led
trading and retain native evidence/readbacks. Monitor continuously through the
watchdog and review diagnostics; ordinary production operations are authorized.

Run without an artificial execution cap. If an issue occurs, stop safely,
preserve/reconcile its account effects, fix its cause, run meaningful offline
regressions, commit/push the fix and restart under a fresh fenced owner/healthy
segment. Do not restart unresolved writes or repeatedly replay an unknown command.

Reach at least four consecutive healthy monitored hours after the last runtime
fix. Four hours is a minimum stability milestone, not a scheduled stop. Continue
when required natural cases remain unwitnessed. Do not mark BLOCKED or terminate
solely because a healthy run has not naturally filled 50 slots, reached DRAINING,
won/sold a card or experienced another particular event yet. Record periodic
coverage and health snapshots. A genuine unavailable human prerequisite or
unresolvable external restriction may block, with exact evidence and safe state.

Acceptance: real production operation and honest live coverage; at least four
consecutive healthy monitored hours on the final revision; all required matrix
cases genuinely evidenced. Missing natural cases do not become simulated PASS.
Continue operating/monitoring rather than manufacture the case or claim completion.

### 003-05 — Independent assessment and operational handoff

Independently validate retained command/readback identities, strategy invariants,
durable state, native work priorities, incident history and monotonic healthy
uptime. Rerun appropriate complete offline checks after the final code change.
Publish `docs/research/003/REPORT.md`, live coverage matrix, incident reports,
configuration, process ownership and explicit stop/status commands; commit/push.

Realized-profit tracking is outside acceptance. Preserve Objective 002's original
PARTIAL verdicts; successful Objective 003 operation does not retroactively change
them or cause Objective 002 to launch a competing actor stack.

Only claim the explicitly evidenced cases and stability interval. Do not claim
universal absence of bugs. Keep production operation running beyond the milestone
only with a persistent, tested monitor and documented ownership/control handoff;
do not end supervision while silently leaving unmonitored actors running. If
that persistent handoff cannot be maintained, stop safely and report the actual
operational limitation rather than claim ongoing monitoring.

Acceptance: independent evidence assessment passes the stated scope, truthful
coverage and healthy uptime, retained production safeguards and history, no
duplicate controllers, reproducible report and an explicit supervised operational
handoff. Never label an unwitnessed required case LIVE-VERIFIED.

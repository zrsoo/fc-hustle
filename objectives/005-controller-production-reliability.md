# Objective 005 — Autonomous production repair and four-hour operational proof

## Original outcome and authority (preserve)

Workspace `C:/hustle/fc-hustle`, branch `main`. Make Objective 004's production
single controller work reliably end to end. Investigate every relevant layer,
implement root-cause fixes, run full behavioral regressions and genuine live
validation. Repeat monitor → safe stop on operational failure → diagnose → scope
and implement fix → test → reconcile actual account state → restart, autonomously.
Finish only after **four consecutive genuinely healthy operational hours after
the final fix/restart**, with independently retained evidence that acquisition,
confirmed bids, management and resale actually work. Leave the healthy watchdog
and controller running. A heartbeat, an HTTP response or four hours of failed or
idle acquisition loops is not success.

The user explicitly authorized this new objective on 2026-11-17, including live
EA requests, browser interaction/recovery, test bids, rebids, genuine won-card
resale and maintenance needed to establish the intended full production flow.
No additional artificial experiment budget or elapsed-time cap is imposed.
Record finite experiments and irreversible intents individually. Never blindly
retry uncertain transactions or forge outcomes. Use actual account evidence.
No source-file integrity assertions, weakened functional tests or rewritten
historical evidence. Do not bypass EA challenges or extract authentication data.

This objective supersedes Objective 004's restriction against an integrated live
run for this NEW objective only. Keep Objective 003 `obj-da182a175410` PAUSED,
Objective 004 `obj-fefda5e912eb` COMPLETED, and every historical Objective 002/003
verdict/checkpoint unchanged. Do not resume legacy actors or submit duplicates.

Use the installed orchestrator's `--autonomous --healthy-seconds 14400` mode.
Keep one durable task/session and update the working plan and progress sections
below throughout investigation. The original outcome and strategy cannot be
weakened by edits. Ordinary implementation defects, authentication recovery,
failed probes, actor stops, uncertain bids, expired/lost auctions and unresolved
hypotheses require continued engineering, not manual recheck. Genuine external
barriers such as EA security challenges/account restrictions or verified absent
desktop access must be evidenced and independently reassessed before escalation.
Never invent a user prerequisite to terminate an inconvenient investigation.
Market waiting is not itself an engineering blocker; continue safely monitoring
until required behavior can be observed. A real external condition cannot be
guaranteed away, and its evidence must not be fabricated.

## Read and preserve before work

- `AGENTS.md` (reread before browser recovery); normal saved sign-in is already
  authorized for the intended **zzorniss** account in official Edge FC27 PC.
- `objectives/ 004-single-controller-implementation.md`, especially strategy,
  execution, journal and resale contracts; `fc_access/controller_v1/README.md`
  and `DESIGN.md`, watchdog, controller, executor, adapter and store.
- `objectives/002-two-actor-competitive-bidding.md`,
  `docs/research/002-bulk-transfer-operations/REPORT.md`,
  `docs/research/001d/001d-07/REPORT.md` as historical reusable context.
- `docs/research/003/003-04/bid-receipt-repair-01/REPORT.md`,
  `docs/research/003/003-04/production-06/REPORT.md`,
  `docs/research/003/003-04/production-07/REPORT.md`.
- `docs/research/ 004/watchdog/REPORT.md`,
  `docs/research/ 004/bridge-audit/REPORT.md`,
  `docs/research/ 004/request-ownership-fix/native-followup-contract.json`,
  current `fc_access/production_v1/extension/page.js` and its ownership tests.
- `C:/hustle/agent-orchestrator/docs/autonomous-operations.md` for exact monitoring,
  scheduler-owned launch, repair and quota handoff contracts.

Inspect Git, actual process/port ownership, current SQLite schemas and browser
state. Existing FC HEAD at submission preparation: `fa266a3`; changes include
the request-ownership repair committed by the user, whose live integration is
not yet proven. Do not assume the repair caused or solved the failures.

Verified quiescent backup: outside Git under
`C:/hustle/orchestrator-migration-evidence/autonomous-20261117T003234Z/`:
`state.db`, `controller.sqlite`, `quotes.sqlite`, all integrity/FK checked and
every table compared row-for-row. No production Python controller or scheduler
was active then. Before each migration/repair establish current quiescence and
create a fresh backup as needed. Git alone does not back up runtime state.

Existing production DB `private-captures/controller-v1/controller.sqlite` had:
302 commands, 905 events, 41 policy batches, 19 candidates/attempts/tombstones,
zero managed members, 61 metrics. Quote DB had ten completed quotes. Inspect
narrow sanitized projections; preserve this original failure evidence.

## Observed incident to explain with actual evidence

November 16 production attached to Edge, RUNNING/ACQUIRING; 41 acquisition
batches: 35 READ_FAILED, four OPERATION_FAILED, two SETTLED. Nineteen initial
bids were all UNKNOWN with zero confirmed managed auctions. Twelve classified
ambiguous_network (native HTTP 461 vs service-layer 403); seven service_failed
HTTP 401. Balance reads: thirty 401, six 200. Extension frequently WAIT. Watchdog
reported healthy progress despite the persistent failures.

Treat these as observations, not a predetermined diagnosis. Correlate each
logical invocation, native request/response, service outcome, real EA readback,
account/persona/document epoch and durable intent. Explain where status codes
are translated and what each signifies in the loaded FC27 client. Distinguish
explicit rejection, authentication failure, uncertain dispatch, receipt evidence
and independently confirmed account ownership. ACK alone must never fabricate a
successful bid. Investigate native caches, queued requests/follow-ups, ownership
attribution, auth/session changes, extension WAIT and service scheduling.

Prior balance repair `9ba0c8e` parsed native currency VO `data.coins.value()` and
matched its same owned GET's COINS funds. Ownership changes in `fa266a3` scope
native DAO queue/send lineage and explicit callback follow-ups. Review their
actual behavior and all required controller operations, not source hashes.
Historical native captures may be inspected as public method projections;
never read or retain credentials, cookies, authentication headers/tokens or EA
session identifiers. Keep layer-specific sanitized status/identity evidence.

## Strategy and safety invariants

Preserve the agreed single sequential controller: ACQUIRING and MANAGING never
overlap; no independent legacy Acquirer/Bidder. Existing entry balance threshold
strictly greater than configurable 40,000 once per batch; at most ten initial
acquisition attempts; candidate discovery maxBid=1000, minBuy=11000; more than
60 seconds remaining; exact-version production pricing, native price limits and
increments, existing fee/profit ceilings, completed 24-hour quote cache. Do not
change these to manufacture successful bids or wins. Management target every
five seconds, nonoverlapping, immediately due again after a longer cycle.

Confirm actual bids through independent fresh native account/auction evidence,
hand off only confirmed membership. Normal competition/rejection/outbid/loss,
empty batches, insufficient entry balance and individual ambiguous results are
not global blockers. Persist ambiguous action evidence and do not blindly replay
it or enroll an unconfirmed bid. Reconcile against genuine current account state;
expired historical mappings are not a prerequisite to continue safe new work.
Persistent operational failure (e.g. repeated authentication failures, no usable
native reads, writes never confirm, ownership faults, missing diagnostics or
wedged work) MUST stop trading promptly for autonomous engineering repair.

Only resell genuinely owned won items after exact identity/ownership/paid-price
confirmation, through existing profitable resale rules and one-hour listings.
Do not move/list unrelated manually owned cards. Bulk maintenance affects all
eligible account entries under the already authorized native bulk contract;
reconcile exact results and preserve existing prices and one-hour relist duration.
No duplicate controller, duplicate command dispatch, blind bid replay, silent
unbounded retries against EA errors or unsafe process/PID-only termination.

## Engineering and monitoring workflow

1. Preserve initial incident state/evidence; reproduce faults with targeted live
   native operations. Diagnose auth, identity, native/wire/status translation,
   transport/ownership, admission, confirmation and journal issues completely.
2. Scope each evidenced fix in the plan below; implement and test negative and
   recovery cases. Refactor components if needed; reuse valid infrastructure.
   Full Python and relevant Node/JS regressions must pass. Never skip failing
   checks merely for green output; distinguish obsolete historical contracts
   from production behavior without rewriting sealed evidence.
3. Improve semantic watchdog detection and a bounded deterministic operational
   health/stop interface. Report meaningful states (STARTING, operational phase,
   RECOVERING, STOPPED with exact reason) and run identity. Define tested failure
   streak/time/freshness criteria from actual policies, allowing ordinary market
   outcomes. A process heartbeat or completed failing loop is insufficient.
4. Use the orchestrator's scheduler-owned `service` handoff to launch the
   watchdog outside Codex's ephemeral process tree. Provide an exclusive runtime
   lock, restart-readable ownership, idempotent ownership-checked stop, startup
   grace and health JSON/interval <=60s. Do not launch persistent processes as
   ordinary provider/tool children. Runtime must survive quota/provider cleanup.
5. Return `monitoring`; orchestrator checks health without AI quota. On a fault,
   stop this runtime safely, preserve diagnostic timing/intents/readbacks, and
   automatically resume this same worker for repair. Update the plan and
   hypothesis log; implement, regress, reconcile and restart with a new run ID.
   Repeat without requiring the operator to diagnose or trigger recheck.
6. Quota exhaustion waits for authoritative quota recovery automatically. A
   healthy watchdog/controller continues; a broken one remains safely stopped
   until the saved worker resumes. Do not change providers, reset counters,
   clone the objective or manufacture unavailable AI capacity. Preserve exact
   resumable next actions before each handoff and commit completed stages.
7. After the final restart, retain at least 14,400 consecutive seconds of valid
   semantic health samples and genuine trading evidence. Any further defect,
   stop, restart or monitored-health discontinuity resets this interval; preserve
   prior intervals and repairs as historical evidence. Independently audit the
   entire final interval and outcomes before returning done. Leave it running.

The objective file is the mutable working plan beneath its preserved original
requirements. No need to create a replacement objective/DAG for each discovered
bug. The installed orchestrator owns durable scheduling, quota waits and repair
assessment. Do not recursively launch a second scheduler or run SQL edits against
the live orchestrator DB to bypass its lifecycle. Improve generic orchestrator
code only if a verified orchestration defect actually prevents this authorized
workflow; preserve its independence and validate isolated fixtures before any
safe service deployment. FC and orchestrator changes are committed/pushed in
their respective repositories.

## Required deliverables and completion

Create `docs/research/005/REPORT.md` and sanitized, independently verifiable
evidence. Include:

- Root causes for every observed failure class, exact diagnostic chain and fixes.
- Behavioral regression commands/counts/results and any genuine unresolved issue.
- Real native/wire/service/account readback evidence for confirmed acquisition,
  management/rebid where competition permits, terminal settlement, genuine won
  item ownership/move/resale listing and maintenance when eligible. Distinguish
  confirmed live behavior from synthetic tests and behavior not yet observed.
- Every stop/fix/restart, durable unknown outcomes and how actual evidence
  resolved or safely isolated them. Do not assume UNKNOWN bids failed or passed.
- Final runtime ID/PID/owner, monotonic four-hour interval, semantic samples,
  valid outcomes/error counts, persisted restart-readable state and independent
  acceptance validator. No PASS for life-only, no-success or failed-read loops.
- Exact PowerShell instructions to launch corrected controller under watchdog,
  inspect current status, stop it safely and resume this existing objective.
- Git commits pushed to `main`, including tests, fixes, report and reusable
  monitoring/recovery harnesses; no credentials or raw provider/session data.

Success requires all of the above, at least four consecutive healthy hours and
real end-to-end production behavior. If a market event has not happened yet,
continue monitoring instead of claiming coverage. If a verified external barrier
prevents completion, record the safe state, evidence, attempted alternatives,
remaining safe actions and exact missing prerequisite for recovery assessment.

## Working plan (update autonomously)

- [ ] Preserve/inspect initial incident; correlate all failure classes.
- [ ] Reproduce and fix root causes with regressions and genuine contract checks.
- [x] Implement semantic watchdog/ownership/health/stop integration; verify it.
- [ ] Run genuine lifecycle, diagnose and repair each incident automatically.
- [ ] Prove final four-hour interval and intended trading/resale behavior.
- [ ] Independent audit, final report, commit/push, leave healthy runtime running.

## Progress and next action (update before handoffs)

Stage 06 repair in progress (2026-11-17), published starting main `92f0b6f`.
Scheduler generation 26407ef02dc7d322407f4c575c0c7ac7 attached automatically and
reconciled the prior 750 bid as LOST through fresh native account evidence.
Its next normal acquisition batch genuinely confirmed TEN initial bids, followed
by successful genuine rebids. One exact item (definition 251852) was independently
verified WON at our paid 3100 and moved once, with fresh exact transfer-list and
unassigned readback confirming the move. No list intent was created. Later fresh
transfer-list reads omit that item; neither disappearance nor ACK authorizes a
repeat move or a listing. Ownership/location investigation remains open.

The scheduler stopped this generation after RUNTIME_STATE_UNAVAILABLE, despite
166 native successes and zero semantic failure streaks in the final persisted
snapshot. Stop was cooperative, exit zero, no forced termination. The original
I/O exception was not retained; a reproducible Windows sharing test demonstrates
an ordinary reader can deny atomic replacement (winerror 5). Runtime reads now
share delete access, Windows publication uses ReplaceFileW, local replacement
retries are bounded to 0.5 seconds, and health retries transient manifest access
for at most two seconds. Typed safe I/O diagnostics now survive future failures.
Nine focused ownership, failure and real Windows I/O tests pass. Full discovery
passed 1111 Python executions with zero failures/errors/skips in 494.890 seconds;
all 37 Node suites and nine serial independent validators pass. Stage06's audit
reparses all 305 actual results, verifies ten initial bids and TEN competitive
rebids, paid win/move/stop/reset, and rejects four altered evidence cases.
Both full acceptance validators correctly return INCOMPLETE; their eight-case
self-tests also pass. No completion or healthy interval is claimed.

All 31 earlier UNKNOWN initial attempts stay consumed. Trading is stopped and
healthy consecutive seconds are ZERO. Stage06 backup outside Git was made under
canonical locks with integrity/FK/row equality checks. A distinct zero-write
window at epoch 10 obtained fresh watched, transfer-list and unassigned reads;
its exact target status was refused locally (known_identity_unavailable) because
the new fence cleared that target's selector. No fourth native request or write
was inferred. The window is consumed, evidence preserved in stage06/win-read-01.

Next: commit/push the verified Windows publication repair and stage06 evidence.
Then reproduce/test post-move recovery when the native watched endpoint removes
the claimed auction: the current work contract incorrectly demands a NEW watched
terminal win before listing, and current peer checks reject old terminal proofs
after restart. Scope a persisted exact terminal/paid-bid evidence chain combined
with independently fresh physical ownership/caps, without granting authority from
ACK or stale inventory. Investigate the missing moved item's native selector and
location without replaying its move. Reconcile the actual binding epoch before
a NEW scheduler-owned generation (the isolated read window consumed epoch 10,
while production DB last held 9). Continue autonomous engineering and genuine
resale validation. No external blocker or human prerequisite is established.
Require the entire lifecycle and 14400 consecutive healthy monitored seconds
AFTER the final fix/restart, independent acceptance, pushed main and live healthy
service. Original requirements and historical objective verdicts are unchanged.

## Hypotheses, actions and results (append with evidence)

2026-11-17 H1 / VERIFIED: original watchdog only bounded work progress; handled
operational failure supplied continuing progress. Added pure semantic policy and
outcome messages, with real stopped-worker and retained-incident replay tests.
Production health/service integration is still pending, so no readiness claim.

2026-11-17 H2 / STATUS TRANSLATION VERIFIED, SERVER DENIAL CAUSE OPEN: captured
public FC27 native methods map PERMISSION_DENIED=461 to service HTTP403 while
retaining native error.code461. The bridge's equality check produces
ambiguous_network for that legitimate client translation. Captured function
behavior reproduces this offline. This does not establish why EA denied twelve
specific bid requests, an account restriction or a successful/failed account
effect. All nineteen historical unknown writes remain unchanged and consumed.

2026-11-17 H3 / CURRENT READ PATH VERIFIED, HISTORICAL AUTH TRANSITION OPEN:
fresh current-persona/native balance, watched, full inventory, unassigned,
discovery (with owned metadata follow-up) and exact ten-target status all passed.
Seven historical bids and thirty balance reads returned401. Current read success
shows no current read-only auth barrier; write behavior still needs genuine
validation after current extension reload. WAIT provenance remains open because
the controller service discards worker diagnostics; preserve typed diagnostics
before the next write probe. No security or saved-authentication values accessed.


2026-11-17 H4 / VERIFIED ENGINEERING REPAIRS: real controller fixtures reproduce
successful caps reads masking persistent failed local helpers; three helper
failures now stop without treating successful helpers as native freshness.
Controller diagnostics were discarded; they are now strictly validated and
retained append-only, and missing diagnostics stop after three operations.
Actual bid-03 retains EA_RESPONSE 461 followed by NATIVE_CALLBACK 403/false.

2026-11-17 H5 / LOCAL OWNERSHIP CONTRACT VERIFIED OFFLINE, DEPLOYMENT PENDING:
`fc_access.controller_v1.operational` implements an exclusive owner lock,
consumed generation, process creation identities, atomic state, strict semantic
health JSON and idempotent generation-bound stop. Finite real-process fixtures
verify duplicate/stale ownership refusal, parent death/child lease withdrawal,
state-write failure and semantic stops. No production runtime generation exists.

2026-11-17 H6 / STALE-PRICE-COMPETITION HYPOTHESIS OPEN: the fresh document still
returned 461 for a minimum 850 bid based on discovery current 800 aged 42.019s.
Independent status two seconds later showed 900 and no account participation.
This does not prove when the competitive change happened or the exact denial
cause. Next: a separately journaled fresh exact-status-before-bid experiment,
with unchanged pricing/filters/cap, no replay of unknown 17bcb5a360204fbfee2fd7a766771d62.

2026-11-17 H7 / BROWSER RECOVERY VERIFIED: temporary input-thread attachment
recovers foreground; a popup is allowed only through the exact intended root
owner. Reusing an existing Extensions menu avoids closing it by toggling. Two
failed attachment windows had zero native dispatch; distinct bid-03 attached
successfully after extension reload/document refresh. No auth values accessed.

2026-11-17 H8 / CONFIRMED ACQUISITION, STALE-SELECTION CONTRIBUTION SUPPORTED:
New finite fresh-bid-01 obtained exact current status after pricing, then bid 700
with unchanged cap 4100/resale 4900. Wire200/native success and exact receipt
matched physical/full-version target. Separate later exact status and watched
both showed highest/current700. This disproves a blanket inability to bid in
this document/account epoch; it does not establish the precise cause of every
historical461. Production refreshes all eligible targets once before intent.
New negative/recovery tests preserve all original strategy constraints.

2026-11-17 H9 / MONITOR CALLBACK FAIL-CLOSED VERIFIED: result callback exceptions
previously could be swallowed by policy handling. Executor now latches admission,
supervision receives RESULT_MONITOR_FAILED and typed exception only, and a
second request is rejected before native dispatch. Successful live experiment
retains all 99 callbacks; no missing-result tolerance or fabricated health added.

2026-11-17 H10 / QUOTA INTERRUPTION RECONCILED: no service launched before quota
interruption. On resumption, full fresh regression passed 1106; separate process
capture and canonical locks show quiescence. Existing confirmed member remains
ACTIVE locally, account outcome unknown until fresh native read. Preserved its
intent/proof and all 20 UNKNOWN bids. Prepared new scheduler launch only; no
ordinary provider-child persistent processes or duplicate writes.

2026-11-17 H11 / STARTUP MANIFEST RACE VERIFIED AND REPAIRED: scheduler first health
ran before service initialization published its state. It correctly failed closed
and cooperatively stopped the newly owned runtime; native dispatch count and
journal delta were both zero. Health now waits boundedly for real requested-gen
state instead of racing its first atomic publication. Absent state never becomes
starting/healthy and scheduler grace cannot be extended. Six real-process tests
and the full 1107-execution regression pass. Preserve the consumed failed launch;
next attempt must use a new deliberate generation, never replay its service ID.

2026-11-17 H12 / SEMANTIC STOP AND GENUINE MAINTENANCE VERIFIED LIVE:
Second scheduler generation completed real relist_all and exact readback; old
confirmed 700 settled LOST through fresh native status. Three initial native bids
then returned 461/service403 and caused prompt cooperative semantic stop. Seven
remaining intents were consumed without dispatch. Fresh selection alone does not
explain/fix all denial cases. Preserve all outcomes; no restriction inferred.

2026-11-17 H13 / CURRENT WIRE-CALLBACK COHERENCE VERIFIED, PRIOR CASES OPEN:
Typed diagnostics compare only allowlisted auction numbers/states and boolean
identity/coherence, never raw response bodies or authentication fields. Ten
read-only targets and new bid pre-status matched wire exactly. New750 probe
succeeded after ordinary saved sign-in recovery. This falsifies a blanket current
write barrier and stale-callback claim for these captures, not for uncaptured
historical wire payloads. Exact server reasons for the three 461 remain open.

2026-11-17 H14 / BETWEEN-COMMAND DIAGNOSTIC GAP REPAIRED:
The 800 intent had no claim/tombstone/native result. Old worker dropped failures
when active=null after ACK. It now records typed poll phase/reason against last
acknowledged scope; stale scopes still fail existing server fencing. Fake error
canaries are not retained; no execution/result replay was added. Read-only idle
polling passed 25s. Missing claim remains an unresolved hypothesis, not success,
explicit rejection, account restriction or manual prerequisite.

2026-11-17 stage06: ten genuine initial confirmations and subsequent rebids;
paid 3100 terminal win and one confirmed move; no listing. Later inventory omits
that item. Isolated readonly epoch10 cannot resolve its old selector and makes no
writes. Scheduler I/O fault stopped otherwise semantically healthy generation;
Windows file-sharing mechanism reproduced, bounded replacement/read repair has
nine passing focused tests. Exact original I/O exception and missing item cause
remain unproven. Full 1111 Python / 37 Node / nine independent checks passed;
stage06 evidence audit rejects four corruptions. Publish, then repair/test safe
post-move terminal-proof and selector recovery. Both full acceptances remain false.

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
- `objectives/004-single-controller-implementation.md`, especially strategy,
  execution, journal and resale contracts; `fc_access/controller_v1/README.md`
  and `DESIGN.md`, watchdog, controller, executor, adapter and store.
- `objectives/002-two-actor-competitive-bidding.md`,
  `docs/research/002-bulk-transfer-operations/REPORT.md`,
  `docs/research/001d/001d-07/REPORT.md` as historical reusable context.
- `docs/research/003/003-04/bid-receipt-repair-01/REPORT.md`,
  `docs/research/003/003-04/production-06/REPORT.md`,
  `docs/research/003/003-04/production-07/REPORT.md`.
- `docs/research/004/watchdog/REPORT.md`,
  `docs/research/004/bridge-audit/REPORT.md`,
  `docs/research/004/request-ownership-fix/native-followup-contract.json`,
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
- [ ] Implement semantic watchdog/ownership/health/stop integration; verify it.
- [ ] Run genuine lifecycle, diagnose and repair each incident automatically.
- [ ] Prove final four-hour interval and intended trading/resale behavior.
- [ ] Independent audit, final report, commit/push, leave healthy runtime running.

## Progress and next action (update before handoffs)

Stage 01, 2026-11-17: preserved the actual 302-command/905-event incident and all
19 UNKNOWN attempts without changing production DBs. Fresh quiescent backups,
integrity/FK checks and row-for-row comparisons are recorded under
`docs/research/005/incident-20261117T010101301454Z/backup.json` (earlier additive
projection/backup also retained). Starting main was `972c01e`, clean. Current
source extension path is `browser/production-v1/`, not the nonexistent extension
path in the input's preparation notes.

Actual finite read-02 window: six native commands, seven authenticated HTTP200
GETs (including discovery metadata), zero mutations, 63702 coins, empty watched
and unassigned sets, five active complete Transfer List entries, 21 discovery
rows, ten exact status targets/rows/full-version links, no missing rows. The
probe closed with no pending commands; it does not prove new-controller wins or
resolve old unknowns. This worker verified official Edge foreground/UI control;
no security challenge or missing credentials were encountered. Read-01's setup
timeout-parameter failure is separately retained and was not reset/replayed.

Implemented semantic outcome monitoring in the existing watchdog and real native
boundary, plus post-readback batch results. Tests prove repeated 401, failed reads,
failed writes, handled failed batches, all-missing managed status, missing native
freshness and repeated unconfirmed acquisition stop rather than remaining healthy
on progress. Single uncertainty and ordinary market outcomes remain non-blocking.
Retained incident replay stops at the third 461 bid, before the later auth storm.
Seventeen focused semantic tests and five evidence tests pass. Final full Python
discovery passed 1088 executions, zero failures/errors/skips, 475.429 seconds;
all 36 Node suites and all nine final independent commands passed. Complete
receipts are in `docs/research/005/checks/stage01/`. The first independent batch
had canonical-lock contention with discovery; its serial rerun exposed one
scheduler no-op audit addition, corrected behaviorally as described below.
Both failed batches remain retained. No original historical evidence was changed.

Next concrete actions: retain controller
diagnostic POSTs with strict sanitization; verify native current-code write/status
and authentication/identity behavior in a new finite, durable-intent window,
without replaying any unknown. Implement tested exclusive scheduler-owned runtime
lock, restart-readable generation/ownership and bounded semantic health/stop JSON.
Then reconcile actual account state and use the SAME task's service handoff for
production launch. No persistent service has been launched, no external blocker
is proposed and healthy operational seconds remain zero. Full live lifecycle and
the consecutive 14400-second interval remain required. Report:
`docs/research/005/REPORT.md`; independent stage-only audit:
`python tests/check_005_stage01.py` (explicitly not objective acceptance).

Additional serial-audit finding: the scheduler appended one no-op transition
event 594021 for paused 003-04 (RECONCILING to RECONCILING, null diagnostic, no
turn). Every original historical row and checkpoint is unchanged. The archival
checker now validates that precise append-only no-op rather than rejecting all
audit additions, with negative tests for real activity, deletions and state edits.
All nine independent validators pass in `checks/stage01/independent-final` and all
36 Node suites pass in `node-final`; final full Python discovery passes 1088
executions in `python-final`. Stage01 publication title:
`Preserve Objective 005 incident and stop persistent controller failures`.

Inspection follow-up for the next repair stage: local price_helpers are correctly
excluded from native freshness, but stage01 currently ignores their failure
streak too. Reproduce/add a separate typed helper-failure stop without counting
successful local helpers as EA freshness; otherwise caps/read successes could
mask repeated helper failures as empty acquisition. Address before any production
launch. Full remaining integration contract is `docs/research/005/runtime-plan.md`.

Before further browser actions, add a reusable verified foreground fallback:
ordinary helper calls later failed `Edge_foreground_control_failed`, but this
worker's temporary AttachThreadInput + restore/BringWindowToTop/SetForegroundWindow
call verified the intended official Edge foreground successfully with no keyboard
or mouse input (`desktop-focus-recovery.json`). Separate unmodified helper calls
still lack that fallback. No desktop-access blocker is established. A newly
observed scheduled FC-005 orchestrator review task is not an FC actor and was not
modified by this worker. Keep ownership checks current; do not launch duplicates.

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

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

Stage 11 repair complete; publication and new scheduler launch next. Starting
published main f10695f. The prior generation stopped cooperatively at 11:47:35 UTC
after 274 successful native operations and four confirmed competitive rebids
(1600, 1800, 2000, 2200). Native status independently settled the member LOST at
4900, above stored cap 4300. Successful balance200 was followed within seconds by
search401 and balance401 without account/document/owner change; the second auth
failure caused immediate stop. One earlier callback200 with no owned request
remains UNKNOWN/unusable; its exact source is unproven. Scheduler peak was
621.70 healthy seconds / 22 samples, then ZERO. The complete stopped run and
quiescent integrity/FK/row-equal backups are retained under stage11. All 41 UNKNOWN
intents are consumed, no active member remains, and no native crash recurred.

Reproduced root defect: the bridge disabled ordinary native renewal for every
read. Current public native _handleFail/_handleReauth/handleTelemetry show that
an enabled native renewal with doRetry=false reports the original 401 unchanged
and permits a later independently journaled read to recover. Pure reads now
preserve only an already-enabled native renewal flag; automatic retries and all
mutation lineage renewals remain disabled. A native opt-out is never enabled.
NATIVE_RENEWAL_RESULT retains only the actual UTAS completion's success boolean;
non-UTAS notifications, authentication data and exception values are not retained.
Original 401 trigger and exact historical 461 server reasons remain unproven;
this repair addresses failed-read persistence without inventing those causes.

Final regressions PASS: 1121 Python test executions, 39 Node suites, nine
independent commands. Eleven renewal cases cover original failure retention,
next-read recovery, native opt-out, renewal failure, no replay/mutation renewal,
callback restoration, privacy and unrelated-environment false-success rejection.
Captured stage11 audit verifies all four rebids/loss, actual auth transition and
prompt stop, and rejects four corruptions including promotion of an unowned
callback. Two finite genuine read-only windows each passed six commands and ten
exact targets, zero missing, zero mutations/pending work, and closed cleanly.
The final window followed extension/page reload with the complete repair.
These baselines do not prove a LIVE expiry-and-renewal event or four healthy hours.

Normal official UI recovery used the designated saved account through autofill
and standard controls; no credential value or EA session identifier was read.
No challenge or external restriction was observed. Fresh pre-service backup and
ownership checks follow before the scheduler-only launch. Production DB epoch
remains 17; last finite read-only native owner epoch is 19, so the next runtime
must use epoch floor 20 and a NEW generation. Safe journal: 38 ACKNOWLEDGED,
41 UNKNOWN, 20 LOST, one WON_ACCOUNTED, no active member or pending command.
Prepared unused generation 718d2acbcab1b4d9cdcb75d7e0035b70, service ID
005-native-read-renewal-718d2acbcab1b4d9cdcb75d7e0035b70, epoch floor 20, is retained in stage11/launch-intent.json.
Fresh pre-service backup, quiescence and official browser projections passed.
Objective 003 remains PAUSED and Objective 004 COMPLETED, independently read-only
verified. Next: publish this complete stage, launch once through the existing
scheduler, immediately verify attachment/current account reconciliation and
original-policy trading. Observe genuine renewal metadata/read recovery if expiry
occurs. Keep repairing actual failures; any stop/restart/gap resets the final
interval. Require full genuine final-generation lifecycle and 14400 consecutive
semantic healthy seconds before done. No manual prerequisite or external blocker
is established.

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

2026-11-17 stage07: reproduced claimed-watch disappearance and restart listing
failure; repaired retained provenance versus fresh physical authority separation.
Added bounded read-only selector recovery and safe pile diagnostic categories.
Focused Python/Node and actual retained-chain negative audits pass. Current live
location is now independently confirmed by full transfer inventory and owned GET;
resale and four-hour proof remain outstanding. Final 1117 Python / 38 Node / nine
independent checks pass. Publish and launch the prepared unique scheduler service,
verify actual recovered listing/new lifecycle, then continue semantic monitoring.

2026-11-17 stage08: genuine recovered one-hour listing and relist confirmed;
eight new initial bids and three competitive rebids independently confirmed.
One policy UNKNOWN preserved despite subsequent native confirmation. Child died
with0xC0000005; interval reset. Actual shared store wrong-row race reproduced,
cache disabled, 147634 correct concurrent reads passed. Exact original crash C
stack missing; matching upstream mechanism is evidenced, future safe fault traces
installed. Continue full regressions/reconciliation/restart, never manual recheck.

2026-11-17 stage08 final audit: the separately retained complete 220-delivery
capture adds the fourth competitive rebid after the unchanged successful prefix.
All eight initials and four rebids have independent later native participation;
the one original UNKNOWN remains unchanged. Final regressions: 1120 Python,
38 Node suites, nine independent checks; acceptance still INCOMPLETE while
stopped. Fresh quiescent backup and unique epoch-15 launch intent retained.
Publish and restart only through the scheduler, immediately reconcile eight
existing members, and continue genuine final-generation lifecycle/14400s proof.

2026-11-17 stage09: new runtime independently reconciled eight losses and cleared
the earlier exact won/resold item after a genuine 4300 sale. Three native461 /
service403 bid failures triggered immediate cooperative stop; 41 UNKNOWN intents
preserved, no fourth dispatch. Official-page refresh and extension reattachment
then permitted one NEW 700-coin bid with independent participation evidence.
Different target/document confound exact denial causality; no account restriction
or historical bid outcome inferred. Native-fault trace did not record a crash in
this run. Focused captured-proof audit rejects four corruptions; full acceptance
still INCOMPLETE, healthy seconds zero. Publish, scheduler-launch epoch 17 and
reconcile/manage the actual new member before continuing four-hour proof.

2026-11-17 stage10: verified new owned generation/epoch 17, genuine current-member
management and one native 1600 rebid after competition with eleven independent
highest readbacks. Captured proof auditor rejects receipt/cap/participation
corruptions; actual final acceptance still INCOMPLETE. No production source fix
or restart at this checkpoint. Leave healthy service running and hand monitoring
to the scheduler; continue same-session engineering if it faults. No life-only
PASS, no replay of 41 UNKNOWN intents, no claimed four-hour interval.

2026-11-17 stage11 preservation: complete stopped generation retained after late
search/balance wire401 transition immediately following successful balance200.
Member terminal loss is real native evidence. Root cause of authentication
transition remains open; no account restriction or challenge inferred. Quiescent
backup integrity/FK/row comparisons passed. Continue native/UI contract diagnosis.

2026-11-17 H15 / NATIVE READ RENEWAL SUPPRESSION REPRODUCED AND REPAIRED:
Current official public _handleFail delegates normal UTAS renewal on401 when its
native doReauth flag is enabled; _handleReauth and handleTelemetry with doRetry
false notify the original failure without resending it. Bridge disabled renewal
for all reads, producing persistence that normal client maintenance could address.
Red/green captured-method tests establish the defect and bounded recovery seam.
Pure reads preserve only native true, mutation lineages remain false; metadata
contains success boolean only. Original401 server trigger and live expiry renewal
are not claimed proven. Full post-metadata regressions and monitored integration
remain next. Original requirements, budgets and historical verdicts unchanged.

2026-11-17 stage11 repair: official current public native renewal functions and
shipped bridge reproduce the forced-doReauth=false defect. Pure reads now preserve
only native-enabled renewal while doRetry stays false; mutations never renew or
retry. Original read401 remains failed, new independent read establishes recovery.
UTAS-only boolean completion diagnostics reject unrelated-environment success.
Final 1121 Python / 39 Node / nine independent checks pass; eleven renewal cases
and four captured-evidence negatives pass. Two finite six-read native baselines
pass after ordinary authorized UI recovery and reviewed extension reload. Live
renewal, original server trigger, final lifecycle and 14400s remain unproven.
Proceed with a new scheduler generation at epoch floor 20; preserve 41 UNKNOWNs.

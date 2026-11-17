# Objective 005 production repair

Status: **IN PROGRESS. Integrated runs stopped on semantic faults; no four-hour proof yet.**
This report is the working record for `obj-cb39371c785a/operate`, not a completion
verdict. Objective 003 remains paused and Objective 004 completed. Their historical
evidence, budgets and verdicts have not been amended.

## Stage 01: incident preservation and semantic stop policy

Starting `main` was `972c01e`. The worktree was clean. No FC production listener
was present on 8783/8784, and canonical account/native/port/database locks were
acquired before backup. Fresh SQLite backup directories, outside Git, are recorded
in `incident-20261117T005412938938Z/backup.json` and
`incident-20261117T010101301454Z/backup.json`. Every table was compared row for row;
both databases passed integrity and foreign-key checks. Production state was not
migrated or reset. The second incident projection additionally retains allowlisted
wire paths, target pseudonyms and header-presence booleans. The earlier projection
remains preserved.

The retained source state has 302 commands, 905 events, 41 acquisition batches,
19 attempts/tombstones, no managed members and ten completed quotes. Batch results
are 35 READ_FAILED, four OPERATION_FAILED and two SETTLED. All nineteen attempted
bids remain UNKNOWN. The command correlation shows:

| Observed layer | Actual retained evidence | Interpretation and remaining work |
| --- | --- | --- |
| Twelve bid requests | Wire PUT 461, service 403, native error code 461, matching target/amount, empty native items, unconfirmed receipt | EA denied the native request. Client status translation explains the numerical mismatch; exact reason for the server's permission decision remains unestablished. No bid acceptance, account ownership or refund is inferred. |
| Seven later bids | Wire/service 401, native error code 401, unconfirmed receipts | Authentication-related failure in this historical document; no independent participation confirmation. Current authenticated reads work. Exact session transition and the earlier write denial still require diagnosis. |
| Balance commands | Six success/200, thirty failure/401, four without results | The failed reads conferred no entry authority. Unknown deliveries remain consumed. Forty balance command records do not cover all 41 batches; batch failures may precede a recorded dispatch. |
| Watchdog | Work-boundary progress could continue after handled failures | Verified implementation defect: life/progress alone did not detect operational failure. Fixed in this stage with outcome messages and semantic fault thresholds. |
| Extension WAIT and discarded diagnostics | Worker can enter WAIT on local rejection or attachment/document failure; controller service currently acknowledges `/diagnostic` without retaining records | Exact historical trigger is not proved by a badge. Durable sanitized diagnostics and current recovery/ownership investigation remain next-stage work. |

`native-status-contract.json` contains only public static methods/enums from the
existing November 16 public-code capture referenced by its provenance. Executing
those captured functions with synthetic HTTP responses demonstrates that
`UtasErrorCode.PERMISSION_DENIED = 461`, `convertUtasCodeToHttpStatus(461) = 403`,
and `_notify` retains error.code 461 while returning status 403. Code 458, rather
than 461, names CAPTCHA_REQUIRED in that capture. The controller bridge's equality
test between wire and service status therefore produces `ambiguous_network` for
these responses. This explains the classification; it does not prove why EA
rejected any particular target. These synthetic exercises are not new EA requests
or a diagnosis of account restrictions. No rejection or acceptance policy has
been relaxed.

## Fresh read-only evidence

This worker verified foreground control of the intended official Edge Web App and
clicked the reviewed production extension through existing Windows UI automation.
No challenge was visible. No sign-in recovery or saved credential access was
needed. `read-02/checkpoint.jsonl` records the separate single-use window, intent
before each command, actual sanitized responses and final closed-service state.
It used the current production public context, an isolated transport DB,
`write_authority=False`, and the canonical account/native locks. No controller,
legacy actor, account write or maintenance operation ran.

Six native commands produced **seven actual GETs**, all HTTP 200:

- Native credits: 63,702 coins, with the same owned wire/DTO balance contract.
- Watched items: empty.
- Complete Transfer List: five active entries; native, wire and repository counts
  agree at five, end-of-list true. These pre-existing items are not new-controller
  wins and confer no individual resale authority.
- Unassigned items: empty.
- Discovery: 21 auctions using the agreed filters, plus one owned player metadata
  GET. Metadata explains the seventh GET; commands and HTTP requests are distinct.
- Exact-target status: ten targets retained from that discovery, ten rows, ten
  independently validated full-version links, zero missing targets.

The consumed `read-01` attempt failed during harness setup because an initial
120-second attachment timeout exceeded the existing transport's maximum of 60.
No command was reserved or dispatched. Its original preparation and isolated DB
remain, with a separate failure record. The harness was corrected and `read-02`
used a new directory; the old attempt was not reset. Fresh empty watched/unassigned
reads do not retroactively resolve any of the nineteen historical UNKNOWN writes.
Those intents and tombstones remain isolated and must never be replayed.

`tests/check_005_stage01.py` independently reparses the captured response contracts
at their original observation times, checks command/intent/target links, counts
actual GETs and rejects invented successes. Its capture seal covers three immutable
captured evidence files only, never implementation, tests, configuration or
instructions. Its successful output is explicitly
`STAGE_VERIFIED_OBJECTIVE_INCOMPLETE`.

## Implemented operational fault policy

`fc_access/controller_v1/semantic.py` adds a pure outcome policy to the existing
watchdog. The serialized executor reports small typed results, and acquisition
reports durable batch membership/uncertainty after the independent status step.
The policy never sends an account request, retries, repairs, restarts, promotes an
ACK to confirmation or rewrites transaction evidence. The existing lease and
ownership guards still withdraw dispatch permission and drain the owned worker
on stop. The parent retains outcome messages in its existing per-run event log.

| Fault threshold | Stop reason |
| --- | --- |
| Two authentication failures without a successful native operation between them | PERSISTENT_AUTH_FAILURE |
| Three consecutive failures of a particular native read operation | PERSISTENT_READ_FAILURE |
| Three failed writes of a particular operation, excluding proven ordinary bid rejection | PERSISTENT_WRITE_FAILURE |
| Three successful exact managed status responses containing no requested rows | PERSISTENT_EMPTY_MANAGED_STATUS |
| Three failed acquisition batches (READ_FAILED / OPERATION_FAILED / INVENTORY_UNKNOWN) | PERSISTENT_ACQUISITION_FAILURE |
| At least three attempted uncertain acquisitions without independently confirmed membership, evaluated after batch readback | PERSISTENT_UNCONFIRMED_ACQUISITION |
| More than 90 seconds since a usable native success, or since startup before the first one | NO_FRESH_NATIVE_SUCCESS |

Three write faults stop well within the existing ten-attempt maximum; two auth
failures stop before an unbounded failing read loop. Ninety seconds matches the
existing startup grace and allows finite paced native operations and cold pricing;
local helper callbacks cannot renew native freshness. Three empty managed status
cycles are distinct from ordinary empty market discovery. Per-operation streaks
prevent a healthy status or balance read from masking persistent owned-item or
inventory failures. Ordinary proven rejection, a single ambiguity, outbid/loss,
capacity limits and empty discovery do not themselves trigger a global fault.
These are operational fault criteria, not artificial production experiment budgets.

The retained incident replay test trips at the third 461 bid, before the later
401 storm. A real isolated subprocess test demonstrates that a failed but
progressing worker is stopped and joined once, without forced termination or
restart. Real-controller fixtures exercise independently confirmed membership,
read failures and durable no-replay behavior. They are offline evidence only.

## Verification and next stage

Commands and complete outputs are retained in `checks/stage01`:

| Final stage command/group | Actual result |
| --- | --- |
| `python -m unittest discover -s tests -v` | PASS: 1088 executions, zero failures/errors/skips; 475.429 seconds recorded wall time, `python-final/` |
| Every current `tests/*checks.cjs` via `python tests/record_005.py node ...` | PASS: 36 Node suites, `node-final/` |
| `python tests/record_005.py independent ...` | PASS: all nine commands, `independent-final/` |
| `python tests/test_005_semantic.py` | PASS: 17 tests, also included in discovery; `focused-final/` |
| `python tests/test_005_evidence.py` | PASS: five tests, also included in discovery; `focused-final/` |
| `python tests/check_005_stage01.py` | PASS for this stage's retained evidence only, explicitly objective incomplete; `focused-final/` |
| `git diff --check` and staged diff check | PASS |

The first full discovery also passed 1080 executions in 476.643 seconds. Final
discovery includes the later added cases and final production changes. Counts
across overlapping focused/full runs must not be added as distinct tests.
The first independent-validator batch overlapped Python discovery and its
004-01 check failed to acquire a canonical lock held by discovery. The other eight
validators passed. These commands share global quiescence checks and must be run
serially; the failed receipt is preserved, not relabeled or suppressed.

The serial rerun then exposed a distinct archival-check defect: one scheduler
audit event, 594021, had been appended at 00:51:31 UTC for the paused legacy task.
It records RECONCILING to RECONCILING, no provider turn and a null diagnostic.
Narrow row comparison found zero modified/deleted historical rows and no added
actor turn. `legacy-noop-observation.json` preserves that sanitized observation.
The audit now preserves every original row and rejects additions except verified
same-state, no-turn transitions under a still-paused parent. New negative tests
reject changed checkpoints, deleted history, actor activity and resumed parents.
No database record or sealed historical evidence was edited. All nine independent
validators passed in `independent-final` after this behavioral correction.

Two initial new evidence-test assumptions were corrected: native discovery really
made an auxiliary metadata GET (seven actual GETs, six commands), and a Windows
SQLite fixture needed explicit connection closure. All five evidence tests and
all seventeen semantic tests pass in focused runs. No historical test assertion
was removed or weakened.

Remaining: retain sanitized diagnostics instead of discarding them; finish exact
native write/auth/identity/queue diagnosis with a new finite intent/readback window;
implement and test scheduler-owned runtime lock, restart-readable ownership,
deterministic health/stop interface and startup state; reconcile genuine current
account state; then launch through the existing orchestrator's service handoff.
The extension must be reloaded and current page attached to the reviewed code
before write validation. The actual extension sources are under
`browser/production-v1/`; the input's `fc_access/production_v1/extension/page.js`
path does not exist in this tree.

A later desktop inspection found `SetForegroundWindow` alone was denied from
the tool's new process. A bounded, verified official-window fallback using
temporary `AttachThreadInput` plus normal restore/foreground APIs succeeded
(`desktop-focus-recovery.json`), without any keyboard/mouse input. The original
separate-process helper still fails its foreground guard; it needs this tested
fallback before the next attachment. This is an engineering repair, not evidence
of absent desktop access or a human prerequisite. A new scheduled task named
`FC-005-Orchestrator-Review-20261117` was observed Ready; sanitized action
classification identifies an orchestrator review action, no FC controller/legacy
actor action. It was not created, launched or changed by this worker.

There is no human prerequisite or evidenced external blocker at this checkpoint.
Trading services are stopped, the finite read-only probe closed with zero pending
commands, historical unknowns remain protected, and healthy operational seconds
remain zero. No real acquisition, rebid, win, move/list, maintenance or four-hour
coverage is claimed by this stage. Launch/health/stop and existing-objective resume
instructions will be finalized with the scheduler integration, before the live
production handoff. No second scheduler or replacement objective was created.

Stage01 publication uses the commit titled `Preserve Objective 005 incident and
stop persistent controller failures`. Its report/evidence and progress log are
part of that publication. This checkpoint continues the same task automatically;
it is not a production-ready or objective-completed handoff.

## Stage 02: diagnostic retention, owned runtime and reproduced live denial

Started from published clean `4cc51c1`. No FC listener was running. A fresh
canonical-lock-held, integrity/FK/row-compared controller/cache backup is recorded
in `stage02/backup-20261117T012442462535Z.json`, outside Git under
`C:/hustle/orchestrator-migration-evidence/005-stage02-20261117T012442462535Z/`.
The additive diagnostic schema was first applied under those exclusive account
guards. Original commands, attempts and evidence were not rewritten.

Implemented and tested:

- Successful local price helpers remain excluded from native freshness. Three
  failed helpers stop with PERSISTENT_HELPER_FAILURE, including the actual
  controller path where successful caps reads previously masked helper failure
  as empty acquisition.
- Controller `/diagnostic` now retains strictly typed, command/peer-bound records
  in append-only `c4_diagnostics`. Maximum 64 records/post and 256/command; unknown
  commands, unclaimed commands, stale epochs, unknown/sensitive fields and excess
  records are rejected. Invalid native results preserve a typed RESULT_REJECTED
  summary without storing the untrusted body or arbitrary error text. The real
  serialized boundary checks retained diagnostics; three missing sets stop with
  PERSISTENT_MISSING_DIAGNOSTICS.
- The schema 4 page now emits PAGE_ENTER, NATIVE_INVOKE, EA_RESPONSE,
  NATIVE_CALLBACK, timeout/failure and PAGE_FINISHED markers. These are diagnostics,
  never authority to acknowledge a bid or enroll membership.
- Verified foreground recovery now uses the bounded temporary thread-input
  attachment fallback, detaching in finally. Input also permits a popup only
  when Windows identifies its root owner as the exact intended Edge window;
  another window in the same Edge process is rejected. Nine deterministic focus
  and popup cases cover success and failure. Existing extension menus are
  recognized before opening, avoiding a toggle that closes the needed menu;
  visible-button discovery waits at most two seconds. Actual official Edge
  recovery, extension reload, refresh and final attachment succeeded. No login
  challenge or credential input was needed.
- `fc_access.controller_v1.operational` supplies the scheduler service, health and
  stop entry points. One OS-backed owner lock protects an exclusive consumed
  generation directory; atomic fsynced manifests retain task, generation,
  supervisor/child creation identity, real progress, semantic counters and exact
  stop reason. No PID-only termination is used. A generation cannot be reused.
  Health requires live matching creation identities, lock ownership, a manifest
  at most five seconds old, actual work-boundary freshness and native success;
  it independently checks failure thresholds. STARTING expires after 90 seconds
  from the actual launch, and successful helpers cannot extend native freshness.
  An owned stop request withdraws the existing lease and joins the owned child;
  stale/foreign generations cannot stop a later service. Local state-file write
  failure also stops/joins safely. No persistent production service was launched
  in this stage; all service-process tests are finite socket-forbidden fixtures.

The real-process tests cover duplicate launch, consumed-generation refusal,
repeated stop, stop after parent death, child lease loss, stale process creation
identity, foreign-task/stale-generation stop, failed reads despite live progress,
strict JSON health CLI, bounded startup, stale samples and disk-write failure.
They establish local runtime behavior, not EA lifecycle proof or provider-cleanup
survival of a production launch. Scheduler-owned deployment remains required.

### Actual live experiment

Two attachment attempts (`stage02/bid-01`, `bid-02`) closed with **zero reserved
commands, zero EA operations and zero mutations**. They exposed ordinary helper
defects: the Extensions popup owns foreground through the intended root window,
and opening an already-open menu toggles it closed. These attempts were not
reset. After those fixes, separate `bid-03` attached and completed its finite
window. This probe used the real production controller DB, quote cache, normal
admission/selection/journal and native transport. Its subclass permits at most
one initial attempt, with no maintenance operations; all ordinary price,
balance, inventory and eligibility rules still apply.

The window captured 129 command results, **26 actual EA requests (25 GET, one PUT)**,
32 reserved EA slots, and one 850-coin native initial bid. No Buy Now, rebid, move,
list, Clear Sold or relist occurred. The sole target is version 246191,
`trade:a19d4fae0576c0918d65782f`, `item:658c3eb1bab5944f9e1d9006`.
Stored resale 5100 and profitable legal cap 4300 were unchanged. Discovery observed
current 800 at 01:43:43.821 UTC. Selection age 40.143535s left 71.856465s, satisfying
the strict more-than 60s rule. The minimum 850 bid was sent at 01:44:25.840 UTC,
**42.019 seconds** after discovery. Native target/body binding matched.

The actual result reproduced the historical class:

```text
command 17bcb5a360204fbfee2fd7a766771d62
wire PUT /ut/game/fc27/trade/:trade/bid -> 461
native callback status 403 / success=false / error.code 461
receipt UNCONFIRMED / EMPTY_NATIVE_ITEMS / matching count 0
controller result UNKNOWN / ambiguous_network
```

The retained typed trace independently records EA_RESPONSE 461 then
NATIVE_CALLBACK 403/false before PAGE_FAILURE. Fresh exact status at 01:44:27.835
returned the same trade/item, current 900, active, 68 seconds remaining, account
bid_state none. A fresh personal watched GET then returned empty. Membership is
zero. The unknown command is consumed and was never retried; no rejection,
refund, loss or ownership is inferred from these observations.

**Hypothesis, not established cause:** competition advanced the required minimum
while pricing consumed the initial discovery's age. The observations support a
stale-price/competition hypothesis; they do not show whether current 900 preceded
the failed write, nor prove an account restriction. The next finite experiment
must use a new distinct target and a fresh exact status before its first bid,
retaining the original full identity and unchanged profitable quote/cap. Scope
any production freshness repair from those actual results; do not replay this
unknown, change the filters/pricing/lookahead or fabricate a win.

All 129 native responses are retained, but only 127 probe semantic callback records
were captured. One caps and one helper response lack that secondary callback.
The probe's SQLite diagnostic-count query had not taken the store lock; it now
uses the same lock as the already-protected production callback. The exact two
lost callback exception causes cannot be reconstructed. This gap is disclosed,
not counted as operational health. Require complete callback/error evidence in
the next probe. The live data confirms diagnostic retention and status translation,
not successful acquisition or complete production readiness.

`tests/check_005_stage02.py` independently reparses all 129 native response
contracts at their original times, checks pre-dispatch intents, actual budgets,
one write, exact identity/cap/age, independent status/watch results and the
retained diagnostic chain. It verifies seals only for captured experiment/EA
evidence, and runs six negative tampering checks. Its verdict explicitly remains
STAGE_VERIFIED_OBJECTIVE_INCOMPLETE.

### Verification and safe checkpoint

Full discovery passed **1103 executions**, zero failures/errors/skips, in 484.045s
recorded wall time. All 36 Node suites passed. Full receipts are under
`checks/stage02/python` and `node`; the serial independent and final focused
receipts are adjacent. Initial process-fixture defects were corrected: test
generations require isolated fixture journal directories, and closed stderr pipes
must not be communicated twice. The initial foreground popup guard and one
misplaced PowerShell helper declaration were caught and corrected before the
successful attachment. No functional check or original acceptance was weakened.

The production DB is now STOPPED/ACQUIRING with 20 UNKNOWN attempts, zero active
managed members, zero pending commands and 643 retained diagnostic rows. All 19
old unknowns plus the new unknown remain protected. No background FC controller
or watchdog was launched; healthy operational seconds remain zero. Continue this
same task with the fresh-status experiment and evidence-driven repair, then
deploy through the scheduler service handoff and prove the genuine full lifecycle
and final uninterrupted 14400-second interval. No external blocker is proposed.

The final health-message refinement preserves the exact recorded STOPPED reason
after the parent exits, instead of replacing it with generic ownership loss.
The five real-process tests passed again after that isolated refinement in
`checks/stage02/focused-health-reason/`; this follow-up is separate from the
1103-execution full receipt above. Final serial independent verification passed
all nine commands. Stage02 publication title: `Add owned runtime health and
retain native denial diagnostics`.

The operational argv contract for the eventual scheduler handoff is:

```json
{
  "monitor": {
    "check": {"command": ["{python}", "-m", "fc_access.controller_v1.operational", "health", "--runtime-dir", "private-captures/controller-v1/operational", "--task-key", "obj-cb39371c785a/operate", "--generation", "<new-32-hex-generation>"], "timeout": 30},
    "stop": {"command": ["{python}", "-m", "fc_access.controller_v1.operational", "stop", "--runtime-dir", "private-captures/controller-v1/operational", "--task-key", "obj-cb39371c785a/operate", "--generation", "<same-generation>"], "timeout": 60},
    "interval": 30,
    "startup_seconds": 90
  },
  "service": {
    "id": "<new-single-use-launch-intent>",
    "command": ["{python}", "-m", "fc_access.controller_v1.operational", "service", "--runtime-dir", "private-captures/controller-v1/operational", "--task-key", "obj-cb39371c785a/operate", "--generation", "<same-generation>", "--database", "private-captures/controller-v1/controller.sqlite", "--cache", "private-captures/controller-v1/quotes.sqlite", "--context", "private-captures/controller-v1/public-context.json", "--port", "8784"]
  }
}
```

This is a planned payload, not a consumed launch ID or running generation. The
worker must substitute a genuine new ID only after reconciliation and use the
existing scheduler's service handoff. The stop timeout60s allows the existing
35s graceful drain and bounded joins; it sends no EA request or arbitrary kill.
Once launched, exact PowerShell inspection/stop uses the retained generation:

```powershell
Set-Location C:/hustle/fc-hustle
$generation = (Get-Content private-captures/controller-v1/operational/state.json -Raw | ConvertFrom-Json).generation
python -m fc_access.controller_v1.operational health --runtime-dir private-captures/controller-v1/operational --task-key obj-cb39371c785a/operate --generation $generation
python -m fc_access.controller_v1.operational stop --runtime-dir private-captures/controller-v1/operational --task-key obj-cb39371c785a/operate --generation $generation
# If this objective was explicitly paused, resume its existing identity:
& C:/hustle/agent-orchestrator/.venv/Scripts/orchestrator.exe --db C:/hustle/fc-hustle/.orchestrator/state.db resume obj-cb39371c785a
```

The scheduler already owns this active task. No scheduler launch, SQL lifecycle
edit, replacement objective or legacy actor resumption occurred in this stage.

`stage02/final-state.json` captures the stopped DB and no pending work. Its broad
process heuristic also matched the collecting PowerShell command because that
command mentioned probe filenames during Git staging. The separate collector-only
`final-quiescence.json` at02:10:51 UTC avoids that false match and independently
reports no FC workers, listeners or scheduled mutation jobs. Both captures remain
retained; the stage validator uses the later quiescent observation and the DB
projection without pretending the earlier heuristic was exact.


## Stage 03 ? fresh selection and first confirmed live participation

The separately consumed `stage03/fresh-bid-01` experiment answered whether a
minimum bid based on current exact status could succeed after the aged-discovery
461 denial. It did: command 16ccdb47cc35f608ba0bf72d7ac6eaf8 bid 700 on
trade:d4e9c4b3d4ee3636cb3e9df6 / item:e211ec5628440e33479fdaf8 / definition 233731.
Native wire 200, service 200, receipt ACCEPTED with exact matching item/amount;
separate exact status a8661367041b03df13454d6319dc61cb and later personal watched
077a1978da8c5347b9fdc6bab32c555d both independently showed highest/current700.
Full-version provenance comes from the owned native full read, never the lite
DTO's zero definition field. The probe ended stopped with zero pending commands.
It retained 99 native responses AND 99 semantic callbacks, 21 actual EA requests
(20 GET/one PUT),26 request reservations and one irreversible intent. No lost
callback is hidden. All 20 earlier UNKNOWN attempts remain protected.

Before/after selection retained the same completed quote, cap 4100/resale 4900 and
minimum 700. Original discovery selection age 30.203395s became 0.356731s for the
fresh exact status; remaining 230.643269s exceeded 60. This confirms working
acquisition in this account/document epoch and supports stale selection as a
contributor. It does not prove the exact EA server reason for every historical 461
or explain all 401 failures. Ordinary competition, explicit native translation,
authentication and uncertain dispatch remain distinct evidence classes.

Production now batches one exact status read after pricing and before immutable
selection. It keeps completed pricing and full-version provenance unchanged,
recomputes only legal current minimum/expiry, and rejects missing, expired or
over-cap candidates. Balance remains one entry check, strictly >40000; discovery
filters/max10/fee/profit/native increments and sequential management remain.
Tests change live fixture request counts to include this read and ensure the
post-bid membership proof still uses a later independent status. Sealed004 traces
are unchanged; explicit socket-free historical replay preserves their original
observations while current fixtures exercise the corrected production behavior.

A result-monitor exception now closes admission immediately and reports only
its type to supervision with RESULT_MONITOR_FAILED. Canary-negative tests prove
no exception value leaks and no second account request dispatches. This repairs
a path where policy exception handling could otherwise continue after monitor
failure. The live experiment had complete callbacks; the old two missing
callbacks remain honestly unresolved historical evidence.

Full regressions: 1106 Python executions, zero failures/errors/skips, 488.333s,
all 36 Node suites and all nine serial independent checks passed. Exact argv,
stdout/stderr and receipts are in `checks/stage03/python-final`, `node` and
`independent`. The retained earlier Python run failed one obsolete post-status
ordering assertion. Its stronger replacement checks both pre-bid freshness AND
all membership proof IDs against the separate later post-bid status; no functional
coverage was removed. `check_005_stage03.py` independently reparses the captured
wire/service/account envelopes and rejects six altered-evidence cases. Its
explicit verdict is STAGE_VERIFIED_OBJECTIVE_INCOMPLETE. Only immutable consumed
experiment captures are sealed, never mutable source/tests/instructions.

`validate_005_interval.py` independently audits scheduler monotonic samples,
constant generation/epoch, gaps, actual process ownership, and separately
correlated native successes from watchdog log plus controller SQLite envelopes.
It rejects heartbeat/helper-only history, fixture provenance, missing diagnostics,
stale native success, short duration, restart/fault or unmonitored gaps. Eight
negative self-tests passed; these are OFFLINE, not operational evidence. Default
acceptance currently fails because no production runtime/four-hour history exists.
A full lifecycle acceptance checker remains necessary before completion.

Quota interruption occurred with trading stopped. The confirmed auction has
since expired by wall time; its actual terminal outcome/ownership is UNKNOWN
until fresh account reconciliation. Do not infer won/lost or move unrelated
items. `pre-service-backup.json` retains a new canonical-lock runtime backup
with row equality/integrity/FK checks; DB STOPPED/MANAGING, one ACTIVE member,
20 UNKNOWN, one ACKNOWLEDGED, zero pending commands. Collector-only
`pre-service-quiescence.json` shows no FC workers/listeners/jobs;
`pre-service-browser.json` verifies this worker's official Edge foreground
access and no visible challenge. No saved authentication values were accessed.

`launch-intent.json` prepares a unique generation/service ID for the installed
scheduler only; no persistent service has yet been dispatched and healthy seconds
remain zero. Publish this repair, hand off service+monitor with status continue,
then immediately inspect startup/reattach if needed and reconcile the existing
member through genuine native reads. Continue semantic monitoring and automatic
repair in this same task. First-production run must still prove management,
terminal ownership/move/one-hour resale/eligible maintenance and the final
uninterrupted 14400s. Original requirements are unchanged; no blocker proposed.


## Stage 04 ? first scheduler launch, safe stop and startup repair

Published stage03 was `0b20735a306c8f8457b807c694c524fdf57d550e`. The installed
scheduler recorded launch intent 629160 and spawn 629161 for generation
b6898a8aeec49b4985957a4d6425aeb3. Its immediate first health event 629164 saw
RUNTIME_STATE_UNAVAILABLE before the new Python service published its manifest.
The service then initialized at 05:31:15 UTC and honored the scheduler's owned
OPERATIONAL_STOP. At05:31:39 UTC it exited without forced termination; the stop
command acknowledged in 24.311s. This was an initialization race, not evidence of
an EA outage or failed trade. No native_result occurred, no EA request dispatched,
and controller command count stayed 530. Existing 20 UNKNOWN attempts and the
confirmed ACTIVE member are unchanged. Actual terminal ownership remains to read.

`stage04/first-runtime-state.json`, `first-runtime-events.jsonl` and
`first-runtime-scheduler.json` preserve the independent consumer/scheduler chain.
`backup.json` records a fresh canonical-lock backup outside Git with SQLite
integrity/FK checks and row equality. `check_005_stage04.py` independently verifies
the stopped generation, cooperative acknowledgement, zero dispatch/journal delta,
preserved uncertainty and backup; four altered-evidence cases fail as intended.
The first service ID/generation are permanently consumed and will not be reused.

The consumer health command now waits at most 2s for the actual requested-gen
manifest, including replacement of an old generation pointer. It never reports
STARTING for missing state; it still requires owned lock/process creation identity
and valid runtime semantics. Repeated checks with no service remain repair.
Six real-process tests include an immediate check against delayed initialization,
absent runtime repetitions, stale/duplicate ownership, parent death and semantic
failure. No generic orchestrator change or live orchestrator SQL edit was needed.

Full Python discovery passed 1107 executions, zero failures/errors/skips, 491.451s.
All 36 Node suites and all nine serial independent checks passed. Exact argv and
stdout/stderr receipts are retained under `checks/stage04/`. The new lifecycle
validator independently checks actual native wire/service/account evidence and
rejects an ACK-only, fixture-only, unrelated, mispriced or unconfirmed chain.
It requires acquisition in the final generation, independent later participation,
management, an actual confirmed rebid when affordable competition is observed,
terminal paid-price ownership, exact physical move and one-hour listing using
the stored quote and native limits. Eligible bulk work must independently preserve
all eligible membership, identity, prices and one-hour duration. Latest full
regression inventories and clean pushed main are also required.

`validate_005_lifecycle.py --self-test` constructs an isolated socket-free world
with valid explicitly synthetic write replies and genuine fixture side-effect
readbacks. It exercises acquisition, rebid, paid win, move/list and clear/relist,
and rejects eight corrupted-evidence cases. Historical WorkEA scenes intentionally
support lost replies; local self-test scaffolding adds explicit synthetic replies
without rewriting those scenes or claiming production coverage. Its initial
fixture cleanup and missing bulk body-empty fields were corrected before PASS;
no live outcomes were changed. Interval validator self-tests reject eight temporal/
semantic discontinuities. Both default acceptance commands remain INCOMPLETE.

Healthy operational time is zero. Prepare a NEW generation/service ID, commit/push,
and return continue with scheduler-owned service and health/stop fields. Immediate
next action is to inspect startup/attach as needed and reconcile the expired
confirmed member against actual account evidence, protecting all uncertain bids.
Then retain genuine live acquisition/management/settlement/ownership/resale and
eligible maintenance plus 14400 uninterrupted healthy seconds after the FINAL fix.
There is no external escalation. Original requirements and legacy controls remain.


## Stage 05 ? operational stop, real relist and two independent native confirmations

Generation fb6b1dcd8851445b6c616c772a700ab5 attached automatically and reported
semantic health with real fresh native EA successes. It reconciled the old 700
confirmed auction as LOST: fresh read b62dd62c335baedecf8c5e0792974f02 showed
closed/outbid, current 4600 and native_is_won false. The old membership body's
entry proof remains historical; the separate LOST event carries terminal proof.
No ownership, move or resale was inferred for that lost item.

The same run genuinely performed relist_all 09cae9aad9c5ae1d86e1133370f83de7.
`maintenance-work.json` retains exact pre-inventory and independent fresh post
readback. The independent native bulk assessor verifies all eligible entries,
unchanged prices/physical identities and one-hour duration. Clear-sold was not
eligible. This is genuine production maintenance evidence, separate from synthetic
resale tests and still-unobserved genuine won-item move/list behavior.

The run then submitted three initial bids: 750, 900 and 700, each returned owned
wire 461/service 403/native error 461 with empty native receipt. Pre-burst status
was fresh; remaining times exceeded 60s. Watchdog stopped cooperatively under
PERSISTENT_WRITE_FAILURE before a fourth native bid. Of ten planned intents,
three reached native dispatch and seven were consumed unsent, leaving 30 UNKNOWN
attempts in total then. No unknown was replayed or promoted. Earlier healthy
samples remain historical in `scheduler-run.json`; final healthy time is zero.
This demonstrates semantic failure detection, not successful acquisition.

The fresh-status repair is therefore insufficient to explain every 461. Added
positive-allowlist diagnostics record owned wire auction numbers/states and
boolean identity/coherence against the native callback, never raw response data,
authentication values or arbitrary error text. Negative tests cover mismatched
wire/callback values, response encodings, secret canaries and strict Python types.
`wire-read-02` completed six commands, zero writes and ten exact status targets:
all ten independently retained wire projections matched the callback. The first
window closed with zero commands during normal sign-in recovery; it remains
consumed. Saved zzorniss account selection and password submission used ordinary
Edge UI/autofill; no saved values were read/exported. A repeated normal Login
click was necessary; no visible challenge or unavailable prerequisite occurred.

`wire-bid-01` then recorded a new 800 intent b4b1fd21faeb907e8de1a029c41e8f70.
It was never claimed: no tombstone, no native diagnostics/result, only INTENT and
UNCERTAIN. It is a local delivery uncertainty, not another captured EA 461 or a
confirmed failed bid. Later personal readback conferred no membership. Its UNKNOWN
record remains consumed. The worker formerly lost between-command failures when
active=null after ACK. Typed WORKER_POLL_FAILURE now reports only an allowlisted
poll phase/reason against the last acknowledged scope. Existing fencing rejects
stale diagnostic scopes; no execution/result retry or new trading authority exists.
The exact cause of that earlier missing claim is still unresolved.

`poll-read-01` was correctly refused before any command because epoch 6 had already
been consumed by the previous production-backed probe. The actual persisted peer
was inspected; `poll-read-02` used epoch 7 and completed six native reads, then
observed 25 seconds of local polling without a retained failure and without any
additional EA request. Epoch floors are now explicit finite-probe public control
inputs; they cannot reset windows or authorize stale/uncertain writes. These are
normal engineering/recovery conditions, not external blockers.

`poll-bid-01` used a NEW target and epoch 8, without refreshing the signed-in page.
It genuinely bid 750 via command 6635a5408d33817c3de33a017a402baf on
trade:3ebc22bd4a6a9be28c286aeb / item:bb160ebf4efd88ee511a6196 / definition 256079.
The stored cap was 4200. Owned pre-status wire/current native data agreed, and
wire 200/service 200/native ACCEPTED receipt matched exact item/trade/amount.
Later exact status AND personal watched independently confirmed highest/current 750.
It retained 120 native command results and 120 monitoring callbacks, 20 actual EA
requests (19 GET/one PUT), 21 reservations, zero pending commands and no semantic
fault. It ended stopped with one ACTIVE confirmed member, one historical LOST,
31 UNKNOWN attempts protected and two ACKNOWLEDGED initial bids. Expiry was about
06:38:11 UTC; subsequent management must reconcile genuine current state.
This proves current write ability, not a precise server explanation for old 461
or a general account restriction. Do not invent either conclusion.

`check_005_stage05.py` reparses actual native envelopes and independent account
confirmation, re-runs the native bulk effect contract from captured commands,
checks the three-failure stop/seven unsent intents and unclaimed 800 isolation,
and rejects four altered-evidence cases. It explicitly reports objective incomplete.
No genuine won-item move/resale or final four-hour interval has been observed.
All 37 Node suites pass; full Python and serial independent verification will be
recorded before publication. Then issue a new scheduler-only generation; normal
next production owner epoch 9 follows the persisted epoch 8. Immediately reconcile
and manage the new confirmed member, continue autonomous stop/repair on semantic
faults, and retain the full intended lifecycle plus 14400 consecutive healthy
seconds after FINAL fix/restart. Leave the healthy service running at completion.


Stage05 final verification: **1108 Python executions**, zero failures/errors/skips,
496.406s; **37 Node suites** and all **nine serial independent validators** passed.
Receipts are in `checks/stage05/`; focused evidence and acceptance self-tests are
adjacent. Both live acceptance commands correctly remain INCOMPLETE. Captured
EA/transaction/consumed-window evidence is sealed, excluding all mutable source,
tests, instructions and configuration. Full inventories were completed with
trading stopped; no historical check was skipped to obtain green output.

Fresh `pre-service-backup.json` records integrity/FK/row-equal backups outside Git.
Local DB has 907 commands, 31 UNKNOWN attempts, two ACKNOWLEDGED, one ACTIVE locally,
one historical LOST and zero pending commands. Separate collector-only and
browser observations are adjacent. The confirmed 750 auction is now expired by
wall time, so startup must reconcile actual native status/ownership rather than
assuming won/lost, replaying a bid or moving an unrelated item. A new scheduler
launch intent will be recorded before dispatch; healthy consecutive time is zero.

## Stage 06: genuine bidding, win and move; Windows manifest repair

Starting revision `92f0b6f`. Scheduler-owned generation
`26407ef02dc7d322407f4c575c0c7ac7` started at 06:44:09 UTC on November 17.
Supervisor PID 18624 had creation FILETIME 134393714491919417; child PID 19344
had creation 134393714495182626. Executable and creation identities, account/
persona pseudonyms and complete fences are retained in stage06/stopped-state.json;
PID alone never authorizes stop. The retained watchdog log is
stage06/stopped-events.jsonl. Correlation labels are not authentication values.

Fresh native status reconciled the prior confirmed 750 auction as LOST:
closed/outbid, current 3800, native_is_won false. The next ordinary batch
2a147a4b9137d6d28fb1ecec33320d8d made ten initial bids, all with matching
wire/native ACCEPTED receipts and independent later native participation.
Ten genuine rebids followed fresh outbid competition and independent readbacks.
These are real account operations. All 31 earlier UNKNOWN initial intents remain
consumed. Strategy thresholds, pricing, filters, ticks and maximum ten initial
attempts were preserved.

One item was genuinely WON at our paid **3100**: definition 251852,
trade:324779fd0ad15aad19df591a / item:4fa51171b8d65f02a7e65198.
Fresh terminal watched evidence, our accepted bid and an independent owned-item
GET establish exact physical identity, tradability and paid price. Move command
81c934d665ebdfaa732e3aab67545153 dispatched once through native Item.move.
Wire PUT /item and service returned 200. Its effect was independently confirmed
by transfer-list read 067e9571f0dde4de2e263b45e71f51c0 at 06:47:56.845 UTC:
complete wire/callback/repository agreement on six entries including this
inactive item, and fresh unassigned read 6c21b12b5a399dcc50affeb9ede5171e
showing it absent there. Listing policy remained start 4200 / BIN 4300 / 3600
seconds; **no listing was dispatched**. confirmed-move.json retains exact proof.

At 06:48:00 a second complete transfer-list read still contained the item.
From 06:48:08 onward fresh complete reads returned five entries, excluding it.
No second move, list or intervening bulk command exists. The old auction's later
lite status remained terminal/highest, which cannot establish physical location
after a move. The inventory change remains unexplained. Do not infer a sale,
listing, return or loss. post-move-projection.json and commands.jsonl retain the
observations. Native DTO/cache mutation is a hypothesis, not a server diagnosis.

Scheduler health event 642165 reported RUNTIME_STATE_UNAVAILABLE. The prior
sample had 150 native successes and 303 consecutive healthy seconds; the final
persisted snapshot had **166 native successes**, ten confirmations, one batch,
native age 1.65 seconds and zero semantic failure streaks. Event 642166
acknowledged the owned stop in 2.232 seconds. Watchdog STOPPED at 06:50:15 UTC
with OPERATIONAL_STOP, exit 0, forced false. This is an I/O health incident;
the old catch discarded its exact exception. It cannot establish authentication
or market failure. Healthy consecutive time resets to **zero**.

A real Windows experiment reproduced PermissionError winerror 5 / errno 13 when
an ordinary open reader denied atomic destination replacement. Runtime readers
now use CreateFileW with FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE;
publication uses ReplaceFileW to preserve destination attributes/ACLs and support
existing shared readers. First publication uses atomic rename. Only local sharing
errors 5/32/33 receive bounded 0.5 second replacement retries. Health retries
transient missing/denied manifest access for at most two seconds, then reports
repair with safe exception type/errno/winerror, never raw exception text. It
does not extend startup or fabricate health. See Microsoft's
[CreateFileW contract](https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew)
and [ReplaceFileW contract](https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-replacefilew).
This fixes a reproduced mechanism; the original unretained exception is unknown.
The held-reader regression failed with os.replace and passed with ReplaceFileW;
the test was not weakened.

Three new tests exercise complete old/new snapshots across a held reader,
transient/persistent real Windows contention, bounded denied health reads,
diagnostic redaction and temporary-file cleanup. All six existing real service/
ownership/stop tests pass. Full Python discovery completed **1111 executions**,
zero failures/errors/skips, in **494.890 seconds**; all **37 Node suites** pass.
Serial independent and focused audit receipts are retained alongside them.
All nine serial independent inventory commands passed. Focused verification
passed the nine ownership/I/O tests, stage06 audit and both eight-case acceptance
self-tests. The actual criterion 0 and criterion 1 commands returned nonzero
INCOMPLETE as required for the stopped, unfinished production objective; those
failures are recorded explicitly, not represented as acceptance passes.

A distinct finite zero-write win-read-01 window consumed epoch 10. Fresh watched,
transfer-list and unassigned native reads succeeded; the moved target was absent.
Exact target status failed locally with known_identity_unavailable before native
dispatch because the new binding cleared its old selector. Four commands / three
GETs / zero writes / zero pending / service stopped are retained. No owned-item
request followed the failure. Production DB last held epoch 9; restart must
reconcile the browser binding instead of reusing consumed epoch 10.

tests/check_005_stage06.py reparses all 305 actual native command results and
diagnostics, verifying ten initial bids, ten competitive rebids and independent
confirmation, paid terminal win, exact owned item, move effect, subsequent missing
inventory, scheduler stop and interval reset. Four corrupt evidence cases reject
ACK-only bids, wrong paid ownership, false move readback and counting a failed
sample as healthy. It explicitly reports STAGE_VERIFIED_OBJECTIVE_INCOMPLETE.
Only immutable captured EA/transaction/experiment evidence is sealed.

Safe state: runtime and finite probe stopped, move consumed, resale unproven.
The fresh backup outside Git is documented in stage06/backup.json with canonical
locks, integrity/FK and row comparison. Next: publish the verified repair, then
repair/test native selector and post-move proof recovery, establish current
physical location from fresh native evidence, and use a NEW scheduler generation.
No external blocker exists. Full acceptance validators remain
tests/validate_005_lifecycle.py (criterion 0) and tests/validate_005_interval.py
(criterion 1); neither can pass until the full genuine lifecycle and final
uninterrupted 14400 healthy seconds exist.

The next repair has a concrete contract defect to reproduce: Work.win currently
requests a new watched terminal win before listing, although native Item.move
claims the auction and its watched entry can disappear. Its trusted validator
also requires terminal reads in the current peer epoch, preventing use of genuine
persisted terminal proof across restart. Tests must distinguish immutable exact
terminal/our-paid-bid lineage from current independently fresh physical ownership
and caps. ACK, an old inventory row, a missing auction or an unrelated owned card
must never authorize listing. The separate unexplained disappearance of the
physical transfer item remains open and must not be hidden by this repair.

## Stage 07: claimed-win recovery and fresh physical location

Starting published main 91795d4. A fresh canonical-lock backup before repairs is
documented in stage07/backup.json; SQLite integrity/FK and row equality passed.
Trading remained stopped throughout engineering and finite read-only windows.
All 31 earlier UNKNOWN initial intents and the already dispatched move stayed
consumed. No legacy actor, objective verdict or historical evidence was changed.

Two socket-free positive cases reproduced the recovery defect before repair:
claiming a won auction removed its watched entry, preventing the next listing;
reopening the durable world with a new owner epoch also prevented listing. The
current work contract reparses the original exact terminal win, our paid-bid
dispatch lineage, original physical ownership, original chronology and separate
confirmed move effect. It does not infer those facts from state labels or ACK.
That immutable chain supplies historical provenance across epochs. Admission and
claim still require a NEW complete physical inventory with exact item/version,
tradability and paid price, current caps and native ticks, stored profitable BIN,
3600 seconds, current owner fences, durable intent and no consumed list action.
Confirmed claimed auctions leave status polling, since they need no further bid
management. Other urgent auction management remains sequential and unchanged.

The new Python recovery scenes cover watched disappearance, aged terminal proof,
restart with new fences and no repeated move, eight physical/caps negatives and
four corrupted-history negatives. Separate tests cover typed diagnostic category
redaction and an epoch floor that only advances public native fencing. Existing
17 controller lifecycle tests passed. tests/check_005_stage07.py reparses the
genuine retained 3100 move chain and rejects six corruptions, including account,
paid-bid lineage, ACK-only state, false readback, paid ownership and chronology.
It never labels historical evidence as a new ownership observation.

A bounded read-only selector recovery now matches the exact item pseudonym and
version in the selected account's native inventory cache (at most 2048 entries),
then performs a separate native requestItemsById GET. Cached selectors are not
fresh ownership, terminal evidence or write authority. Unowned active watched
auctions remain rejected before GET. Public source review verified the native
inventory methods; stage07/public-selector-contract.json contains method-only
projections from the official public compiled_2.js, with no browser/auth state.
Both the legacy read entry and reviewed controller queue entry pass exact-target,
unknown/version/oversize/persona negative and single-dispatch Node tests. Optional
item_pile diagnostics accept only club/transfer/purchased/inbox/storage/other;
no raw ID, native selector, header, session or credential value is exported.

The first full Python run retained 1115 executions with two failures. One exposed
an actual regression in unowned active-auction read rejection: it was corrected,
and the original final_owned_checks.cjs test was preserved unchanged. The other
was Windows ConnectionAbortedError 10053 during a local rejected-origin HTTP test;
the full 12-test integration harness passed on rerun. No speculative server fix
or weakened rejection expectation was used. Final complete inventories after
these changes are recorded separately; a failed run is never replaced or hidden.

Own desktop/foreground inspection verified the intended official Edge tab.
The reviewed extension was reloaded and the app navigated normally. Saved zzorniss
sign-in required repeated normal login controls, the displayed saved designated
account suggestion, Next and ordinary saved-password submission. No credential
value was inspected and no challenge was visible. These were ordinary authorized
recovery actions, not human prerequisites.

Three NEW finite zero-write windows retain every outcome:

- owned-read-01 (epoch 11): genuine watched GET succeeded. Transfer-list callback
  supplied no owned request while login/UI GETs were observed as background, so
  the ownership guard correctly refused ambiguous_network. It made no writes.
- owned-read-02 (epoch 12): fresh watched, transfer-list and unassigned reads
  succeeded. An incorrect Python argument shape stopped the probe BEFORE owned
  lookup dispatch; that probe bug was fixed. Its consumed window was preserved.
- owned-read-03 (epoch 13): four genuine GETs succeeded (watched, transfer-list,
  unassigned, owned item). Five commands were reserved; old auction status then
  correctly failed locally with known_identity_unavailable and no EA request.
  Overall window status remains FAILED, with zero mutations/pending and service
  stopped. Partial valid reads are distinguished from whole-window success.

**Current physical location is now independently established.** Fresh complete
transfer-list wire/callback/repository agreement contains six entries, including
item:4fa51171b8d65f02a7e65198 / definition 251852, inactive/current bid zero,
tradable and last_sale_price 3100. A separate native item GET returns the same
physical identity, exact paid price and transfer-pile diagnostic. Watched omits
the old trade, as expected after a claim. The earlier document's omission cause
is still unproven; normal recovery and fresh readback establish current state
without inventing an explanation or repeating the move. Immutable window logs,
results and diagnostics are sealed alongside the retained transaction snapshot.

Production DB last held owner epoch 9; isolated native probes reached epoch 13.
The explicit public --epoch-floor option chooses max(persisted + 1, floor), with
safe integer validation, and cannot lower a fence, reset a budget or replay an
intent. The next unique scheduler-owned service will use floor 14, current
account state and the existing production databases. No tool child launches a
persistent runtime. Its first work must reconcile existing members and list only
the genuinely owned pending win through the repaired authority contract.

Live resale and the final 14400-second interval are still unproven. Both full
acceptance validators remain authoritative and must reject incomplete operation.
After final regression/audit and publication, launch a new generation, immediately
verify genuine listing and continued acquisition/management, then hand semantic
monitoring to the scheduler. Every further defect or stop resets the interval.

Stage07 final discovery passed **1117 executions**, zero failures/errors/skips,
in **515.295 unittest seconds** (516.033 seconds including the process wrapper).
All **38 Node suites** and **nine serial independent inventory commands** passed.
Focused recovery/native-chain checks and both eight-case acceptance self-tests
passed. The earlier failed full run is retained alongside the final receipts.
The new stage audit is included in the final criterion 0 regression/evidence gate.

Fresh pre-service backup and desktop/process observations are adjacent. Local
DB has 31 UNKNOWN and 22 ACKNOWLEDGED attempts, nine ACTIVE, two LOST and one
PENDING_WIN member, no pending command. All expired ACTIVE auctions require fresh
native status, never wall-time settlement. There is no production worker,
listener or scheduled mutation job. Prepared generation
d019ab7647ea4aaac981c9319019b87b and unique service ID in launch-intent.json remain
undispatched until the scheduler consumes the handoff, using --epoch-floor 14.
Normal production must read current ownership/caps again before the first list;
the finite probe is not a reusable dispatch authorization. Full acceptances and
the final four-hour interval remain unfulfilled.

## Stage 08: genuine resale; shared SQLite statement-cache repair

Starting published main 26457b9. Scheduler generation
d019ab7647ea4aaac981c9319019b87b launched at 10:54:00 UTC with owner epoch 14.
Supervisor PID14972 / creation134393864405050358 and child PID1800 /
creation134393864408833148 matched actual live creation identities. The owned
service reconciled all nine earlier ACTIVE auctions as LOST through fresh native
status, then completed the original pending win's first genuine listing.

List command **9669d0fec6b3c4039b8c655c0690f21d** dispatched at
10:54:16.029754 UTC. The exact original won item (definition251852,
item:4fa51171b8d65f02a7e65198, paid3100) had a NEW complete inactive physical
inventory read and current native caps/ticks. Listing preserved stored start4200,
BIN4300 and 3600 seconds. Native POST /auctionhouse and its owned native status
follow-up both returned200. Separate full transfer-list read
ca04f05ad88c07b7c0147d759a027913 verified exact physical identity, new auction,
prices and one-hour duration. The original move was not repeated. The member
became WON_ACCOUNTED only after effect readback. This is genuine recovered
resale, not a synthetic fixture or ACK-based promotion.

Eligible maintenance command c3103db63d2bd8709c2f3a8a6de408e4 independently
confirmed native relist_all for exactly the two expired eligible items, preserving
their original prices and one-hour durations. Other inventory was preserved.
The next unchanged production batch abb68611488515c726ebb0526a335cf9 independently
confirmed **eight initial bids** and **three competitive rebids** with fresh
native account/auction evidence. The independent stage audit verifies original
entry>40000, discovery maxBid1000/minBuy11000, at most ten initial attempts,
more than60 seconds, completed quotes, exact version and original caps.

One rebid, 925f719d16be53d8feec724535aa7168, was marked UNKNOWN by policy after
an immediate local STATUS_UNKNOWN before any new native read was dispatched.
It is **not** a wire461 failure: the actual bid returned wire/service200 and a
matching ACCEPTED receipt for950. A later independent native status returned
highest/current950 for the same exact target. This establishes participation
without rewriting the original UNKNOWN journal entry or repeating it. The old
exception type/read invocation was discarded by _status, so its precise local
cause cannot be asserted; new diagnostics retain only planned read_id and safe
exception class, never arbitrary exception values. Eight already-confirmed
members continued management through independent reads.

### Crash and safe state

At **10:58:11.839726 UTC** Windows Application event1000 recorded child PID0x708
(1800) dying with **c0000005**, fault module **python313.dll**, version
3.13.17150.1013, offset000000000002b341. The watchdog independently retained
STOPPED/PROCESS_EXIT at10:58:14.975948, exit3221225477, forcedfalse. Its final
snapshot had112 genuine native successes, eight confirmed members, one batch and
zero semantic failure streaks. The scheduler detected the process fault and reset
consecutive healthy time to **zero**. The idempotent owned stop acknowledged that
both identities had exited. No production listener/actor remained; eight auction
members need fresh native settlement reconciliation after repair. All earlier31
UNKNOWN intents and the new UNKNOWN rebid remain consumed.

stage08/windows-fault.json contains only allowlisted Windows event fields;
stopped-state.json and stopped-events.jsonl retain independent runtime evidence.
The successful-prefix snapshot is preserved separately, not rewritten to conceal
the crash. No original native crash stack existed. We do not infer an EA outage,
account restriction, security challenge or a specific missing C call stack.
Fresh quiescent canonical-lock backups outside Git passed integrity/FK and
row-for-row comparisons before repair; see stage08/backup.json.

### Reproduced defect and repair

The controller's one SQLite connection was shared by policy and HTTP threads
with check_same_thread=False and the default prepared-statement cache. An isolated
finite test of the **actual ControllerStore connection** returned an incorrect
row under concurrent parameterized SELECTs in **0.220 seconds**. A separate
cached-connection control failed with the same synthetic-read mismatch in
**0.151 seconds**. Both red receipts and tracebacks are retained; these tests have
no network or production database access, and compare complete synthetic data.

The upstream [CPython cache-inconsistency report](https://github.com/python/cpython/issues/118172)
describes wrong concurrent reads in Python3.12/3.13 and an uncached workaround.
The [Windows native-crash report](https://github.com/python/cpython/issues/160699)
documents the same shared-connection pattern producing access violations even
with SQLite serialized threading. The [proposed CPython fix](https://github.com/python/cpython/pull/160706)
explains that the cached statement can be obtained concurrently before it becomes
busy, while execution releases the GIL. These primary sources support the
mechanism; they do not supply the missing original production stack.

The shared controller connection now uses **cached_statements=0**, removing that
unsafe statement reuse. Existing transactions, locks, durable intents, account
scope, pricing and native request pacing remain in force. QuoteCache retains its
separate thread-owned connection. The **unchanged actual-store workload** then
passed **147634 exact reads across12 concurrent readers over30 seconds** on
Python3.13.17 / SQLite3.50.4, threadsafety3, GIL enabled. A behavioral regression
runs the actual connection under the same concurrent bound-query pattern; it
does not assert source bytes or configuration text.

This establishes a real bad-read root cause and an evidenced explanation for the
native crash class. Attribution of the exact original fatal instruction remains
an inference. New workers enable faulthandler in their own fresh watchdog run
directory (python-fault.txt), recording stack locations for every thread on a
future native fault. No locals, exception values, raw memory dumps, browser
credentials, authentication values or provider/session data enter that file.
Tests verify stack metadata, canary redaction, exclusive trace creation and
pre-transport diagnostic correlation. There is no automatic process restart or
account-write retry in this repair.

tests/check_005_stage08.py reparses genuine native listing and exact effect,
maintenance, original-policy acquisition and competitive rebid confirmation;
four altered-evidence cases reject ACK-only listing, false ownership, changed
price and wrong duration. It also matches the Windows crash to the owned child,
checks the scheduler reset and verifies the red/control/green experiments. Only
immutable captured native, fault and experiment evidence is sealed. It explicitly
returns STAGE_VERIFIED_OBJECTIVE_INCOMPLETE with healthy_seconds0.

Final regression receipts under checks/stage08 show **1120 Python test
executions**, **38 Node suites** and **nine independent inventory commands**
passing. Focused-final receipts include three concurrency/diagnostic regressions,
four altered-listing negatives and both acceptance validators' negative fixtures.
The real acceptance commands both return INCOMPLETE/nonzero while stopped; these
expected failures are retained rather than reported as acceptance success.

The successful-prefix capture retained 204 native deliveries and three rebids.
Separate **final-commands.jsonl** and **final-acquisition.json** contain all **220**
deliveries in the complete stopped runtime log and independently verify **four**
rebids, including the original UNKNOWN whose later account participation is
confirmed. A separate immutable final seal preserves this additional capture;
the original prefix and its seal remain unchanged. The stage auditor checks exact
command coverage against the stopped log, actual readback for every bid, and
rejects altered listing outcomes. These remain historical stage outcomes, not a
claim that the final runtime has completed its lifecycle.

Pre-service quiescence and browser projections, a fresh canonical-lock backup,
and a finite launch intent are retained under stage08. Both DB backups passed
integrity/FK and row equality checks. The production journal has 33 ACKNOWLEDGED
and 32 UNKNOWN attempts, eight ACTIVE members, eleven LOST, one WON_ACCOUNTED and
zero pending commands at owner epoch 14. Wall-clock expiry is not settlement.
The next scheduler-owned generation is **2a7a7c6219060321031664a0e4b5d86f**,
service ID **005-sqlite-cache-repair-2a7a7c6219060321031664a0e4b5d86f**,
with epoch floor **15**. After publication, launch it once through the existing
scheduler handoff, immediately verify attachment and fresh account reconciliation,
then continue production. Do not repeat the already confirmed move/list/relist or
prior bids. Any later fault or fix resets the required final uninterrupted 14400
seconds. Current healthy time is zero. No human prerequisite or external blocker
exists; this is continued authorized engineering.


## Stage 09 ? successful sold-item cleanup, persistent denial stop and normal recovery

Scheduler generation **2a7a7c6219060321031664a0e4b5d86f**, epoch 15, launched
**11:25:56 UTC**. Owned supervisor PID 2720 / child PID 7124 made genuine native
requests. Fresh watched/full-version-linked status independently showed all eight
inherited members closed/outbid/not-won; the journal recorded their terminal losses.
No expired wall-clock mapping was treated as settlement or new bidding authority.

The exact earlier owned item **item:4fa51171b8d65f02a7e65198**, paid 3100, was
observed on its same resale auction **closed at current_bid 4300**. The native
**clear_sold 120f19032950b98dcdeb40ffd955e7a2** contract targeted that sole eligible
sold item, preserved unrelated entries, and confirmed its removal in a separate
complete inventory read. Original listing/native readbacks remain sealed in
stage08; stage09/work.json and commands.jsonl retain the sale/cleanup evidence.
This extends the historical win/move/list lifecycle through actual sale and
maintenance. It does not substitute for the required final generation's proof.

The next original-policy batch **6ef9ec1d6736c0885dc92176f7ab014f** dispatched
three initial bids at 750, 800 and 700. Every owned PUT returned wire **461**;
native callback returned **403**, native receipt error **461**, empty native items,
UNCONFIRMED participation and no successful account confirmation. Diagnostics
retain invocation, send, response, callback and ACK chronology separately. Reads
and the preceding clear operation had succeeded, so an HTTP response/heartbeat
alone would have been false health. The third failure was reported at
**11:27:04.474708 UTC**; STOP_REQUESTED followed at **11:27:04.474972**, and STOPPED
at **11:27:06.670769**, exit 0 / forced false. No fourth bid was sent. The three
dispatched and six selected-but-unsent intents remain consumed UNKNOWN. Total
UNKNOWN is **41**, not an assertion that 41 writes reached EA. The service is
stopped and the final healthy interval reset to zero. No native crash recurred
in this short run; that is not four-hour validation of the cache repair.

A fresh canonical-lock backup passed SQLite integrity/FK and row-equality checks.
This worker verified official Edge foreground and navigated normally to the Web
App. A transient Login control disappeared before the attempted click; the helper
rejected the missing exact control and sent no input. The page completed its normal
saved-session load with no challenge. The reviewed extension was reattached at
**11:29:22 UTC**. No credential value, cookie, authentication header/token or EA
session identifier was inspected, retained or changed.

Finite experiment **stage09/after-refresh-one-bid** reserved one mutation and
used unchanged production admission, exact-version completed pricing, limits,
filters and fresh exact status. At epoch 16, new command
**118ad356722de9343285f70598498466** bid **700** on a different target. Its actual
wire/service 200 and matching native ACCEPTED receipt were followed by independent
status and watched account evidence, confirming genuine participation. The probe
closed with **one mutation, 124 commands, 23 reserved EA requests and zero pending
commands**. It did not replay any of the prior uncertain targets. The comparison
establishes currently usable bidding after ordinary recovery. Candidate and document
changed, so it does **not** establish the exact server-side reason for prior 461s,
a blanket account restriction, a new authentication-error classification, or the
outcome of those prior bids. Those causal questions remain explicitly open.

**tests/check_005_stage09.py** independently reparses these native contracts,
full/lite identity links, exact terminal losses, original listing-to-sale identity,
all-eligible sold cleanup, bid policy and post-bid account confirmation. Four
negative cases reject false terminal membership, changed sale price, missing bid
receipt and missing independent participation. It also checks three dispatched
failures, prompt cooperative stop, finite probe closure and protected UNKNOWN
intents. Only captured experiment/EA evidence is sealed. It reports
STAGE_VERIFIED_OBJECTIVE_INCOMPLETE / healthy_seconds 0.

No production implementation changed in this recovery stage. The complete tested
production inventory remains **1120 Python executions, 38 Node suites and nine
independent commands**, with new focused receipts under checks/stage09. Both
actual acceptance validators still return INCOMPLETE while stopped, and their
negative fixtures pass. No incomplete live contract is relabeled as PASS.

The pre-service canonical-lock backup and verified quiescence are retained under
stage09. Safe journal state: **34 ACKNOWLEDGED, 41 UNKNOWN, one ACTIVE member,
19 LOST, one WON_ACCOUNTED, zero pending commands**, persisted epoch 16. Unique
prepared scheduler generation **e4f748f311fbcdaccdfe983600a8726c**, service ID
**005-normal-session-recovery-e4f748f311fbcdaccdfe983600a8726c**, uses epoch floor
**17**. Publish and launch it once through the scheduler, immediately reconcile
and manage the actual 700-coin member, then continue original-policy production.
Earlier UNKNOWN commands and completed move/list/bulk operations must not replay.
Any new fault requires preservation, safe stop, diagnosis and repair. Final genuine
lifecycle and **14400 consecutive healthy seconds remain unproven**; there is no
verified external barrier or human prerequisite.


## Stage 10 ? genuine restarted management and monitoring handoff

Generation **e4f748f311fbcdaccdfe983600a8726c** launched through the existing
scheduler at **11:36:18 UTC**, owner epoch **17**. Ownership is supervisor PID
**19088**, creation FILETIME **134393889782388626**, and child PID **1872**,
creation FILETIME **134393889786235899**, both the reviewed Python313 image.
Exclusive runtime lock and current process identities were independently checked.
The restart reestablished exact current membership through native watched and
full/lite linked status, then managed the genuine 700-coin member from stage09.

Actual competition led to **rebid 59abe62de9f8971e732996e209630158** at **1600**,
with original stored cap **4300**. Its pre-status was active/outbid, below the
new minimum; native wire/service 200 and exact matching ACCEPTED receipt were
followed by independent highest/current-1600 reads. The retained successful prefix
contains **31 native deliveries** and **eleven post-rebid confirmations**. No
new initial or earlier UNKNOWN bid was replayed. The controller remains in its
single sequential MANAGING phase with genuine fresh native reads and no semantic
error streaks. The child fault trace was empty at capture; this is a short healthy
prefix, not four-hour crash-proof evidence.

**tests/check_005_stage10.py** reparses immutable command/diagnostic evidence,
original confirmed-member identity, unchanged stored cap, fresh competitive
prerequisite and independent participation. Three negative cases reject a missing
receipt, altered cap and missing post-bid account participation. The capture also
checks unique deliveries, single-phase management, ownership and semantic health.
It reports STAGE_VERIFIED_OBJECTIVE_INCOMPLETE. It cannot pass the final objective.

The existing full tested production inventory remains **1120 Python executions,
38 Node suites and nine independent commands**. This checkpoint changes proof
auditors/documentation only. Focused receipts retain stage09/10 artifact checks,
both final validators' negative fixtures, and actual final validator failures:
criterion 0 **full_genuine_lifecycle_not_observed**, criterion 1
**scheduler_interval_incomplete**. At approximately **11:38:50 UTC** the independent
scheduler state showed **121.29 healthy seconds**, same generation and scheduler
epoch, faulted false. This interval is explicitly less than the required 14400.
The final generation still needs its own genuine acquisition-to-resale outcomes.

After publication, leave this exact service running and return the existing
30-second semantic monitor; **no new service launch or startup grace** is requested.
The scheduler retains health samples without AI quota and resumes the same worker
for actual faults or completion assessment. A fault/stop/restart/monitor gap resets
the interval. Market waiting does not establish a blocker. If required real events
have not occurred after four hours, continue safe monitoring. Independently audit
the full final lifecycle and interval before done; preserve uncertainty about the
historical 461 server causes. **41 earlier UNKNOWN intents remain protected**.
No external barrier or human prerequisite is established.


## Stage 11 ? preserve native read renewal without retrying failed requests

### Genuine incident and safe state

The complete stopped run of generation **e4f748f311fbcdaccdfe983600a8726c** is
retained separately from stage10's unchanged successful prefix. It contains
**298 logical native/helper deliveries**, **274 successful native operations**,
and four actual rebids at **1600, 1800, 2000 and 2200**. Each has a matching
native receipt and later independent highest readbacks. Competition eventually
reached **4900**, above stored cap **4300**; no unaffordable rebid was sent.
Fresh status **c1cd5f526fc802cbabd6a9b99bcc992c** independently observed the exact
member closed/outbid/not-won, after which the journal settled it LOST.

One earlier status command **3f7d4e5808d5672c92b0df9bf623b21f** received a service
callback200 with **no owned request**. It remained UNKNOWN/ambiguous_network and
granted no fresh-read, participation or settlement proof. Later separately
journaled native reads recovered. A native cache/coalescing origin is a hypothesis;
the missing owned send cannot be reconstructed into a confirmed outcome.

Balance **67cb333ebb906a8cdc6df1e47fd79c0d** succeeded with actual wire/service200
at **11:47:30 UTC**. Next discovery **fe24ab38f77b62a112fd295e785bd2a1** returned
wire/service401, followed by balance **7fd2deee68b00bf8d94b2f2b88b1586a** returning
wire/service401. Account, persona, document and owner fences did not change.
Failed legacy reads intentionally lack a successful-read network_at; their
owned EA_RESPONSE diagnostic timestamps establish the actual transition instead
of fabricated freshness. Authentication-header presence is a boolean, not proof
that authentication remained valid. No header value or EA session identifier was
inspected. The initial server-side invalidation/expiry trigger remains unproven.

The second auth failure was reported **11:47:34.245522 UTC**, STOP_REQUESTED
followed **11:47:34.245872**, and STOPPED **11:47:35.947403**, exit 0 / forced false.
The scheduler retained **22 healthy samples**, peaking at **621.6986 seconds**,
then reset to **zero**. The owned stop acknowledged both identities exited.
Quota waiting left the broken runtime stopped until this same worker resumed.
No native crash recurred during this short run. Safe journal: **38 ACKNOWLEDGED,
41 UNKNOWN, 20 LOST, one WON_ACCOUNTED, no active members or pending commands**.
Fresh canonical-lock backups passed SQLite integrity/FK and row comparisons.

### Root defect, repair and limits

Both controller.js and the controller-mode shared page bridge forced
**doReauth=false** on every finite request. The native client normally enables
renewal for requests with an authentication delegate. The current official
[public native client](https://www.ea.com/ea-sports-fc/ultimate-team/web-app/js/ocompiled.js)
shows _handleFail starting ordinary UTAS renewal on a 401, then _handleReauth and
handleTelemetry honoring doRetry. With **doRetry=false**, native renewal does
**not** replay the original request: it reports that original failure through
_notify. A later independently journaled read must establish success. This
mechanism was reproduced with the captured public native functions and shipped
bridge, synthetic HTTP/native observables and credential-access traps. No browser
or authentication values are present in those offline fixtures.

The read adapter now preserves **only an already-enabled native renewal flag**
for pure balance/watch/status and shared search/caps/owned-inventory reads.
Native opt-out remains disabled. **All automatic request retries remain off**;
bids and every move/list/bulk mutation lineage also keep renewal disabled.
The first read401 remains failed and cannot supply balance, quote, ownership or
membership authority. Existing failure streak/freshness/stop thresholds remain
in force. This is normal native session maintenance, not direct authentication
API calls, credential handling, challenge bypass, write replay or changed global
security policy. It repairs a proven reason that ordinary renewal was suppressed;
it does not establish why the server first rejected that particular session.
Historical 461 denial causes also remain explicitly open.

A private wrapper retains **NATIVE_RENEWAL_RESULT** only when the native
observable completes the UTAS environment, with a single **success boolean**.
An unrelated authentication environment's early success cannot claim UTAS
recovery. Native callback hooks are restored. No authentication response object,
header, cookie, token, credential, EA session ID or arbitrary exception is retained.
This metadata does not count as a native trading success or fresh account proof.

### Verification and genuine baselines

The pre-fix regression retained zero native renewal calls despite an enabled
native default. After repair the same scenario renews once, reports original
read401 unchanged and succeeds only on a separate new read. Final verification:
**1121 Python test executions**, **39 Node suites**, **nine independent commands**,
all passing. Eleven focused renewal cases cover native opt-out, failed renewal,
request no-replay, mutation no-renewal, restoration, privacy and wrong-environment
false-success rejection. Red/green/final receipts remain separate under
checks/stage11; no red history or failed live evidence was rewritten.

**tests/check_005_stage11.py** reparses every captured delivery and native
readback, all four rebids, actual terminal loss, coherent auth failures, prompt
stop and protected journal state. Four negative cases reject missing receipt,
changed wire auth status, life-only stop reason and promotion of the unowned
callback to success. Only immutable captured native/experiment/public-method
projections are sealed; mutable implementation files are not hashed or pinned.

This worker used ordinary official Edge UI recovery: verified foreground,
reviewed extension reload, normal app navigation, designated saved-account
selection through autofill, NEXT and standard password submission controls.
Credential values were never read. No security challenge, restriction or absent
desktop access was observed. Both **read-after-repair** and final **read-final**
windows independently passed **six commands / ten exact targets / zero missing**,
with **zero mutations and pending work**, and closed their local service. The final
window followed reload of the complete instrumented repair, native owner epoch
**19**. Captured contracts and typed diagnostics are independently reparsed.
These are genuine native-read baselines; no forced expiry or successful live
renewal is claimed. Actual renewal and sustained trading must be observed in the
next monitored run. Both final acceptance criteria remain incomplete.

### Next operational run

Production DB fencing remains epoch **17**, while the isolated read-only native
window used epoch **19**. The next unique scheduler launch therefore requires
**epoch floor 20**, fresh actual account reconciliation and unchanged production
policy. Fresh pre-service quiescence/backup/browser evidence and finite launch
intent are retained under stage11 before dispatch. No previous UNKNOWN bid
or completed move/list/bulk action may replay. Any operational failure, stop,
restart or monitored gap resets the required interval. Continue autonomous repair
if needed; leave the eventual healthy runtime running. **Live renewal recovery,
final-generation full lifecycle and 14400 consecutive healthy seconds remain
unproven. No external barrier or human prerequisite is established.**

Prepared generation **718d2acbcab1b4d9cdcb75d7e0035b70**, service ID
**005-native-read-renewal-718d2acbcab1b4d9cdcb75d7e0035b70**, is not yet dispatched or consumed. Its
canonical backup passed integrity/FK/row-equality comparisons. The official browser
snapshot shows no challenge and a usable foreground app; actual fresh read success
is established separately by the six-command final native window. Read-only legacy
objective checks confirm Objective 003 PAUSED and Objective 004 COMPLETED.

The existing scheduler will launch the following reviewed public argv once through
this task's service handoff. This PowerShell spelling documents the corrected
controller-under-watchdog launch; persistent execution for this objective remains
scheduler-owned. Its exclusive owner lock and consumed generation directory reject
a second launch.

```powershell
Set-Location C:/hustle/fc-hustle
$fcPython = 'C:/hustle/agent-orchestrator/.venv/Scripts/python.exe'
$fcGeneration = '718d2acbcab1b4d9cdcb75d7e0035b70'
& $fcPython -m fc_access.controller_v1.operational service --runtime-dir private-captures/controller-v1/operational --task-key obj-cb39371c785a/operate --generation $fcGeneration --database private-captures/controller-v1/controller.sqlite --cache private-captures/controller-v1/quotes.sqlite --context private-captures/controller-v1/public-context.json --port 8784 --epoch-floor 20
# Inspect the actual generation:
& $fcPython -m fc_access.controller_v1.operational health --runtime-dir private-captures/controller-v1/operational --task-key obj-cb39371c785a/operate --generation $fcGeneration
# Cooperatively stop only this generation:
& $fcPython -m fc_access.controller_v1.operational stop --runtime-dir private-captures/controller-v1/operational --task-key obj-cb39371c785a/operate --generation $fcGeneration
# Resume the existing objective only if it was explicitly paused:
& C:/hustle/agent-orchestrator/.venv/Scripts/orchestrator.exe --db C:/hustle/fc-hustle/.orchestrator/state.db resume obj-cb39371c785a
```

Focused-final receipts include the four corrupted-evidence cases, typed diagnostic
privacy tests and both acceptance validators' negative fixtures. The real criteria
0/1 commands still return INCOMPLETE/nonzero while this service is stopped. The
new runtime must establish actual native trading/resale behavior, genuine recovery
if renewal occurs, and the uninterrupted four-hour semantic interval before done.

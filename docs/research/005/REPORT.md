# Objective 005 production repair

Status: **IN PROGRESS. No integrated trading run or four-hour proof yet.**
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

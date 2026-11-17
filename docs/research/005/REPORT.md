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

# 004-01 baseline and controller contract boundaries

Status: **004-01 COMPLETE — BASELINE BACKED UP / DESIGN VERIFIED**. The new
controller is not implemented by this task. No EA requests, account mutations,
browser recovery, production migrations, controller runs or legacy actors were
started. Implementation continues in 004-02 through 004-05 under the complete
[Objective 004 contract](../../../../objectives/004-single-controller-implementation.md).

## Preserved current baseline

Initial branch was `main`, revision
`8981096cc2bccb9bfbcb64debc14e08a7f0e71e8`; the initial Git tree was clean.
The collector's subsequent status contains only its own new
`tests/baseline_00401.py`. This revision is descriptive provenance, never a test
that mutable source files must retain old bytes. No unrelated tracked or
untracked work required replacement or removal.

The exclusive backup completed at 2026-11-16T15:22:26Z in
`C:/hustle/fc-hustle-backups/004-01-20261116T152219Z`. It contains:

- `working-tree.zip`: all 2,697 tracked working-tree files at capture, including
  historical documentation/evidence and the current implementation.
- `repository.bundle`: complete Git history/all refs, independently verifiable
  by `git bundle verify`; `working-tree.patch` is empty at this clean baseline.
- Seven consistent SQLite online-backup copies, with schema and table counts
  recorded in [baseline.json](baseline.json). Sources are the final-remediation
  Foundation journal, quote cache, native and transport stores; continuous
  native/control stores; and the latest bulk/production transport store.
- `legacy-control.json`: read-only projections of Objective 002/003 controls,
  tasks, dependencies, validator definitions and turn/event/artifact metadata.
  Opaque session/payload columns and the raw orchestrator DB were excluded.

The application DB producers were reviewed: their retained public account
pseudonyms and owner/document fences are application identity, not EA credentials
or session secrets. The backup uses the SQLite backup API rather than copying a
main DB without its WAL. No application constructor was opened against live
state: Store constructors rewrite restart state, and Journal can install schemas.
The only source connections were SQLite `mode=ro` plus `query_only`; readers can
touch SQLite shared-memory bookkeeping without changing logical account records.

Edge profiles, saved credentials, cookies, headers, EA tokens/session IDs,
unreviewed private captures and raw orchestrator payloads were neither opened
nor copied. Raw command lines were classified inside PowerShell and never
printed or retained. Public process IDs/names, classification booleans and
native-service listener ownership are retained. The initial scan found no
competing Python production worker and no listener on 8780–8799. Independent
final checks also attempt the existing canonical owner/native/actor process
guards nonblockingly without creating or rewriting their lock files.

Recovery after the supervisor interruption inspected the existing destination
and confirmed the original backup was complete; the collector was not replayed.
All seven SQLite copies were present, the complete Git bundle verified, and the
legacy control projection remained unchanged. Current application state is
checked against logical backup rows rather than SQLite file bytes.

Current local journal facts differ from the old reports: all 69 bid commands
are RECONCILED, and all six bulk intents are RECONCILED. Historical capacity
slots still include two UNRESOLVED records; these were not inferred away or
migrated. The continuous native mailbox contains 2,342 DONE and six UNKNOWN
commands, with no queued live worker inferred from those historical rows. The
last control event is RUN_STOPPED at 2026-11-16T13:14:34.605391Z. These are durable
local facts, not fresh observations of the current EA account or inventory.

## Legacy objectives and evidence

Objective `obj-da182a175410` remains `PAUSED`, control `pause`. Task `003-04`
retains its existing `RECONCILING` state and null task control under the paused
parent. It would be incorrect to edit the task row to spell PAUSED: preserving
the user's pause requires leaving its orchestration checkpoint untouched. No
resume, recheck, completion, replacement or orchestration mutation was issued.
Objective `obj-29bea3b74eb3` remains BLOCKED; 002-12's published verdict remains
`PARTIAL/NOT FULL PASS`. Historical runs, incidents, consumed budgets and evidence
retain their original meanings and archived recoverable copies.

The validators compare only safe legacy control projections and durable account
records. They also compare sealed historical JSONL observations, REPORTs,
outcomes, incidents and durable-ledger evidence with the captured archive.
They do not assert hashes or byte identity of mutable source, tests,
instructions, configuration or implementation files. Historical source hashes
remain provenance only. No deferred orchestrator changes are part of this task.

## Design and policy coverage

[Controller design](../../../../fc_access/controller_v1/DESIGN.md) describes the
new orchestration/state/config/API boundary, exact imports, shared seams and
affected legacy callers. [reuse.json](reuse.json) makes the symbol and caller map
checkable against the actual Python API. The architecture imports proven pricing,
native limits/increments, identity and ownership primitives and verified outcome
validators; it replaces the policy-bearing actor loops and batch admission.
Legacy per-bid credits freshness, unresolved-command gates, page poisoning and
supervisor stop behavior remain explicit legacy defaults.

Exactly ACQUIRING and MANAGING are operational phases. RUNNING, STOPPED, PAUSED
and HALTED are separate lifecycle controls. A trusted server-side BatchAuthority
validates durable account/batch/decision records; a client flag cannot turn on
writes. One canonical cross-mode account owner and one serialized executor
remain. New-mode state lives in a separate additive SQLite file. No live test
migration or compatibility data conversion has occurred.

[storage.sql](storage.sql) is a draft schema exercised only in new temporary
databases. It covers phase/lifecycle, batch, candidate, stored quote/cap,
observations, confirmed membership, deadlines, commands/results, permanent
tombstones, physical resale, transitions and probe windows. SQL enforces key
uniqueness, ten-slot bounds, foreign keys, immutable intents/quotes, append-only
results/tombstones and irreversible consumed probe budgets. Admission provenance,
scope/epoch agreement, independent evidence and atomic claim+tombstone are
explicit future authority responsibilities, not claims that SQL alone implements
the controller. Short transactions commit before awaited native I/O.

[plan.json](plan.json) contains 32 requirement rows, each with an implementation
task, acceptance indexes, expected observations and negative cases. It covers
all agreed numeric defaults and the detailed acquisition, status attribution,
management, uncertainty, restart, resale, maintenance and final handoff rules.
Central EA request spacing starts at two seconds and remains configurable;
local-only helpers consume zero EA slots. Two seconds is not claimed to be an
EA-required safe rate. All offline future tests must use isolated state, account
fixtures and loopback ports. The schema/pacing examples here are design and
reusable-mechanism proof, not controller acceptance or live-account proof.

## Targeted live verification boundary

[probes.json](probes.json) defines eight separate future finite windows. Only
the read-only native exact-target multi-ID status contract check is required;
the others activate only when changed seams genuinely need live evidence.
Each has a concrete question, trigger, deadline, operation-by-operation request
and mutation budget, exclusive durable checkpoint and recorded cleanup.
Budgets include possible native internal requests. Requests/mutations are
reserved before dispatch; ambiguous or interrupted operations remain consumed.
Pre-mutation intent precedes every write; independent readbacks classify each
outcome. No probe was executed in 004-01 and no checkpoint was pre-consumed.

The multi-ID check must report actual retained requested/returned/omitted targets,
up to ten when naturally available; fewer than two cannot prove multi-ID behavior.
Fixtures never become live proof. Security challenges and missing natural market
conditions are explicit external limitations. Implementation defects require
offline repair and a separately recorded new bounded window. Prior bid receipt,
production incident and bulk windows must never be reset or replayed.

Autonomous controllers, legacy actors, scheduled jobs, full-batch lifecycle E2E
and soaks remain prohibited throughout Objective 004. Final source/report
publication and the verdict IMPLEMENTATION COMPLETE — FULL CONTROLLER E2E PENDING
belong to 004-05 after the actual implementation and required verification. This
task leaves production stopped and supplies no permission to launch the full E2E.

## Verification

Verification is recorded in [verification.json](verification.json), with captured
outputs under [checks](checks). All nine recorded final commands exited zero:

| Check | Result |
| --- | --- |
| New design/negative/storage/pacing/lock tests | 19 tests passed |
| Independent artifact and preservation validator | PASS; seven DB backups, 155 historical evidence files, six idle locks |
| Existing pricing tests | 17 passed |
| Existing Foundation tests | 16 passed |
| Existing receipt tests | 11 passed |
| Existing bulk integration tests | 20 passed |
| Actual production page and native-status Node suites | Both passed |
| Git whitespace check | Passed; existing tracked tree unchanged |

That is 83 Python tests, zero failures/errors, plus two Node suites. This is
focused baseline/reuse verification; complete current suite discovery remains
004-05 work. No production implementation changed in this task. Independently
repeatable commands from the workspace are:

- `python tests/check_00401_artifacts.py`: recoverability, read-only process/lock/
  database/control preservation, historical evidence and design/probe coverage.
- `python tests/test_00401_design.py`: negative artifact cases, draft SQL design
  constraints and recovery, independent SQLite writer during suspended I/O,
  actual imported executor/helper cadence at two/three seconds, and a competing
  fixture process rejected by the reused process lock.

The validation commands never call the baseline collector, install a schema in
live state, contact EA, recover Edge or start a controller. Future runtime tests
must still exercise actual controller/page/worker/transport code after it exists;
these design tests do not replace the remaining Objective 004 implementation.

The first artifact run caught a collector metadata error: `tracked_entries=2698`
included the empty entry after Git's trailing NUL. The archive actually contains
all 2,697 tracked filenames, verified against the captured Git tree. The original
baseline receipt remains unchanged; the collector now excludes empty entries and
refuses a second capture before creating any backup directory. No backup content
or baseline window was regenerated to repair this descriptive count.

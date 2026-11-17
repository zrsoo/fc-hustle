# Objective 005 bootstrap — orchestrator support

2026-11-17. This is the launch/setup record, **not** production-controller
remediation or a four-hour PASS. The autonomous worker maintains
`docs/research/005/REPORT.md` with real fixes and live results.

## Why changes were required

The previous orchestrator could reread quota and resume saved sessions, but
ordinary worker `blocked` immediately became terminal, repeated unchanged-file
failure episodes could block, and fixed DAG turns had no durable quota-free
operational monitoring handoff. Provider job cleanup could also kill a consumer
launched as its tool descendant. Editing an objective file alone did not change
its saved task graph or scheduling lifecycle.

Implemented opt-in operational objectives in the standalone orchestrator:

- `submit --autonomous --healthy-seconds 14400` saves the original contract and
  creates one persistent `operate` task/session. The worker updates its working
  plan in the objective file, without replacing original acceptance.
- `continue` returns to repair automatically. Proposed blockers require a
  separate same-session external recovery assessment and retained evidence.
  Ordinary coding/operational failures do not require a user recheck.
- `monitoring` registers bounded deterministic health/stop commands. They run
  independently of AI quota, including via control callbacks during turns.
  Faults stop the owned consumer and retain pending repair. Authoritative quota
  recovery resumes that same worker automatically.
- Scheduler-owned service launches persist unique intent before dispatch and
  never replay a consumed/uncertain launch ID. Consumers run outside Codex's
  ephemeral provider job. Consumer runtime lock, semantic watchdog and owned
  stop/reconciliation interface are explicit Objective 005 implementation work.
- Monotonic healthy duration resets on faults, generation changes, scheduler
  restarts and unmonitored gaps. Fresh health plus independent validators are
  required for completion. Healthy services remain running at the final handoff.
- Existing objectives retain their original DAGs, controls and failure policy.

Canonical generic contract:
`C:/hustle/agent-orchestrator/docs/autonomous-operations.md`.

## Preserved state

FC main started at `fa266a3`; orchestrator main at `713e3cb`. The pre-existing
IMP-004 documentation is preserved and updated with the authorized implementation.
No production Python controller, localhost FC service or scheduler was active
when backups were made. Exclusive orchestrator service lock/probe checked.

Backup directory outside Git:
`C:/hustle/orchestrator-migration-evidence/autonomous-20261117T003234Z/`.
SQLite backup API, `integrity_check=ok`, no FK violations and every original table
compared row-for-row for `state.db`, `controller.sqlite`, `quotes.sqlite`.

Original orchestration rows: seven objectives, 50 tasks, 43 dependencies, 80
turns, 594019 events, 348 artifacts, 138 validators. Objective 003 remains PAUSED;
004 remains COMPLETED; historical 002 remains BLOCKED. No historical state reset.
FC DB: 302 commands, 905 events, 41 policy batches, 19 candidates/attempts/
tombstones, zero managed members, 61 metrics. Quote DB: ten completed quotes.

## Verification

In `C:/hustle/agent-orchestrator`:

- `.venv/Scripts/python -m pip check`: no broken requirements.
- `.venv/Scripts/python -m pytest tests -q -m "not live"`:
  209 passed, one optional historical incident replay skipped, three live tests
  deselected, three subtests passed (169.07 seconds).
- `.venv/Scripts/python scripts/test_m1_recheck_startup.py`:
  63 passed (57.87 seconds).
- Expanded `.venv/Scripts/python -m pytest tests/test_operations.py tests/test_lifecycle.py tests/test_recovery_prompt.py -q -m "not live"`:
  84 passed, one optional historical replay skipped (60.65 seconds).
- First integrated CLI run: its 209 tests passed, but the runner rejected its
  evidence because source edits occurred concurrently. No functional assertion
  failed; that run is not counted as accepted integrated verification. The
  frozen-source repeat result is recorded below before launch.

Final frozen-source `.venv/Scripts/python scripts/test_m1_integrated_cli.py`
with `ORCHESTRATOR_M1_EVIDENCE=reports/m1/autonomous-frozen-20261117`:
**216 passed, one optional historical replay skipped, three live-inference tests
deselected, three subtests passed in 178.63 seconds; integrated runner exit 0.**
The expanded operations suite independently passed all 26 tests (21.03 seconds),
including bounded startup grace, subsequent browser attachment and no startup
time counted as healthy. An intermediate 213-test run also passed its tests but
was invalidated by concurrent source changes; only the final frozen run is
accepted as integrated evidence.

Additional real Windows process experiment: assigned a disposable provider to
the production `ProcessTree` job, launched a disposable consumer through the
scheduler, closed the provider job, verified provider exit and consumer survival,
then verified consumer cooperative exit. No real account/model was involved.
Retained locally: `agent-orchestrator/reports/autonomous-real-job-proof.json`.

Migrated an isolated copy of the actual pre-change production backup: every
original column and row in all seven tables retained; integrity/FK checks passed;
all seven historical objectives remained opted out. Scratch DB was closed and
removed. A first scratch cleanup hit an open SQLite handle after its assertions
passed; the corrected repeat closed connections and exited 0.
Retained locally: `agent-orchestrator/reports/autonomous-migration-proof.json`.

Fixtures use isolated DBs/workspaces, real bounded child processes and fake
providers. These do not prove FC authentication or real trading. Objective 005
must implement domain health checks and prove actual production outcomes.

## Submission and current status

Objective source: `objectives/005-controller-production-reliability.md`.
Submit only once, with the existing FC orchestrator DB. Detached scheduler must
acknowledge live exclusive ownership. Record ID/PID and worker activity below.
No FC production fix or live validation is claimed by this bootstrap record.

Submitted once as **`obj-cb39371c785a`**, autonomous mode, required health 14400
seconds. Generic orchestrator implementation committed/pushed on main as
`4f9d5f1`. Submission was made under the exclusive service lock, with no live
scheduler and an explicit duplicate-objective check. Initial status PENDING;
the scheduler is launched only after committing/pushing this objective/report.
The runtime-only `.orchestrator/005-launch.json` records acknowledgement and PID.

Launch (already submitted; **do not resubmit**):

```powershell
& C:/hustle/agent-orchestrator/.venv/Scripts/orchestrator.exe --db C:/hustle/fc-hustle/.orchestrator/state.db run --detach --poll 10
```

Observe state in a separate PowerShell window:

```powershell
& C:/hustle/agent-orchestrator/.venv/Scripts/orchestrator.exe --db C:/hustle/fc-hustle/.orchestrator/state.db status
Get-Content C:/hustle/fc-hustle/.orchestrator/service.log -Tail 40 -Wait
```

The selected objective should move PENDING → RUNNING while diagnosing/repairing,
then task MONITORING with consecutive health progress. WAITING_QUOTA resumes
automatically. Monitor status does not by itself prove FC repair or completion.
Its semantic health interface and exact watchdog launch instructions are worker
deliverables, documented in `docs/research/005/REPORT.md` when verified.

Healthy trading continues during AI quota waits; repairs requiring AI wait for
quota to return. EA challenges/account restrictions and unavailable desktop
access can still require an external action. Neither unattended completion nor
market wins can be guaranteed; evidence must stay accurate.

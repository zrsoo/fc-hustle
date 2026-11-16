# Single-controller minimal watchdog

Date: 2026-11-16. Base: `8fb841877a5df4b0930d8fab9564d99a379679e8`.

## Scope

The user requested process supervision and a visible status line for the new
single controller. This change adds those to the existing explicit
`python -m fc_access.controller_v1 run` command. No live controller was started,
no browser was attached and no EA request or account mutation was performed.
Original objectives, evidence, checkpoints and legacy runtimes are unchanged.

One local parent supervises one controller worker. The worker retains the
existing account/native/port/database locks, service, native executor and trading
policy. There is no automatic restart, GUI, notification service, additional EA
polling, scheduled job or orchestrator change.

## Implementation and fault policy

- `watchdog.py`: Windows-spawn-compatible parent/worker IPC, supervision leases,
  monotonic progress deadlines, a refreshing terminal line and one unique
  local event log per invocation. Only exception types and stack locations are
  retained, never arbitrary exception text, locals or authentication material.
- `__main__.py`: the existing run CLI launches supervision; the worker owns
  the original runtime. Status/pause/stop retain their existing contracts.
- `executor.py`: optional reports around actual attachment and finite native
  calls; no extra native call, retry or pacing change.
- `controller.py` and `store.py`: supervision checked at policy step, dispatch,
  enqueue and claim. The existing dispatch guard still checks after pacing.
  Lightweight state projections keep the phase/managed count current at native
  boundaries, including handoff within one step.

| Condition | Behavior |
| --- | --- |
| Worker exits/crashes or reports an unhandled exception | Stop and retain the reason/stack locations |
| Controller HALTED, PAUSED or STOPPED | End supervised execution, preserving the controller reason |
| Startup/attachment makes no progress for over 90 seconds | Stop |
| One native transport call makes no progress for over 45 seconds | Stop; existing underlying transport timeout remains 30 seconds |
| Local work makes no progress for over 60 seconds | Stop |
| Supervisor pipe closes or its lease is older than 10 seconds | Worker refuses further steps, dispatch, enqueue and claim |
| Watchdog status output or event logging fails | Stop the worker |
| Rejection, outbid, expiry, missing row, ambiguous outcome | Retain existing non-blocking policy and durable evidence |
| Management exceeds its five-second target | Continue sequentially; no overlap or cycle-duration watchdog limit |

The parent polls every 0.5 seconds. Work boundaries, rather than a background
heartbeat thread, reset progress deadlines. A long acquisition or 26-second
management cycle therefore remains healthy while finite calls progress.
The watchdog does not duplicate bid/pricing/listing validation or infer every
logic defect. Repeated handled failures can remain live progress and require
journal inspection.

## Stop and operator visibility

The terminal shows STARTING/RUNNING, phase, current operation, managed count and
stage age. A fault or operator Ctrl+C changes it to STOPPING, then STOPPED with
the reason only after worker exit is verified. A failure to terminate is shown
as STOP_FAILED. No restart is automatic.

The parent withdraws permission and allows 35 seconds for the current call and
cleanup, then terminates only its own stuck worker. An already-issued EA write
cannot be undone; its outcome can remain uncertain. Existing durable intent,
tombstone and restart recovery behavior remains intact. Following forced
termination, SQLite can retain a RUNNING lifecycle from before the crash; the
watchdog's verified process-exit record describes whether that run is stopped.

Each run prints its log path before startup:
`<database directory>/watchdog-runs/<UTC-random>/events.jsonl`.
Start, stop-request and final records are flushed/synced when storage permits.
The database, cache and historical logs are never reset. Ordinary pause/stop
still drain native work; restart requires an explicit new run and normal
owner/document reattachment.

## Verification

The final dedicated watchdog regression run passes 13 tests. It covers real
Windows subprocess crash/stall/HALT,
Ctrl+C drain, supervisor death, lease withdrawal before claim and after pacing,
unknown/rejected/missing outcomes continuing without replay, phase handoff,
long progressing work, failed status/log output and sanitized fatal diagnostics.

The first process tests exposed Windows `Pipe.poll()` raising BrokenPipeError
after child exit. The drain helper now handles both polling and receive closure
without losing the retained controller reason. Follow-up process checks pass.

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | PASS: 1061 executions, 1044 distinct methods, zero failures/errors/skips; 473.264 seconds wall time |
| `python tests/test_controller_watchdog.py` | PASS: final 13 watchdog tests, 5.692 seconds |
| `python -m unittest discover -s tests -p 'test_004*.py' -v` | PASS: 90 controller/design/handoff tests, 117.200 seconds |
| All `tests/*checks.cjs`, via `python tests/record_00405.py node <new-output-directory>` | PASS: 33 Node suites |
| `python tests/record_00405.py independent <new-output-directory>` | PASS: nine independent validation commands |
| `powershell -NoProfile -File tests/collect_00405_state.ps1` | No production workers, listeners or scheduled mutation jobs at 20:25:47 UTC |
| `git diff --check` | PASS |

Full discovery started with 12 watchdog tests; the final phase-display handoff
regression and final watchdog refinements were verified by the 13-test follow-up
and the controller subset. The separate commands overlap; counts must not be
summed as distinct tests. The 90-test controller subset and final watchdog run
cover the final implementation. No old test or functional assertion was removed,
skipped or weakened.

Fresh full Python, all Node suites and independent validators are recorded
separately under
`private-captures/controller-watchdog-verification/20261116T201722Z`, using the
existing offline `tests/record_00405.py` recorder without changing its historical
outputs. The nine commands are the two 004 artifact gates, retained 002-03 gate
and stop validators for `20261114-adapter-repair-gate-06`, adapter repair, bulk
blocker recovery, 003 baseline, 003 production prepublication and sealed bulk
transfer evidence. Those validators inspect retained evidence, not live EA.

Result: minimal supervision is implemented and offline verified. Live trading
remains stopped. This is not a live trading E2E claim.

# 003-01 baseline review and read-only reconciliation

The Objective 002 baseline is preserved on `main` as
`413d21ad0a5d976572f2c488524f1a23d8a44340` (`obj002`). It was already committed
and published when this task started. The working tree was clean. This task
independently reviewed and tested that commit and adds its review/evidence in a
separate commit; it does not amend, duplicate or rewrite the user's baseline.
No trading actor, maintenance job or Objective 002 continuation was launched.

Required instructions, both objectives, production/actor modules and handoff
reports are enumerated with substantive read notes in [provenance.json](provenance.json).
The older blocker-repair report's instruction to request an Objective 002 recheck
is superseded by Objective 003's explicit prohibition.

## Preservation and ownership

The submission backup at
`private-captures/003-handoff/20261115T151935Z/` was inspected directly: its Git
bundle verifies, the binary tracked patch describes nine changed paths, its ZIP
passes CRC checks and contains 44 pending files, and all five SQLite backups
pass `PRAGMA integrity_check`. All 44 archived paths are tracked in the separately
published baseline. The patch's production changes were reviewed alongside the
actual committed diff, rather than assuming the bundle contained uncommitted work.

Before modifications, a new backup was made at
`private-captures/003-01/20261115T153459Z/`. It contains an independently verified
all-ref Git bundle, binary working-tree/index diffs, working-tree status, an
untracked archive, and SQLite online backups of the foundation journal, completed
quotes, actor mailbox, production transport and orchestrator state. Each database
passes integrity checking. No actor was running at that point, so the three
related actor databases also form a quiescent restore point. The orchestrator
backup is a consistent transactional snapshot of an active controller, not a
claim that all five files share one cross-database transaction.

The backup includes a historical evidence inventory. Integrity checks apply to
sealed captures/reports and experiment evidence, never mutable implementation,
tests, instructions or the current series selector. Git ancestry and explicit
changed-path checks preserve unrelated tracked work. No historical file was
rewritten, deleted or promoted to PASS.

Initial process inspection found the old discovery service (PID 12008), dashboards
and the current orchestrator, with no live actor stack. The discovery service was
stopped and its exit awaited before starting the production read-only service
(PID 1372, port 8784). The orchestrator running this new objective and dashboards
were retained. Offline regression tests temporarily spawn fixture actors; these
are identified separately from production ownership and exit under their tests.
[process-ownership.json](process-ownership.json) records both scans and the
stop/await/start order. Public owner epoch 63 fences the new read-only attachment;
the actor mailbox's consumed epoch 60 is preserved, not reset or reused.

Edge's first normal foreground attempt failed. The existing
`.orchestrator/focus_edge.ps1` recovery helper then verified actual foreground
control by this worker. The official Web App tab was selected and the reviewed
production extension attached. [desktop-preflight.json](desktop-preflight.json)
records independent window/tab/foreground verification. No login was needed and
no credentials, cookies, authentication headers or session identifiers were read
or exported. The production server has no journal mutation authority.

## Independent baseline review

[review.json](review.json) records the reviewed commit, parent, pending paths,
production findings and limitations. The post-list wrapper permits precisely the
native auxiliary status read bound to the newly assigned auction of the exact
physical item. Duplicate reads/writes, foreign mutations, wrong trades/hosts and
read bodies are covered by negative tests. The Python protocol checks the same
sanitized item mapping and auxiliary count. Series assessment joins captures to
separate durable mailbox/transport destinations and retains original errors,
unknown effects and missing live proofs. Gross sale observations remain distinct
from attributable realized profit.

Independently rerun against the reviewed baseline:

- All 744 Python tests passed in 173.532 seconds. [python-baseline.json](python-baseline.json)
  contains the exact observed completion summary; it does not claim a separate
  full log for that first streamed run.
- All 27 `tests/*checks.cjs` Node suites passed, including the post-list negative
  cases. Commands and captured outputs are in [node-baseline.json](node-baseline.json).
- The consumed sixth pricing gate/stop validators, adapter repair validator and
  bulk blocker artifact validator passed independently, with zero live requests.
  See [independent-baseline.json](independent-baseline.json).

These are offline baseline checks, not an orchestrator recheck or a replay of a
live Objective 002 window. After adding this task's 13 checks, full discovery
passed **757 tests** in 174.909 seconds, with its complete output retained in
[python-task.txt](python-task.txt) and result in [python-task.json](python-task.json).

## Fresh account reconciliation

[native-opening.jsonl](native-opening.jsonl) contains four distinct, hash-chained
official native GET results, paced at least two seconds apart, collected from
15:37:52 through 15:37:59 UTC on 2026-11-15. Each is authenticated, successful and
fresh at collection. Each command/response is independently matched against the
production transport database. This capture is a new Objective 003 read-only
record, not a reset or continuation of any Objective 002 experiment.

The exact account/persona/platform/namespace context is in
[reconciliation.json](reconciliation.json). Operator labels alone do not establish
identity: assessment also requires native selected-object/PC fencing and exact
physical/version history for every current Transfer List item, plus exact
trade/item/version history for both watched auctions, joined to independently
retained authenticated native responses in the same namespace. This does not
extract raw EA account identifiers or authentication data.

The fresh observations are:

- Native spendable balance: **62,827 coins**.
- Complete Transfer List: **five items**, including account-wide/manual entries;
  wire, callback and repository counts agree and native end-of-list is true.
  Exact physical identities, versions, current trades, prices and states are
  preserved in the reconciliation artifact.
- Watched: **two exact closed/outbid auctions**. The watched API does not certify
  complete account coverage. Its absence of another trade is not terminal proof.
- Unassigned: **zero returned items**; no claim of complete club inventory.
- The selected account retains one conservative, unexecuted item-3 reservation:
  version 278046, `trade:057aeb82a3b167642da7aeee`, physical
  `item:a7ab887f475aec2049288c42`, **700 coins**. It lacks a current watched mapping.
  The conservative policy amount after that reservation is **62,127**; this is
  not a second EA balance or a newly inferred debit.
- There are **no pending journal mutation intents**. A last transport bid remains
  ACKNOWLEDGED while its journal command is RECONCILED; both original records are
  preserved. No status rewrite, blind retry or redispatch was performed.
- All **six selected-account completed quotes are expired** under the unchanged
  86,400-second TTL. One older quarantined-account quote and its separate unresolved
  capacity slot are preserved under their own scope and confer no authority here.

The mutation gate remains **closed**. The unmapped ghost stays reserved pending
independent reconciliation, with no guessed native IDs and no absent-to-LOST
inference. Fresh reads are proof at capture time only: future mutation ownership
requires new reads, current cache assessment and settlement of ambiguity. This
task establishes and preserves the baseline; it grants no dispatch permission.
The historical finite runtime's one-page discovery override is retained as
evidence. Future production must use the normal three-page `Config` default.

## Retained Objective 002 state and repeatable verification

`obj-29bea3b74eb3` and `002-12` remain **BLOCKED**, attempts remain **4**, and no
recheck is requested. The immutable review-05 verdict remains
**PARTIAL/NOT FULL PASS**, with the original missing proofs and failed callbacks.
All stopped windows, active-time/request counters, mailbox history, journal
rows and consumed budgets remain intact. Artifact checks compare Objective 002
execution-turn metadata and durable actor state against the new consistent backup.

Run independently from the workspace:

```text
python tests/check_00301_baseline.py
python tests/test_00301_baseline.py
```

The first command checks all six acceptance criteria against actual artifacts,
SQLite state, Git ancestry and the published remote branch. The second adds
behavioral and negative cases for missing context/backups, competing processes,
unawaited ownership transfer, failed regressions, Objective 002 unblocking,
identity changes, stale/unauthenticated/incomplete native reads, missing physical
continuity and mutation denial. Neither command dispatches native work or starts
production actors.

The only persistent service left by this task is read-only. Its status is
`GET http://127.0.0.1:8784/health`; `mutations_enabled` must be false. Stop that
specific service with `Stop-Process -Id 1372; Wait-Process -Id 1372` only after
verifying the PID still identifies `fc_access.production_v1.server`. No actor
uptime or continuous-production coverage is claimed by 003-01.

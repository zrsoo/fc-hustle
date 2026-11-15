# 003-03 live coverage preparation

The prelaunch package consists of the explicit 24-case
[matrix](live-coverage-matrix.json), [control handoff](monitoring-handoff.json),
[independent assessment procedure](independent-assessment.md) and the local-only
`fc_access.continuous_v1.evidence` collector/assessor. Preparation does not launch
production or claim any new EA operation, current-run live outcome or healthy hour.
Every current-run row starts LIVE-UNVERIFIED. The historical Objective 002 verdict
remains PARTIAL/NOT FULL PASS, including failed listing and bulk callbacks.

Each row distinguishes scoped prior live observations (with retained report and
outcome references), named current-revision behavioral checks and independent
current-run proof. Its explicit requirements supplement the shared command/read/
native response/durable state/incident/healthy segment evidence contract. The
selected offline checks run against the current implementation; their receipt is
`behavioral-results.json`. An offline pass cannot promote a live status. Historical
failed callbacks cannot become new successful execution, even after an old effect
is independently reconciled. No current-run identity is fabricated for preparation.

The matrix is finite, covering known state-machine branches and observed defects.
New cases join the matrix and stop/diagnose/reconcile/fix/test/recover/reassess loop.
It makes no claim to exhaust every possible unknown edge case. Natural cases stay
unverified until witnessed. Never manufacture wins, sales, outbids, reserve breaches
or 50-slot saturation. No price/reserve/capacity setting changes for coverage.

Safe lifecycle checks first gate new writes with the supported stop command and
await bounded in-flight work and all child exits. Preserve any unresolved intent
as UNKNOWN; a timeout is not proof of cancellation. Capture its diagnostics and
commitments, independently reconcile through the supported read-only recovery,
and require exact current identity mappings before READY. Missing ghost mappings
stay reserved and gated. Do not guess native IDs or blindly replay old commands.
There is no separate live pause/reconnect command: use documented stop/recover.
Do not perform manual market actions merely to exercise unrelated browser traffic.

Realized-profit accounting is **DEFERRED**, excluded from acceptance. Transaction,
actual paid-cost, intent, ownership and gross-sale records remain preserved for
reconciliation and evidence. Estimated return is never reported as realized profit.

The production operator who launches run/recover owns the persistent supervisor
and monitor until a named replacement acknowledges the run, paths, status and
controls. The AI conversation is not the heartbeat. See the detailed
[production controls](../../../continuous-production.md). Before launch review,
commit/push and verify the 003-02 dependency and this package, check for competing
owners, service authority, extension attachment, persona, authentication and EA
market success separately. The known ghost identity prerequisite remains a live
startup gate, not a blocker to preparing this package. No live recovery is needed
to validate this preparation.

The watchdog persists local health SNAPSHOT records each second with zero added
EA polling. The operator exports the five evidence DBs every 300 seconds and on
incidents, stop, repair, recovery or handoff, using a new UTC output directory:

```powershell
python -m fc_access.continuous_v1 status
python -m fc_access.continuous_v1 stop
python -m fc_access.continuous_v1.evidence capture --state-dir private-captures/continuous-production --transport <existing-reviewed-transport-database> --output private-captures/continuous-evidence/<unique-UTC-snapshot> --revision <reviewed-launch-commit>
python -m fc_access.continuous_v1.evidence assess private-captures/continuous-evidence/<unique-UTC-snapshot>
python -m fc_access.continuous_v1 recover --context <reviewed-public-context.json>
```

Resolve placeholders from the existing reviewed launch record; they are not new
empty databases. Preserve the same state, journal, cache, transport and public
context. The declared launch revision is descriptive provenance, independently
checked against the launch/repair record; no mutable source digest is enforced.
For a nondefault state, place `--state-dir <same-path>` before the control
action. Capture opens only local databases in read-only mode and creates fresh
copies using SQLite backup, including committed WAL data. It never opens a browser
or sends EA requests. Each DB is consistent individually; cross-DB identity or
capture-boundary races need independent joins and another snapshot. The manifest
is written last; a partial export is not admissible. Integrity digests apply only
to sealed evidence copies, never source, tests, instructions or configuration.
Keep captures private; retain only the existing sanitized native protocol bodies
and public correlation labels, never credentials, cookies, headers or tokens.

On lost supervision the broker's lease gates dispatch, records a gap and stops
the segment. Request stop and verify every owned child exit; retain uncertain
effects, commands and incidents. The monitor cannot supply its own missing lease.
Check status and process/lock ownership before recover; do not start a replacement
over an old owner. A stale/unavailable monitor, disk failure or inability to keep
the persistent owner means stop safely and report the gap. Do not leave silent
unmonitored mutations running when the conversation ends. Reconcile independently
before further writes and start a new healthy segment after interruption/fix.
Never count the gap as healthy or reset consumed historical windows/budgets.

Reproducible preparation validation (all offline):

```powershell
python tests/check_00303_preparation.py
python tests/test_00303_preparation.py
```

The first validates the artifact contracts and executes every selected behavior
plus browser traffic suites, retaining actual argv/results. The second exercises
collector/assessment with real temporary SQLite and native doubles, integrity and
identity rejection, failed/unknown outcomes, per-run uptime, malformed artifacts,
missing cases and dishonest proof promotion. Neither command starts live actors.

Verification completed with **27 preparation/evidence tests**, **22 selected
current-implementation behavioral tests** and **2 Node browser-traffic suites**
passing. `behavioral-results.json` retains the executed test identities, outputs,
exit results and descriptive revision/working-tree provenance. All 24 current-run
cases remain LIVE-UNVERIFIED; realized-profit accounting remains DEFERRED.

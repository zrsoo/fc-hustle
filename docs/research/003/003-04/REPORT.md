# 003-04: startup stopped at preserved identity reconciliation

**BLOCKED; operational acceptance is incomplete.** The mandatory startup
reconciliation cannot map the preserved 700-coin, decision-only reservation to
a current official native auction. The separate exact-status diagnostic returned
`known_identity_unavailable`, before making any EA request. Ordinary browser,
authentication and localhost attachment prerequisites were available. This is not
a claim of an EA market ban, a login challenge, or a missing natural coverage case.

The reservation is trade `trade:057aeb82a3b167642da7aeee`, physical item
`item:a7ab887f475aec2049288c42`, definition 278046. Its native terminal state
remains UNKNOWN. Missing watched coverage does not establish LOST. The canonical
journal has no bid command for this trade, but the reviewed startup policy
explicitly keeps an unmapped reservation gated. See the
[003-02 review](../003-02/REPORT.md),
[003-03 handoff](../003-03/monitoring-handoff.json), and
[incident](incident-00304-20261115T171217Z.json).

Continuing requires independently verifiable official native evidence resolving
this exact identity, or an explicit amendment permitting audited withdrawal of
a proven decision-only reservation. No reservation was dropped, no native ID was
guessed, no absent row was converted to LOST, and no consumed command was replayed.
A login or extension click alone does not resolve this prerequisite. Runtime
changes that bypass this gate would violate the preserved launch requirements.

## Actual execution and evidence

The preparation implementation, matrix, collector and handoff were reviewed,
tested, committed and pushed separately as
`c4c7b5e5f8e036185dd6243143c0873733ec92c7` before startup. The 003-02 independent
checker passed, including publication ancestry. The previously dirty 003-02
regression receipt files were retained separately; this task did not discard or
stage those unrelated changes.

Fresh official read-only reconciliation at 17:10:20 UTC on 2026-11-15 obtained four
distinct, paced native GETs: watched, credits, complete Transfer List and unassigned.
The selected FC27 PC context and exact watched/physical inventory history match the
preserved account/persona/namespace. At capture, credits were **62,827**, complete
occupied Transfer List **5**, pending mutation intents **0**, and the conservative
local reservation **700**. These are capture-time observations, not assertions of
current account balance after the later infrastructure interruption. See
[raw native capture](prelaunch-20261115T171020Z.jsonl) and
[independent reconciliation](prelaunch-reconciliation.json).

The worker reread AGENTS.md and verified its own Edge access, the intended official
tab and foreground. Initial foreground attempts failed; UI Automation focus of the
identified Web App tab and the existing reviewed foreground helper succeeded.
The existing authenticated session required no login, so no saved credential was
read or entered. The designated saved account remains zzorniss. No credentials,
cookies, authentication headers, tokens or EA session identifiers were extracted.
The native bridge retains only its existing public correlation fences. An extra
attachment recording attempt exited 1 and its error text was not retained; this
failure is preserved in [browser-recovery.jsonl](browser-recovery.jsonl). Separate
service health observations verify attachment. No CAPTCHA, 2FA, security challenge
or missing credential was encountered or bypassed.

The prior read-only service was stopped and its exit awaited before starting the
reviewed journal-backed service on the same transport database. There was no
competing actor/controller. Consistent backups of journal, cache and transport
were retained under the private path in [backup-receipt.json](backup-receipt.json).
No new empty account journal or historical experiment runner was used.

Exactly one production boot was issued, without a wall/request/cycle/enrollment
cap, under run `c7485d279225b0b726a5f6117a68ba10`, owner epoch **65**, revision
`c4c7b5e5f8e036185dd6243143c0873733ec92c7`. Its persistent supervisor and independent
watchdog started. Startup made three fresh native GETs under the new fence:
watched, balance and complete Transfer List. Each is independently retained in
both control recovery records and the transport database.

The executor recorded
`unmapped_commitment_requires_independent_reconciliation` at control sequence 35.
The controlled stop is sequence 36. Sequence 42 records all child exits verified,
no remaining processes, and the healthy segment closed. READY was never recorded.
Acquirer, Bidder and maintenance workers were never launched. **No strategy trade,
account mutation or healthy monitored second is claimed.** The startup watchdog's
pre-READY snapshots correctly report zero healthy time and stale observations
where freshness has not yet been re-established.

The mutation-capable service then exited and was replaced with the original
read-only authority. An initial exit check observed a service still exiting; a
subsequent independent process/liveness check verified actual exit before the
replacement was started. The later exact-status command
`bc93151a719733f812c305ed70fda017` is a new read-only diagnostic, not a replay:
`known_identity_unavailable`, request count **0**, native network **[]**. Its
command/response is joined to a separate sealed transport copy.

The five startup databases are sealed at
`private-captures/continuous-evidence/00304-startup-20261115T171217Z/`.
[Structural assessment](startup-structural-assessment.json) checks their captured
integrity, native/transport identities and separately reconstructs zero healthy
time. The supplemental diagnostic transport is sealed at
`private-captures/003-04/sealed-diagnostic/transport.sqlite3`.
[Captured-evidence integrity](captured-evidence-manifest.json) applies only to
immutable native captures, execution receipts, captured observations and logs;
it contains no mutable implementation, test, instruction or configuration pins.

## Recovery, remaining work and checks

After the conversation infrastructure interruption, the same session inspected
the actual Git remote, control database, process list and localhost health.
[Resume reconciliation](resume-reconciliation.json) confirms the original run is
still STOPPED, its sealed zero-second segment remains intact, and PID 17624 is
the read-only service with `mutations_enabled=false`. No actor was left running,
no replacement run was opened, and no native command or mutation was repeated
while reconciling the interruption. The conversation's elapsed time does not count
as healthy monitored runtime.

All 24 current-run cases remain **LIVE-UNVERIFIED** in the
[run matrix](live-coverage-matrix.json). Historical Objective 002 PARTIAL verdicts,
failed callbacks, consumed windows and counters remain preserved. No natural
event was manufactured and lack of an event is not the reason for this stop.
Realized-profit accounting remains DEFERRED.

Three actual offline runtime regressions passed: preserving an unmapped ghost,
independent reconciliation of a lost response without replay, and invalidation
of interrupted deliveries without history deletion. Their actual commands and
outputs are in [gate-regressions.json](gate-regressions.json).

Twenty new behavioral/artifact checks pass. They exercise all ten criterion
checks and reject absent live operations, unsupported coverage promotions,
generic successful GETs masquerading as each required branch, stale/unverified UI,
credential access, incomplete incidents, unawaited process exits, unsafe repair
ordering, unpublished repairs, reused owner epochs, missing reconciliation,
reopened segments, cumulative-window uptime, clock/heartbeat gaps, account
invariants, and captured-evidence tampering. These offline successes cannot
satisfy the live acceptance criteria.

Run independently from the workspace:

```text
python tests/test_00304_live.py
python tests/check_00304_live.py
```

The first checks the preserved startup episode via `startup-evidence-index.json`.
The second uses the current `evidence-index.json`, evaluates **all ten** criteria,
and intentionally exits **1 / INCOMPLETE** while live obligations are unmet.
The latter is the full acceptance validator, not a human prerequisite check.
Private evidence databases must remain available in this workspace.

After exact commitment resolution, independently reconcile again through the
supported `recover` control with the existing context, journal, cache and state.
Retain the stopped segment and incident, use a fresh fenced owner, and keep the
persistent watchdog active. Runtime repairs require stopped/exited processes,
meaningful offline regressions and commit/push before restart. Update the current
evidence index and run matrix with genuine new captures and independent case
reviews, without rewriting this stopped episode. Continue until all required
cases and at least four consecutive healthy monitored hours on the final revision
are evidenced. Four hours remains a minimum milestone, not a shutdown timer.

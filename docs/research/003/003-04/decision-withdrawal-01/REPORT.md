# 003-04: withdraw the certified decision-only reservation

The 700-coin startup blocker has been removed through an audited local
withdrawal. Fresh production startup reconciliation subsequently passed through
the authenticated official FC27 PC bridge: three genuine EA GETs, zero account
mutations, zero actor launches, zero unresolved commitments. Continuous actor
operation and the four-hour/live-case acceptance requirements remain outstanding.

The user explicitly requested: **“ok, fix that and trigger recheck”**, after the
blocker was identified as an admission reservation for which no bid was sent.
That authorizes this narrow local withdrawal. It does not authorize treating
unmapped real or ambiguous transactions as lost, clearing history, or resetting
any consumed experiment window.

## Root cause and exact identity

`Foundation.admit` correctly reserves coins and a potential-win slot before its
separate `bid` operation. The completed read-only 002-03 gate exercised admission
without invoking `bid`, but left its admission in the canonical journal. Startup
recovery subsequently treated that enrollment as an unresolved auction commitment.
After browser reconnect there was no native mapping for it; fresh watched reads
could not independently establish an auction outcome. Preserving that generic
unknown was correct under the previous policy. Browser focus, authentication and
the user's later removal of lost watched auctions cannot resolve this local
decision-only reservation.

| Field | Sanitized value |
|---|---|
| Scope | `e7fce7c176935f0b95dc3db91dd28521` |
| Trade | `trade:057aeb82a3b167642da7aeee` |
| Physical item | `item:a7ab887f475aec2049288c42` |
| Exact definition | `278046` |
| Local reservation | `700` coins; one potential-win slot |
| Enrollment | journal sequence `14`, `2026-11-14T02:42:19.484924+00:00` |
| Certificate | [002-03 read-only gate](../../../002/002-03/attempts/20261114-adapter-repair-gate-06/gate.json) |

The certificate independently validates its captured native responses and
`BID/ELIGIBLE` decision, measured at 12.0698056 seconds, with zero account
mutations and zero journal bid commands. All 34 command/response pairs still
match the retained transport. The target had one ENROLLED event, one matching
gate decision, subsequent missing-identity diagnostics, and **no** durable bid,
mailbox mutation, transport mutation, resale intent or bulk intent for its
trade/item identity. The audit examined all 31 historical mailbox mutations and
all 31 transport mutations, across all command states.

## Backup, repair and preservation

Before changes: main at `0a01535e1ac1ba3f8ce20321e9e066324b5361b2`.
Local backup tag: `backup/decision-withdrawal-20261115T214057Z`.
`private-captures/decision-withdrawal/20261115T214057Z/` retains the repository
bundle, dirty-tree patch and five consistent database backups. All five SQLite
integrity checks returned `ok`. The six pre-existing dirty 003-02 receipt files
were preserved and excluded from this commit.

`fc_access/continuous_v1/withdrawal.py` implements an explicit, finite operator
operation. It validates the sealed read-only certificate, exact context,
identity, amount, enrollment timestamps and native read IDs. A matching durable
command in **any** state vetoes withdrawal, including RECONCILED and
NOT_DISPATCHED. Missing gate transport records, orphan evidence, trading
provenance, identity conflicts and ambiguous account-wide writes also veto it.
Unrelated bulk mailbox DONE rows require their actual independently reconciled
journal and transport records; delivery alone is insufficient.

Account/controller/executor/bid process locks exclude running owners. Explicit
zero-row updates acquire both attached WAL write locks, preventing a producer
from queuing a mutation between verification and commit. These lock operations
change no mailbox or transport row. A single journal transaction fences the old
owner, stores immutable `admission_withdrawals_v1` proof, appends
`ADMISSION_WITHDRAWN` and a registry audit, and changes the slot to `WITHDRAWN`.
Failure rolls back the owner, audit, event and slot together. Repetition is a
verified idempotent no-op.

AuctionQueue restart replay now releases that local reservation and invalidates
its old balance observation. Capacity migration also replays the withdrawal;
the registry displays local WITHDRAWN with actual auction state UNKNOWN.
Sticky DRAINING, other scopes, real/ambiguous writes, pending resale and generic
unmapped commitments retain their existing protections. Startup does not
automatically invoke this repair.

The rehearsal used database copies and passed independent assessment. The actual
application then fenced epoch 65 to 66 at `2026-11-15T21:57:31.395632+00:00`.
[Application receipt](application.json) and [rehearsal receipt](rehearsal.json)
record the exact proof and checks. Before/after captures remain at
`private-captures/decision-withdrawal/application-01/{before,after}.sqlite3`.
Independent assessment confirmed every original event and registry row remained
unchanged, all bid/resale/bulk commands and inventory records were unchanged,
and exactly the target local slot was released. No EA loss, win, refund or
balance increase was invented.

## Behavioral verification

The first full discovery ran **871 tests, one failure, zero errors**. The failure
was `test_00301_baseline.ReconciliationBehavior.test_all_criteria_artifacts_are_independently_checked`:
the completed baseline validator compared its old snapshot with the entire
evolving runtime database. Later owner epochs already invalidated that equality;
the authorized withdrawal also changed its current commitment projection.

The baseline's historical reconciliation and cache checks now read its original
captured databases. Current-state preservation checks still reject removed or
rewritten historical events, consumed commands, intents and counters; they allow
append-only new work and monotonic owner/schedule changes. Capacity identities
and inventory read lineage remain checked. The historical ghost-reservation
test also uses its original snapshot, where its expectation remains true.
Five new behavioral regressions cover new sessions/appends, rewritten evidence,
requeued consumed commands, unfenced owner changes and schedule resets.

The 24 withdrawal tests cover the certificate, every dangerous command state,
same-item/different-trade conflicts, incomplete evidence, completed versus
reconciled bulk operations, trading provenance, rollback, locking and the WAL
enqueue race, scope isolation, sticky DRAINING, immutable audit, replay/migration,
idempotency and independent before/after assessment including a negative capture.
The original generic startup ghost-preservation regression remains in place.

Commands and receipts:

```text
python -m unittest discover -s tests -v
python tests/test_00304_withdrawal.py -v
python tests/test_00301_baseline.py
node tests/<each *checks.cjs file>
python tests/validate_00203_gate.py --attempt 20261114-adapter-repair-gate-06
python tests/check_bidding_v1_artifacts.py
python -m fc_access.release_audit_v1
python tests/check_00301_baseline.py
python tests/check_00302_production.py
python tests/check_00303_preparation.py
python tests/check_00304_withdrawal.py --before private-captures/decision-withdrawal/application-01/before.sqlite3 --after private-captures/decision-withdrawal/application-01/after.sqlite3
git diff --check
```

Final full discovery passed **879 tests, zero failures, zero errors** in
336.321 seconds (runner wall time 336.972 seconds).
The 27 Node suites and the gate, bidding, release, 003-02 and 003-03 independent
validators passed. Focused final checks passed: withdrawal **24/24**, baseline
**22/22**. [First-run commands/results](checks.json) preserve the discovered
failure; [final-run commands/results](final-checks.json) retain the corrected
full-suite and independent withdrawal results. A validator that regenerated a
003-03 receipt had that new result copied here before its historical file was
restored; the old evidence was not replaced.

## Actual read-only startup E2E

```text
python tests/probe_00304_recovery.py --output docs/research/003/003-04/decision-withdrawal-01/live-recovery
```

The finite probe constructs the actual Foundation with the existing canonical
journal/cache and calls actual `continuous_v1.recovery.reconcile`. Its transport
permits exactly three operations in order, and no writes. It verifies the
existing authenticated attached official FC27 PC context and read-only service,
then claims a fresh fenced epoch **67**. It starts no actors, scheduler or
controller. Attachment alone is not counted as successful authentication.

| Operation / command ID | Actual EA method and path | HTTP | UTC network time |
|---|---|---|---|
| Watched `6068da4508020a2c8df82b28222c2f9d` | GET `/ut/game/fc27/watchlist` | 200 | 22:02:10.397 |
| Credits `3addbc54c0d93655cc8fe467029792dd` | GET `/ut/game/fc27/user/credits` | 200 | 22:02:12.393 |
| Transfer List `43084de8688231c7599425e096e2bc2a` | GET `/ut/game/fc27/tradepile` | 200 | 22:02:14.398 |

All three occurred on **2026-11-15 UTC**, each with one actual native GET and
sanitized query `{}`. The exact commands, responses, identity fences, native
timings and before/after registry projections are in
[native evidence](live-recovery/native.jsonl). No credentials or session values
were read, exposed or persisted.

[Probe result](live-recovery/result.json): **PASS**; 62,827 credits; complete
Transfer List occupancy **5**; unresolved commitments **0**; pending resale **0**;
pipeline total **5**. Both credits and inventory were fresh. Three command
attempts produced three responses. Zero bids, purchases, moves, listings or
maintenance mutations occurred.

The watched response contained two entries and explicitly incomplete coverage;
its omissions were not used as proof of LOST. Transfer List completeness was
corroborated by matching wire/callback/repository counts of five and native
end-of-list evidence. All five returned pile entries were active.

[Independent verification](live-independent.json) reparsed all three captured
responses with production protocol validation, checked actual successful EA GET
routes, complete inventory/count, fresh scoped registry state and independent
durable transport joins. The separate transport capture is
`private-captures/decision-withdrawal/application-01/probe-transport.sqlite3`.

## Orchestrator handoff

**The specific local startup blocker is FIXED and live-confirmed.** Preserve
`obj-da182a175410/003-04` and its prior stopped run
`c7485d279225b0b726a5f6117a68ba10`; keep Objective 002 BLOCKED. The original
003-04 report, stopped segment, diagnostic, checkpoints, budgets and prior
PARTIAL/INCOMPLETE verdicts remain untouched.

The existing full live acceptance validator still exits **1 / INCOMPLETE** for
that retained stopped run. This is expected: this repair and its three-read
probe do not demonstrate four healthy hours, real actor strategy operations or
the 24 required live cases. [Acceptance output](soak-acceptance-stdout.txt)
preserves that distinction. Do not mark the task or objective complete.

After committing and pushing this repair/report, trigger exactly the existing
task recheck:

```text
C:/hustle/agent-orchestrator/.venv/Scripts/orchestrator.exe --db C:/hustle/fc-hustle/.orchestrator/state.db recheck obj-da182a175410/003-04
```

The orchestrator owns subsequent recovery and continuous operation. It should
read this report, use the existing canonical context/journal/cache/state, obtain
new owner fences and fresh startup reads, retain the persistent watchdog and
all strategy/account safeguards, and create a new healthy segment without
reopening the old one. Update the current evidence index only with genuine new
run evidence. The probe leaves the service read-only. No second actor controller
is to be started by this repair session; stop after recheck acknowledgement.
